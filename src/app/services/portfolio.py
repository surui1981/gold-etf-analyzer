"""交易业绩分析服务：收益曲线回放重建 + 获利分析总结评估（V0.61.0）。

设计要点
--------
- **不新增数据表**：曲线由 ``trade_records``（成交流水）+ ETF 历史价 **回放重建**，
  历史交易即刻可见，无需等每日快照长期积累；
- **成本口径与 PositionService 一致（均价法）**，保证曲线数字与持仓页对得上；
- **收益率分母统一为「累计买入本金（含手续费）」**，避免净投入为 0 时除零；
- 非交易日录入的成交，顺延到其后的首个交易日生效，避免曲线出现无价格的点。
"""

import bisect
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.repositories.market_data import MarketDataRepository
from app.repositories.position import PositionRepository
from app.schemas.portfolio import (
    EquityCurveOut,
    EquityPoint,
    EquitySummary,
    PerformanceOut,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


class PortfolioAnalyticsService:
    """交易业绩分析：收益曲线 + 获利总结（无状态，可安全复用）。"""

    def __init__(self, repo: PositionRepository, market: MarketDataRepository) -> None:
        self._repo = repo
        self._market = market

    # ───────────────────────── 回放内核 ─────────────────────────
    @staticmethod
    def _replay(
        trades: Sequence[Any],
        price_dates: list[date],
        price_map: dict[date, float],
    ) -> tuple[list[dict[str, Any]], list[tuple[float, datetime]]]:
        """按均价法回放交易流水，产出逐日状态与逐笔平仓盈亏。

        Args:
            trades: 按 ``traded_at`` 升序的 TradeRecord 列表
            price_dates: 升序交易日列表
            price_map: ``{交易日: 收盘价}``

        Returns:
            ``(daily_states, sell_outcomes)``：
            daily_states 每项含 date/qty/cost/realized/invested；
            sell_outcomes 为每笔卖出的 ``(已实现盈亏, 成交时间)``。

        Raises:
            ValueError: 价格序列为空（无交易日无法回放）
        """
        if not price_dates:
            raise ValueError("无可用交易日价格序列，无法回放收益曲线")

        # 交易生效日 = 首个 >= 成交日的交易日（非交易日录入顺延）
        #
        # 成交日晚于价格序列最后一天时（当日盘中录入、行情源 T-1 滞后、
        # 周末/节假日录入），没有“次一交易日”可归属。此时**归入最后一个可得
        # 交易日**而不是丢弃：否则同一响应会出现「sell_count=2 但
        # closed_trades=0 / 累计投入本金 0.00 元」的自相矛盾，持仓页看到
        # 的实时持仓与业绩页完全对不上。
        by_day: dict[date, list[Any]] = defaultdict(list)
        last_idx = len(price_dates) - 1
        for t in trades:
            idx = bisect.bisect_left(price_dates, t.traded_at.date())
            if idx > last_idx:
                idx = last_idx
            by_day[price_dates[idx]].append(t)

        qty = cost = realized = invested = 0.0
        daily: list[dict[str, Any]] = []
        sells: list[tuple[float, datetime]] = []

        for day in price_dates:
            for t in sorted(by_day.get(day, []), key=lambda x: x.traded_at):
                if t.side == "buy":
                    # 成本口径必须与 PositionService.add_trade 一致：
                    # 摊薄成本不含手续费（手续费单独计入“累计投入本金”）。
                    # 若此处把 fee 计入 cost，曲线浮盈会比「获利分析」多亏一份手续费，
                    # 同页两个面板出现两个收益率，损害可信度。
                    gross = t.price * t.quantity
                    cost += gross
                    qty += t.quantity
                    invested += gross + t.fee
                else:
                    if qty <= 0:
                        continue  # 数据异常（无持仓却卖出），跳过避免负成本
                    avg = cost / qty
                    sq = min(t.quantity, qty)
                    pnl = (t.price - avg) * sq - t.fee
                    realized += pnl
                    cost -= avg * sq
                    qty -= sq
                    sells.append((pnl, t.traded_at))
            daily.append(
                {
                    "date": day,
                    "qty": qty,
                    "cost": cost,
                    "realized": realized,
                    "invested": invested,
                }
            )
        return daily, sells

    @staticmethod
    def _holding_days(position: Any, now: datetime) -> float:
        """持仓天数（开仓 → 平仓 / 当前），容忍 naive 与 aware 混用。"""
        start, end = position.opened_at, position.closed_at or now
        if start is None:
            return 0.0
        if (start.tzinfo is None) != (end.tzinfo is None):
            start = start.replace(tzinfo=None) if start.tzinfo else start
            end = end.replace(tzinfo=None) if end.tzinfo else end
        try:
            return float(max((end - start).days, 0))
        except TypeError:  # pragma: no cover - 极端脏数据兜底
            return 0.0

    async def _prices(self, days: int) -> tuple[list[date], dict[date, float]]:
        """ETF 历史价（升序日期 + 映射），任何失败都退化为空序列。"""
        try:
            klines = await self._market.get_gold_history(days=max(days, 30))
        except Exception as exc:
            logger.warning("收益曲线取 ETF 历史价失败: %s", exc)
            return [], {}
        price_map = {k.date: k.close for k in klines}
        return sorted(price_map), price_map

    # ───────────────────────── 收益曲线 ─────────────────────────
    async def equity_curve(self, days: int = 90, account_id: int | None = None) -> EquityCurveOut:
        """回放重建每日收益曲线（持有份数 / 成本 / 市值 / 累计收益率）。

        Args:
            days: 展示区间（自然日，向前回溯）；成本累计仍从首笔交易起算。
            account_id: 账本过滤；None=全部账本（合并口径，同一标的可安全合并）

        Returns:
            EquityCurveOut，含逐日点位与区间汇总；无交易时 points 为空。

        Raises:
            ValueError: 无交易记录或无价格序列（由调用方转 400 / 空态处理）
        """
        trades = await self._repo.list_all_trades(account_id=account_id)
        if not trades:
            return EquityCurveOut(days=days, points=[], summary=EquitySummary())

        price_dates, price_map = await self._prices(days)
        if not price_dates:
            return EquityCurveOut(days=days, points=[], summary=EquitySummary())

        daily, _ = self._replay(trades, price_dates, price_map)

        points_all: list[EquityPoint] = []
        for st in daily:
            price = price_map[st["date"]]
            market_value = st["qty"] * price
            unrealized = market_value - st["cost"]
            total = st["realized"] + unrealized
            ret = (total / st["invested"] * 100) if st["invested"] else 0.0
            points_all.append(
                EquityPoint(
                    date=st["date"].isoformat(),
                    price=round(price, 3),
                    quantity=round(st["qty"], 2),
                    cost=round(st["cost"], 2),
                    market_value=round(market_value, 2),
                    realized_pnl=round(st["realized"], 2),
                    unrealized_pnl=round(unrealized, 2),
                    total_pnl=round(total, 2),
                    return_pct=round(ret, 2),
                )
            )

        # 只展示最近 days 个自然日（回放成本已含更早交易）
        if points_all:
            cutoff = date.fromisoformat(points_all[-1].date) - timedelta(days=days)
            points = [p for p in points_all if date.fromisoformat(p.date) >= cutoff]
        else:  # pragma: no cover - 理论不可达（daily 非空）
            points = []

        if not points:  # pragma: no cover
            return EquityCurveOut(days=days, points=[], summary=EquitySummary())

        rets = [p.return_pct for p in points]
        peak, max_dd = rets[0], 0.0
        for r in rets:
            peak = max(peak, r)
            max_dd = max(max_dd, peak - r)

        last = daily[-1]
        summary = EquitySummary(
            latest_market_value=points[-1].market_value,
            latest_return_pct=points[-1].return_pct,
            max_return_pct=round(max(rets), 2),
            min_return_pct=round(min(rets), 2),
            max_drawdown_pct=round(max_dd, 2),
            total_invested=round(last["invested"], 2),
            total_pnl=points[-1].total_pnl,
        )
        logger.info(
            "Equity curve: %s points, latest %+.2f%%, maxDD %.2f%%",
            len(points),
            summary.latest_return_pct,
            summary.max_drawdown_pct,
        )
        return EquityCurveOut(days=days, points=points, summary=summary)

    # ───────────────────────── 获利分析 ─────────────────────────
    async def performance(self, account_id: int | None = None) -> PerformanceOut:
        """获利分析总结评估：已实现 / 浮动 / 胜率 / 盈亏比 / 平均持仓天数。

        Args:
            account_id: 账本过滤；None=全部账本

        Returns:
            PerformanceOut；无任何交易与持仓时返回空态 + 引导文案。
        """
        positions = await self._repo.list_all(account_id=account_id)
        trades = await self._repo.list_all_trades(account_id=account_id)

        if not trades and not positions:
            return PerformanceOut(
                summary="暂无交易记录。记录第一笔买入后，这里会给出已实现盈亏、胜率、"
                "盈亏比与持仓天数分析，帮助你复盘每一笔决策。",
            )

        price_dates, price_map = await self._prices(30)
        if trades and price_dates:
            daily, sells = self._replay(trades, price_dates, price_map)
        else:
            daily, sells = [], []
        latest_price = price_map[price_dates[-1]] if price_dates else 0.0

        realized = daily[-1]["realized"] if daily else 0.0
        invested = daily[-1]["invested"] if daily else 0.0

        # 浮动盈亏与成本：仅未平仓持仓
        open_positions = [p for p in positions if p.status == "open"]
        total_cost = sum(p.avg_cost * p.quantity for p in open_positions)
        unrealized = sum((latest_price - p.avg_cost) * p.quantity for p in open_positions)

        total_pnl = realized + unrealized
        return_pct = (total_pnl / invested * 100) if invested else 0.0

        wins = [x[0] for x in sells if x[0] > 0]
        losses = [x[0] for x in sells if x[0] < 0]
        closed_trades = len(sells)
        gross_profit = sum(wins)
        gross_loss = sum(losses)
        win_rate = (len(wins) / closed_trades * 100) if closed_trades else 0.0
        profit_factor = (gross_profit / abs(gross_loss)) if gross_loss else None

        now = datetime.now(timezone.utc)
        holds = [self._holding_days(p, now) for p in positions]
        avg_hold = (sum(holds) / len(holds)) if holds else 0.0

        best = max((x[0] for x in sells), default=0.0)
        worst = min((x[0] for x in sells), default=0.0)
        avg_trade = (sum(x[0] for x in sells) / closed_trades) if closed_trades else 0.0

        out = PerformanceOut(
            total_pnl=round(total_pnl, 2),
            realized_pnl=round(realized, 2),
            unrealized_pnl=round(unrealized, 2),
            total_cost=round(total_cost, 2),
            total_invested=round(invested, 2),
            total_return_pct=round(return_pct, 2),
            open_positions=len(open_positions),
            closed_positions=sum(1 for p in positions if p.status == "closed"),
            closed_trades=closed_trades,
            win_trades=len(wins),
            loss_trades=len(losses),
            win_rate=round(win_rate, 2),
            buy_count=sum(1 for t in trades if t.side == "buy"),
            sell_count=sum(1 for t in trades if t.side == "sell"),
            best_trade_pnl=round(best, 2),
            worst_trade_pnl=round(worst, 2),
            avg_trade_pnl=round(avg_trade, 2),
            gross_profit=round(gross_profit, 2),
            gross_loss=round(gross_loss, 2),
            profit_factor=round(profit_factor, 2) if profit_factor is not None else None,
            avg_holding_days=round(avg_hold, 1),
        )
        out.summary = self._summarize(out, len(positions))
        logger.info(
            "Performance: total %+.2f (%+.2f%%), realized %+.2f, trades=%s",
            out.total_pnl,
            out.total_return_pct,
            out.realized_pnl,
            closed_trades,
        )
        return out

    @staticmethod
    def _summarize(p: PerformanceOut, position_count: int) -> str:
        """生成面向客户的中文总结（含纪律提示，不构成投资建议）。"""
        parts = [
            f"累计投入本金 <b>{p.total_invested:.2f}</b> 元，"
            f"总盈亏 <b>{p.total_pnl:+.2f}</b> 元（收益率 <b>{p.total_return_pct:+.2f}%</b>）。",
            f"其中已实现 <b>{p.realized_pnl:+.2f}</b> 元"
            f"（{p.closed_trades} 笔平仓：{p.win_trades} 胜 / {p.loss_trades} 负，"
            f"胜率 <b>{p.win_rate:.1f}%</b>），"
            f"浮动 <b>{p.unrealized_pnl:+.2f}</b> 元。",
        ]
        if p.profit_factor is not None:
            parts.append(f"盈亏比 <b>{p.profit_factor:.2f}</b>。")
        if p.closed_trades:
            parts.append(
                f"最佳平仓 {p.best_trade_pnl:+.2f} 元，最差 {p.worst_trade_pnl:+.2f} 元，"
                f"平均每笔 {p.avg_trade_pnl:+.2f} 元，平均持仓 {p.avg_holding_days:.0f} 天。"
            )
        parts.append(f"当前共 {position_count} 笔持仓记录（{p.open_positions} 笔持有中）。")

        # 一句纪律提示：按胜率与盈亏比给出中性观察
        if p.closed_trades == 0:
            tip = "尚无平仓记录，建议先按既定纪律建仓并记录，积累样本后再复盘。"
        elif p.total_pnl >= 0 and p.win_rate >= 50:
            tip = "整体处于盈利状态且胜率过半，注意守住止盈纪律、避免回吐。"
        elif p.profit_factor is not None and p.profit_factor >= 1.5:
            tip = "胜率不高但盈亏比良好（赚大亏小），可继续坚持既有的止损纪律。"
        else:
            tip = "当前样本整体承压，建议复盘入场时点与仓位节奏，控制单笔风险敞口。"
        return "".join(parts) + tip + "（本分析仅供研究参考，不构成投资建议）"
