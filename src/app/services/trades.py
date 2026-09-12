"""交易历史查询服务：多条件筛选 + 均价法回放 + 汇总导出（P1 #6）。

为什么需要「回放」
-----------------
``trade_records`` 只存成交本身（方向/数量/价格/手续费），不含成交时刻的持仓状态。
交易历史页要展示「这笔卖出赚了多少」「成交后还剩多少份」，就必须按均价法
（与 ``PositionService.add_trade`` 同口径）逐笔重放：买入摊薄成本、卖出成本不变。

口径与 V0.61.0 收益曲线保持一致：
- 买入：``cost += price × qty``（**不含**手续费）；``invested += price × qty + fee``
- 卖出：``pnl = (price − avg) × 成交量 − fee``，``avg = cost / qty``
"""

import csv
import io
from collections import defaultdict
from datetime import date

from app.repositories.position import PositionRepository, TradeWithPosition
from app.schemas.trade import (
    TradeHistoryItem,
    TradeHistoryOut,
    TradeHistorySummary,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


class TradeHistoryService:
    """交易历史的筛选、回放与导出（无状态，可安全复用）。"""

    def __init__(self, repo: PositionRepository) -> None:
        self._repo = repo

    async def query(
        self,
        *,
        account_id: int | None = None,
        side: str | None = None,
        position_id: int | None = None,
        symbol: str | None = None,
        keyword: str | None = None,
        start: date | None = None,
        end: date | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> TradeHistoryOut:
        """按条件查询交易历史（分页 + 全量汇总）。

        Args:
            account_id: 账本过滤；None=全部账本
            side: buy / sell；None=全部
            position_id: 指定持仓
            symbol: 品种代码
            keyword: 持仓名称或代码模糊匹配
            start / end: 成交日期区间（含边界）
            page: 页码（从 1 起）
            page_size: 每页条数

        Returns:
            TradeHistoryOut：当前页明细 + 全量汇总 + 分页信息
        """
        # 关键：回放用的流水**不能**带 side / 日期过滤。
        # 均价法的成本依赖买入上下文——只看卖出会把 qty 当成 0，
        # 导致「已实现盈亏」全部算不出来。故分两次取：
        #   scope_rows   = 账本 / 持仓 / 品种 / 关键字（决定「看哪些持仓」）
        #   display_rows = scope + side + 日期区间（决定「看哪些成交」）
        scope_rows = await self._repo.query_trades(
            account_id=account_id,
            position_id=position_id,
            symbol=symbol,
            keyword=keyword,
        )
        if side is None and start is None and end is None:
            display_rows = scope_rows
        else:
            display_rows = await self._repo.query_trades(
                account_id=account_id,
                position_id=position_id,
                symbol=symbol,
                keyword=keyword,
                side=side,
                start=start,
                end=end,
            )

        replay = self._replay_by_position(scope_rows)
        items = [self._to_item(row, replay) for row in display_rows]
        summary = self._summarize(items)

        page = max(page, 1)
        page_size = max(min(page_size, 500), 1)
        total = len(items)
        page_count = max((total + page_size - 1) // page_size, 1)
        page = min(page, page_count)
        start_idx = (page - 1) * page_size

        return TradeHistoryOut(
            items=items[start_idx : start_idx + page_size],
            total=total,
            page=page,
            page_size=page_size,
            page_count=page_count,
            summary=summary,
        )

    async def export_csv(
        self,
        *,
        account_id: int | None = None,
        side: str | None = None,
        position_id: int | None = None,
        symbol: str | None = None,
        keyword: str | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> str:
        """按同样的筛选条件导出全部匹配流水为 CSV 文本。"""
        scope_rows = await self._repo.query_trades(
            account_id=account_id,
            position_id=position_id,
            symbol=symbol,
            keyword=keyword,
        )
        if side is None and start is None and end is None:
            display_rows = scope_rows
        else:
            display_rows = await self._repo.query_trades(
                account_id=account_id,
                position_id=position_id,
                symbol=symbol,
                keyword=keyword,
                side=side,
                start=start,
                end=end,
            )
        replay = self._replay_by_position(scope_rows)
        items = [self._to_item(row, replay) for row in display_rows]
        summary = self._summarize(items)

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["# 交易历史导出", "", "", "", "", "", "", "", "", "", ""])
        writer.writerow(
            [
                "成交时间", "账本", "品种代码", "品种名称", "方向", "数量(份)",
                "成交价(元/份)", "成交金额(元)", "手续费(元)", "已实现盈亏(元)",
                "成交后份额", "持仓ID", "流水ID",
            ]
        )
        for item in items:
            writer.writerow(
                [
                    item.traded_at, item.account_name, item.symbol, item.name,
                    "买入" if item.side == "buy" else "卖出",
                    item.quantity, item.price, item.amount, item.fee,
                    "" if item.realized_pnl is None else item.realized_pnl,
                    "" if item.post_quantity is None else item.post_quantity,
                    item.position_id, item.id,
                ]
            )
        writer.writerow([])
        writer.writerow(["# 汇总", "", "", "", "", "", "", "", "", "", ""])
        writer.writerow(
            [
                "笔数", "买入笔数", "卖出笔数", "买入金额", "卖出金额",
                "净流出", "手续费合计", "已实现盈亏",
            ]
        )
        writer.writerow(
            [
                summary.count, summary.buy_count, summary.sell_count,
                summary.buy_amount, summary.sell_amount, summary.net_amount,
                summary.total_fee, summary.realized_pnl,
            ]
        )
        return buf.getvalue()

    # ───────────────────────── 内部实现 ─────────────────────────
    @staticmethod
    def _replay_by_position(
        rows: list[TradeWithPosition],
    ) -> dict[int, tuple[float | None, float | None]]:
        """按持仓分组做均价法回放，返回 ``{流水ID: (已实现盈亏, 成交后份额)}``。

        买入的已实现盈亏为 ``None``；数据异常（无持仓却卖出）时盈亏为 ``None``
        但给出成交后份额 0，避免整页报错。
        """
        grouped: dict[int, list[TradeWithPosition]] = defaultdict(list)
        for row in rows:
            grouped[row.trade.position_id].append(row)

        outcome: dict[int, tuple[float | None, float | None]] = {}
        for group in grouped.values():
            # 仓库返回倒序，回放必须按时间升序
            ordered = sorted(group, key=lambda r: (r.trade.traded_at, r.trade.id))
            qty = cost = 0.0
            for row in ordered:
                trade = row.trade
                if trade.side == "buy":
                    cost += trade.price * trade.quantity
                    qty += trade.quantity
                    outcome[trade.id] = (None, round(qty, 4))
                    continue

                if qty <= 0:
                    outcome[trade.id] = (None, 0.0)
                    continue
                avg = cost / qty
                sold = min(trade.quantity, qty)
                pnl = (trade.price - avg) * sold - trade.fee
                cost -= avg * sold
                qty -= sold
                outcome[trade.id] = (round(pnl, 2), round(qty, 4))
        return outcome

    @staticmethod
    def _to_item(
        row: TradeWithPosition,
        replay: dict[int, tuple[float | None, float | None]],
    ) -> TradeHistoryItem:
        """ORM 行 → 输出模型（补充成交金额与回放结果）。"""
        trade = row.trade
        realized, post = replay.get(trade.id, (None, None))
        return TradeHistoryItem(
            id=trade.id,
            position_id=trade.position_id,
            account_id=row.position.account_id,
            account_name=row.account_name,
            symbol=row.position.symbol,
            name=row.position.name,
            side=trade.side,
            quantity=trade.quantity,
            price=trade.price,
            fee=trade.fee,
            amount=round(trade.price * trade.quantity, 2),
            realized_pnl=realized,
            post_quantity=post,
            traded_at=trade.traded_at,
        )

    @staticmethod
    def _summarize(items: list[TradeHistoryItem]) -> TradeHistorySummary:
        """汇总全部匹配行（非当前页），保证与筛选结果一致。"""
        buy = [i for i in items if i.side == "buy"]
        sell = [i for i in items if i.side == "sell"]
        buy_amount = round(sum(i.amount for i in buy), 2)
        sell_amount = round(sum(i.amount for i in sell), 2)
        return TradeHistorySummary(
            count=len(items),
            buy_count=len(buy),
            sell_count=len(sell),
            buy_amount=buy_amount,
            sell_amount=sell_amount,
            net_amount=round(buy_amount - sell_amount, 2),
            total_fee=round(sum(i.fee for i in items), 2),
            realized_pnl=round(
                sum(i.realized_pnl or 0.0 for i in sell), 2
            ),
        )
