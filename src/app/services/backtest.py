"""回测引擎（V0.71.0）：在 daily_snapshots 上重算历史分数，输出 Sharpe / 最大回撤 / 校准。

设计：
- 直接读 daily_snapshots（tech_index / macro_index / news_index）作为历史「金标准」，
  无需重算宏观（macro 因子历史不可回溯）；
- 按 weight_grid 笛卡尔积展开参数组合；
- 每组合：用 tech × tech_w + macro × macro_w + news × news_w 合成综合分；
  按阈值带 → 方向 (BULLISH / BEARISH) → T+1 涨跌幅判定命中；
- 聚合 Sharpe（年化 ×√252）/ 最大回撤 / 命中率 / 校准 5 桶；
- 节流：run() 入口处调用 backtest_throttle.get_cached()；命中直接返回。
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.snapshot import DailySnapshot
from app.repositories.review import GoldPriceRepository
from app.schemas.backtest import (
    BacktestCoverageOut,
    BacktestGridRow,
    BacktestRequestIn,
    BacktestResultOut,
    BacktestSummary,
)
from app.schemas.common import DirectionSignal
from app.services import backtest_throttle as throttle
from app.services.review import judge_hit
from app.services.settings import WeightService
from app.utils.logger import get_logger

logger = get_logger(__name__)


# 样本不足阈值（与 review 对齐）
_MIN_SAMPLES = 20

# 5 桶分箱（与 review._calibration 共享形状）
_CALIBRATION_BUCKETS: tuple[tuple[float, float], ...] = (
    (0, 20),
    (20, 40),
    (40, 60),
    (60, 80),
    (80, 100),
)


def compute_sharpe(daily_returns: list[float], rf: float = 0.0) -> float:
    """日频收益 → 年化 Sharpe（×√252）。

    数据不足（<2）/ 零方差返回 0.0；公式 mean(excess) / std(excess) * sqrt(252)。
    """
    if len(daily_returns) < 2:
        return 0.0
    excess = [r - rf for r in daily_returns]
    mean = sum(excess) / len(excess)
    var = sum((x - mean) ** 2 for x in excess) / len(excess)
    if var <= 0:
        return 0.0
    return round(mean / (var**0.5) * (252**0.5), 2)


def compute_max_drawdown(equity: list[float]) -> float:
    """最大回撤 % = max((peak - cur) / peak * 100)。

    equity 为累计净值序列（从 1.0 开始）；空列表返回 0.0。
    """
    if not equity:
        return 0.0
    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak * 100
            if dd > max_dd:
                max_dd = dd
    return round(max_dd, 2)


def _direction_from_score(
    score: float,
    bullish_threshold: float,
    bearish_threshold: float,
) -> DirectionSignal:
    """按阈值带 → 多空方向（中性区间省略，按 score 在两阈值之间判 NEUTRAL）。"""
    if score >= bullish_threshold:
        return DirectionSignal.BULLISH
    if score <= bearish_threshold:
        return DirectionSignal.BEARISH
    return DirectionSignal.NEUTRAL


@dataclass(frozen=True)
class _SimDay:
    """单日模拟结果。"""

    score: float
    direction: DirectionSignal
    next_return: float  # T+1 涨跌幅 %（用于 Sharpe 与最大回撤）
    hit: bool


class BacktestService:
    """回测编排服务：覆盖期报告 + 参数扫描 + 节流。"""

    def __init__(
        self,
        session: AsyncSession,
        gold: GoldPriceRepository,
        weights: WeightService,
    ) -> None:
        self._session = session
        self._gold = gold
        self._weights = weights

    # ───────────────────── 覆盖期报告 ─────────────────────

    async def coverage(
        self,
        target: str = "etf",
        days: int = 90,
    ) -> BacktestCoverageOut:
        """报告回测数据覆盖期（tech_index 非空的快照天数）。"""
        target = self._normalize_target(target)
        stmt = (
            select(DailySnapshot)
            .where(DailySnapshot.tech_index.is_not(None))
            .order_by(DailySnapshot.snapshot_date.asc())
        )
        rows = list((await self._session.execute(stmt)).scalars().all())
        if not rows:
            return BacktestCoverageOut(
                target=target,  # type: ignore[arg-type]
                start_date=None,
                end_date=None,
                available_days=0,
                available_window_trading_days=0,
                note="daily_snapshots 表为空，无法回测",
                sample_warning=True,
            )
        start = rows[0].snapshot_date
        end = rows[-1].snapshot_date
        available = len(rows)
        return BacktestCoverageOut(
            target=target,  # type: ignore[arg-type]
            start_date=start,
            end_date=end,
            available_days=available,
            available_window_trading_days=available,
            note=(
                f"覆盖期 {start} ~ {end}（{available} 个有效样本）"
                + ("；样本较少，回测结果仅供参考" if available < _MIN_SAMPLES else "")
            ),
            sample_warning=available < _MIN_SAMPLES,
        )

    # ───────────────────── 回测主入口 ─────────────────────

    async def run(self, params: BacktestRequestIn) -> BacktestResultOut:
        """执行回测：节流 → 覆盖期报告 → 网格展开 → 聚合。

        Args:
            params: 包含 days / target / weight_grid / threshold_bands。

        Returns:
            BacktestResultOut（含 rows / summary / coverage / cached 标记）。
        """
        target = self._normalize_target(params.target)

        # 节流检查：同 params 5 分钟内命中
        cache_key = params.model_dump()
        cached = throttle.get_cached(cache_key)
        if cached is not None:
            logger.info("Backtest cache hit (age=%ss)", cached.get("cached_age_seconds", -1))
            return BacktestResultOut(**cached)

        cov = await self.coverage(target=target, days=params.days)
        snapshots = await self._load_snapshots(target=target)
        if len(snapshots) < 2:
            out = BacktestResultOut(
                target=target,  # type: ignore[arg-type]
                days=params.days,
                coverage=cov,
                rows=[],
                summary=BacktestSummary(
                    total_rows=0,
                    best_sharpe=0.0,
                    worst_sharpe=0.0,
                    avg_sharpe=0.0,
                    best_max_drawdown=0.0,
                    avg_win_rate=0.0,
                ),
                cached=False,
            )
            throttle.store(cache_key, out.model_dump())
            return out

        # 准备 T+1 涨跌幅（按快照日期对齐 gold_price_daily）
        next_returns = await self._build_next_returns(
            target=target,
            snapshot_dates=[s.snapshot_date for s in snapshots],
        )

        # 网格展开：tech_w × macro_w × news_w × bullish × bearish
        rows: list[BacktestGridRow] = []
        for tech_w, macro_w, news_w, bull_t, bear_t in itertools.product(
            params.weight_grid.tech,
            params.weight_grid.macro,
            params.weight_grid.news,
            params.threshold_bands.bullish,
            params.threshold_bands.bearish,
        ):
            row = self._evaluate_grid(
                snapshots=snapshots,
                next_returns=next_returns,
                tech_w=tech_w,
                macro_w=macro_w,
                news_w=news_w,
                bullish_threshold=bull_t,
                bearish_threshold=bear_t,
            )
            rows.append(row)

        summary = self._aggregate(rows)

        out = BacktestResultOut(
            target=target,  # type: ignore[arg-type]
            days=params.days,
            coverage=cov,
            rows=rows,
            summary=summary,
            cached=False,
        )
        throttle.store(cache_key, out.model_dump())
        logger.info(
            "Backtest run: target=%s rows=%d best_sharpe=%.2f",
            target,
            len(rows),
            summary.best_sharpe,
        )
        return out

    # ───────────────────── 内部辅助 ─────────────────────

    @staticmethod
    def _normalize_target(target: str | None) -> str:
        """兼容传入未知 target：回退 etf。"""
        valid = {"ny", "etf", "gram", "silver_ny", "silver_etf"}
        return target if target in valid else "etf"

    async def _load_snapshots(self, target: str) -> list[DailySnapshot]:
        """加载所有有效快照（按日期升序）。"""
        stmt = (
            select(DailySnapshot)
            .where(DailySnapshot.tech_index.is_not(None))
            .order_by(DailySnapshot.snapshot_date.asc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def _build_next_returns(
        self,
        target: str,
        snapshot_dates: list[date],
    ) -> dict[date, float]:
        """构造 T+1 涨跌幅映射：snapshot_date → 下一交易日的收盘涨跌幅 %。

        实现：读 gold_price_daily（target 维度）按日期升序，对齐后算 close[i+1]/close[i]-1。
        缺失或最后一个返回 0.0（无 T+1 数据）。
        """
        if not snapshot_dates:
            return {}
        start = snapshot_dates[0]
        end = snapshot_dates[-1] + timedelta(days=5)  # 缓冲覆盖后续交易日
        bars = await self._gold.list_range(target, start=start, end=end)
        if len(bars) < 2:
            return {d: 0.0 for d in snapshot_dates}
        # 按日期构造 close 序列
        by_date: dict[date, float] = {b.price_date: b.close for b in bars}
        sorted_dates = sorted(by_date.keys())
        next_close: dict[date, float] = {}
        for i in range(len(sorted_dates) - 1):
            cur, nxt = sorted_dates[i], sorted_dates[i + 1]
            cur_close = by_date[cur]
            nxt_close = by_date[nxt]
            if cur_close > 0:
                next_close[cur] = round((nxt_close - cur_close) / cur_close * 100, 4)
            else:
                next_close[cur] = 0.0
        return {d: next_close.get(d, 0.0) for d in snapshot_dates}

    def _evaluate_grid(
        self,
        snapshots: list[DailySnapshot],
        next_returns: dict[date, float],
        tech_w: float,
        macro_w: float,
        news_w: float,
        bullish_threshold: float,
        bearish_threshold: float,
    ) -> BacktestGridRow:
        """单组参数组合：合成 → 方向 → 命中 → 聚合。"""
        sims: list[_SimDay] = []
        for snap in snapshots:
            score = (
                float(snap.tech_index) * tech_w
                + float(snap.macro_index) * macro_w
                + float(snap.news_index) * news_w
            )
            direction = _direction_from_score(score, bullish_threshold, bearish_threshold)
            ret = next_returns.get(snap.snapshot_date, 0.0)
            hit, _ = judge_hit(direction, ret)
            sims.append(_SimDay(score=score, direction=direction, next_return=ret, hit=hit))

        daily_returns = [s.next_return for s in sims]
        sharpe = compute_sharpe(daily_returns)
        # 构造 equity 序列（从 1.0 开始）
        equity = [1.0]
        for r in daily_returns:
            equity.append(equity[-1] * (1 + r / 100))
        max_dd = compute_max_drawdown(equity)
        wins = sum(1 for s in sims if s.hit)
        win_rate = wins / len(sims) if sims else 0.0

        return BacktestGridRow(
            tech_w=tech_w,
            macro_w=macro_w,
            news_w=news_w,
            bullish_threshold=bullish_threshold,
            bearish_threshold=bearish_threshold,
            sharpe=sharpe,
            max_drawdown_pct=max_dd,
            win_rate=round(win_rate, 4),
            samples=len(sims),
        )

    @staticmethod
    def _aggregate(rows: list[BacktestGridRow]) -> BacktestSummary:
        """聚合 N 行结果为 summary。"""
        if not rows:
            return BacktestSummary(
                total_rows=0,
                best_sharpe=0.0,
                worst_sharpe=0.0,
                avg_sharpe=0.0,
                best_max_drawdown=0.0,
                avg_win_rate=0.0,
            )
        sharpes = [r.sharpe for r in rows]
        drawdowns = [r.max_drawdown_pct for r in rows]
        win_rates = [r.win_rate for r in rows]
        return BacktestSummary(
            total_rows=len(rows),
            best_sharpe=max(sharpes),
            worst_sharpe=min(sharpes),
            avg_sharpe=round(sum(sharpes) / len(sharpes), 2),
            best_max_drawdown=min(drawdowns),  # 越低越好
            avg_win_rate=round(sum(win_rates) / len(win_rates), 4),
        )