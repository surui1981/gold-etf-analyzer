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
import json
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
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
from app.services.price_source import (
    TRUSTED_PRICE_SOURCES as _TRUSTED_PRICE_SOURCES,
)
from app.services.price_source import resolve_price_source
from app.services.review import judge_hit
from app.services.settings import WeightService
from app.services.trend import TrendService
from app.utils.logger import get_logger

logger = get_logger(__name__)


# 样本不足阈值（与 review 对齐）
_MIN_SAMPLES = 20

# V0.79.0 任务 #163：回测只采信这些来源的快照。
# ⚠ ``mock`` 必须排除（编造的价格）；``None``（历史未标记）也排除 ——
# 宁可样本少，也不要用不可信数据算出「看似正常」的 Sharpe。
_TRUSTED_SNAPSHOT_SOURCES: tuple[str, ...] = ("live", "stale")

# V0.79.0：行情来源判定（可否写入价格日历 / target→市场 key 映射）已抽到
# ``services.price_source`` —— 回测与复盘共用，而 ``backtest`` 已 import ``review``，
# 逻辑留在本模块会让 review 反向依赖 backtest ⇒ 循环导入。
# 上面的 ``_TRUSTED_PRICE_SOURCES`` / ``_TARGET_TO_MARKET_KEY`` 是为兼容既有引用的别名。

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


def _aggregate_from_detail(
    detail_json: str | None,
    weights: dict[str, float],
    which: str,
) -> float | None:
    """按 ``weights`` 加权聚合 ``detail_json`` 中的 ``score`` 字段。

    V0.79.0 Step G 新增辅助：

    - ``detail_json=None`` → 返回 None（调用方应跳过该根快照，**非中性 50**）
    - ``detail_json`` 非空但缺失某个 ``weights`` 字段对应的子维度 →
      同样返回 None（V0.78.0 Step D「数据不足 ≠ 中性」纪律）
    - 任意子维度 ``score`` 为 None → 返回 None
    - 任一 ``weights[k]`` 缺失 → 返回 None
    - 解析失败 → 返回 None（容错：旧快照格式漂移不致 500）
    - 否则返回 ``∑ weights[k] * detail[k]["score"]``

    ``which`` 仅用于日志标签（"tech" / "macro"），不影响计算。
    """
    if detail_json is None:
        return None
    try:
        parsed = json.loads(detail_json)
    except (TypeError, ValueError) as exc:
        logger.warning(
            "Backtest %s detail JSON parse failed: %s (treat as data-insufficient)",
            which,
            exc,
        )
        return None
    if not isinstance(parsed, dict):
        return None
    total = 0.0
    for dim, w in weights.items():
        entry = parsed.get(dim)
        if not isinstance(entry, dict):
            return None
        score = entry.get("score")
        if score is None:
            return None
        try:
            total += float(score) * float(w)
        except (TypeError, ValueError):
            return None
    return total


@dataclass(frozen=True)
class _SimDay:
    """单日模拟结果。"""

    score: float
    direction: DirectionSignal
    next_return: float  # T+1 涨跌幅 %（用于 Sharpe 与最大回撤）
    hit: bool


class BacktestService:
    """回测编排服务：覆盖期报告 + 参数扫描 + 节流。

    V0.79.0：新增 ``ensure_price_calendar()`` —— 回测**按需自动回填**价格日历。
    动机：价格日历原先只有一条写入路径（``/review`` 页用户手工点复盘），
    而回测 / 复盘 / 校准曲线**都依赖它** ⇒ 未回填时三者静默返回假结果
    （见 ``coverage()`` 的 ``usable`` 字段）。回测是按需动作，故在
    ``run()`` 里惰性回填而非塞进 07:00 调度器 —— 少一次无谓取数。
    """

    def __init__(
        self,
        session: AsyncSession,
        gold: GoldPriceRepository,
        weights: WeightService,
        trend: TrendService | None = None,
    ) -> None:
        self._session = session
        self._gold = gold
        self._weights = weights
        # ⚠ 可选注入：未注入时 ``ensure_price_calendar`` 直接返回「不可用」，
        # 回测照常跑（只是拿不到价格数据）⇒ **不因缺依赖而 500**。
        self._trend = trend

    # ───────────────────── 覆盖期报告 ─────────────────────

    async def coverage(
        self,
        target: str = "etf",
        days: int = 90,
    ) -> BacktestCoverageOut:
        """报告回测数据覆盖期。

        ⚠ **V0.79.0 起同时检查两类数据**（此前只查快照，是静默假结果的根因）：
          ① ``daily_snapshots``：有哪些日子可评；
          ② ``gold_price_daily``：每日的对错如何判定。
        只查 ① 时，价格日历为空会照常返回 ``best_sharpe=0.0`` + 虚高命中率 +
        ``sample_warning=False``，用户无从分辨「回测无效」与「表现差」。
        """
        target = self._normalize_target(target)
        # ⚠ V0.79.0 任务 #163：与 ``_load_snapshots`` **同一套过滤**（可信来源）。
        # ⚠ 两处口径必须一致 —— 否则 coverage 报的 available_days 与真正参与
        # 网格计算的行数不符，又是一次「披露与实际不符」的静默偏差。
        stmt = (
            select(DailySnapshot)
            .where(
                DailySnapshot.tech_index.is_not(None),
                DailySnapshot.data_source.in_(_TRUSTED_SNAPSHOT_SOURCES),
            )
            .order_by(DailySnapshot.snapshot_date.asc())
        )
        rows = list((await self._session.execute(stmt)).scalars().all())
        if not rows:
            # ⚠ 措辞必须准确：表**可能非空**，只是全部因来源不可信被排除
            # （V0.79.0 #163）。说「表为空」会让用户去查错方向。
            total_stmt = (
                select(func.count())
                .select_from(DailySnapshot)
                .where(DailySnapshot.tech_index.is_not(None))
            )
            total = int((await self._session.execute(total_stmt)).scalar_one())
            return BacktestCoverageOut(
                target=target,  # type: ignore[arg-type]
                start_date=None,
                end_date=None,
                available_days=0,
                available_window_trading_days=0,
                note=(
                    f"无可用快照（共 {total} 条，但全部来源不可信：mock 或未标记）"
                    if total
                    else "daily_snapshots 表为空，无法回测"
                ),
                sample_warning=True,
                price_calendar_days=0,
                returns_available_days=0,
                returns_missing_days=0,
                usable=False,
            )
        start = rows[0].snapshot_date
        end = rows[-1].snapshot_date
        available = len(rows)
        snap_dates = [r.snapshot_date for r in rows]

        # ⚠ V0.79.0 #163：统计「因来源不可信而被排除」的快照数，并在 note 披露 ——
        # 静默排除会让样本量凭空减少却无人察觉（又一次「未执行 ≠ 不存在」）。
        excluded_stmt = (
            select(func.count())
            .select_from(DailySnapshot)
            .where(
                DailySnapshot.tech_index.is_not(None),
                ~DailySnapshot.data_source.in_(_TRUSTED_SNAPSHOT_SOURCES),
            )
        )
        excluded = int((await self._session.execute(excluded_stmt)).scalar_one())

        # ── 价格日历维度（V0.79.0 新增）──
        # 必须实际查表：T+1 收益只能由「同 target 的相邻两个交易日收盘价」推出，
        # 最后一个快照日之后没有价格 ⇒ 天然无收益。
        cal_days = await self._gold.count_in_range(
            target=target, start=start, end=end + timedelta(days=5)
        )
        returns_ok = await self._count_days_with_next_close(
            target=target, snapshot_dates=snap_dates
        )
        returns_missing = available - returns_ok
        usable = returns_ok > 0

        parts = [f"覆盖期 {start} ~ {end}（{available} 个有效样本）"]
        if available < _MIN_SAMPLES:
            parts.append("样本较少，回测结果仅供参考")
        if excluded:
            parts.append(
                f"已排除 {excluded} 天来源不可信（mock 或未标记）的快照；"
                "历史快照均无来源标记，故从今日起才逐步可用"
            )
        if cal_days == 0:
            parts.append(
                "**价格日历为空，Sharpe 与命中率无法计算**"
                "（须先在复盘页执行价格回填）；下列指标是填充值而非回测结论"
            )
        elif returns_missing:
            parts.append(f"其中 {returns_missing} 天因缺后继交易日价格而未参与指标计算")

        return BacktestCoverageOut(
            target=target,  # type: ignore[arg-type]
            start_date=start,
            end_date=end,
            available_days=available,
            available_window_trading_days=available,
            note="；".join(parts),
            # ⚠ 样本告警的判定**不能只看快照天数**：即使快照充足、价格日历为空，
            # 结果同样不可用（收益全 0 ⇒ Sharpe 恒 0、NEUTRAL 行全命中）。
            sample_warning=available < _MIN_SAMPLES or not usable,
            price_calendar_days=cal_days,
            returns_available_days=returns_ok,
            returns_missing_days=returns_missing,
            usable=usable,
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

        # V0.79.0：价格日历为空时**先尝试按需回填**，再重新评估覆盖期。
        # 放在 coverage 之后、网格展开之前 —— 顺序有讲究：
        #   ① 先看现状（多数请求有数据，不做无谓的取数）；
        #   ② 回填失败不抛异常（增强而非前置），此时 cov 仍是「不可用」，
        #      后面的 rows/summary 会如实带上 usable=False；
        #   ③ 回填成功才重算 coverage，否则用户拿到的还是回填前的口径。
        if not cov.usable:
            wrote, why = await self.ensure_price_calendar(target=target, days=params.days)
            logger.info(
                "Backtest lazy price-calendar backfill: target=%s wrote=%s (%s)", target, wrote, why
            )
            if wrote:
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
                    usable=cov.usable,
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

        # 网格展开（V0.79.0 Step G）：7 维笛卡尔积
        # tech_w × macro_w × news_w × bullish × bearish × (trend_5 or 1) × (macro_5 or 1)
        # ⚠ trend_weights / macro_weights 未启用（=None）时退化为 ``[None]`` 元素，
        # itertools.product 中保留该维度但 ``_evaluate_grid`` 拿到 None 时走扁平路径
        # —— 与 V0.71.0 旧行为逐位等价（同一份 ``snap.tech_index``）。
        wg = params.weight_grid
        trend_iter = wg.trend_weights.weights if wg.trend_weights else [None]
        macro_iter = wg.macro_weights.weights if wg.macro_weights else [None]
        rows: list[BacktestGridRow] = []
        for tech_w, macro_w, news_w, bull_t, bear_t, tr_w, ma_w in itertools.product(
            wg.tech,
            wg.macro,
            wg.news,
            params.threshold_bands.bullish,
            params.threshold_bands.bearish,
            trend_iter,
            macro_iter,
        ):
            row = self._evaluate_grid(
                snapshots=snapshots,
                next_returns=next_returns,
                tech_w=tech_w,
                macro_w=macro_w,
                news_w=news_w,
                bullish_threshold=bull_t,
                bearish_threshold=bear_t,
                tech_dim_weights=tr_w,
                macro_dim_weights=ma_w,
            )
            rows.append(row)

        summary = self._aggregate(rows)
        # ⚠ V0.79.0：聚合结果的可用性**继承 coverage**。价格日历为空时 rows 里的
        # sharpe / win_rate 是「收益全 0」推导出的填充值（Sharpe 零方差 → 0.0；
        # judge_hit 对 NEUTRAL 判 |0| <= band → 全命中），若不标记，调用方无法
        # 分辨「回测无效」与「回测有效但表现差」。
        summary.usable = cov.usable

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
            "Backtest run: target=%s rows=%d best_sharpe=%.2f usable=%s returns_ok=%d/%d",
            target,
            len(rows),
            summary.best_sharpe,
            cov.usable,
            cov.returns_available_days,
            cov.available_days,
        )
        return out

    # ───────────────────── 价格日历按需回填（V0.79.0）─────────────────────

    async def ensure_price_calendar(
        self,
        target: str,
        *,
        days: int = 90,
        force: bool = False,
    ) -> tuple[bool, str]:
        """价格日历为空时按需回填。返回 ``(是否写入, 说明)``。

        ⚠⚠ **三条不可退让的约束**（都源于本次修复的教训）：

        1. **只接受真实数据源**。``TrendService`` 在取数失败时会**静默降级为
           mock**，而 mock 价格若写进 ``gold_price_daily``，回测就会基于
           **编造的收盘价**给出看似正常的 Sharpe —— 比「无数据」危险得多。
           故此处**先判 ``data_sources[target] == 'live'/'stale'``，否则直接放弃**，
           不让 ``upsert_many`` 的白名单校验去兜底（那会抛 400 打断回测）。
        2. **失败不抛异常**。回填是**增强**而非前置条件，失败只记录并如实反映在
           ``coverage.usable`` 上；抛异常会把「增强失败」变成「回测不可用」。
        3. **不覆盖已有数据**。``upsert_many`` 本身幂等，但 ``force=False`` 时
           仅在**区间内完全无数据**时才回填，避免每次回测都打数据源。
        """
        if self._trend is None:
            return False, "未注入趋势服务，无法自动回填"

        start, end = await self._existing_calendar_span(target=target)
        if not force and start is not None and end is not None:
            return False, f"价格日历已有数据（{start} ~ {end}），跳过回填"

        try:
            trend = await self._trend.analyze(days=days, target=target)
        except Exception as exc:
            logger.warning(
                "Price calendar backfill aborted: analyze failed target=%s: %s", target, exc
            )
            return False, f"取数失败：{exc}"

        source = self._resolve_price_source(trend.data_sources, target)
        # ⚠ 约束 1：只认真实数据源。`mock` 是降级产物，写库即污染。
        if source not in _TRUSTED_PRICE_SOURCES:
            logger.warning(
                "Price calendar backfill skipped: target=%s source=%r not in %s",
                target,
                source,
                sorted(_TRUSTED_PRICE_SOURCES),
            )
            return False, f"数据源为 {source or '未知'}（非真实行情），已跳过回填以免写入假价格"

        bars = [(p.date, float(p.close)) for p in trend.points]
        if not bars:
            return False, "取数结果为空"

        written = await self._gold.upsert_many(target=target, bars=bars, source=source)
        logger.info(
            "Price calendar backfilled by backtest: target=%s written=%d source=%s",
            target,
            written,
            source,
        )
        return written > 0, f"已回填 {written} 条（{bars[0][0]} ~ {bars[-1][0]}，来源 {source}）"

    @staticmethod
    def _resolve_price_source(data_sources: dict | None, target: str) -> str:
        """委托 :mod:`app.services.price_source`（回测与复盘共用的唯一实现）。

        ⚠ 保留此方法仅供既有测试/调用方；**新代码请直接用**
        ``services.price_source.resolve_price_source``，避免同一逻辑两处维护。
        """
        return resolve_price_source(data_sources, target)

    async def _existing_calendar_span(self, target: str) -> tuple[date | None, date | None]:
        """返回价格日历在库中的最早 / 最晚日期（空表返回 ``(None, None)``）。"""
        bars = await self._gold.list_range(target, start=date(1990, 1, 1), end=date(2099, 12, 31))
        if not bars:
            return None, None
        return bars[0].price_date, bars[-1].price_date

    # ───────────────────── 内部辅助 ─────────────────────

    @staticmethod
    def _normalize_target(target: str | None) -> str:
        """兼容传入未知 target：回退 etf。"""
        valid = {"ny", "etf", "gram", "silver_ny", "silver_etf", "silver_gram"}
        return target if target in valid else "etf"

    async def _load_snapshots(self, target: str) -> list[DailySnapshot]:
        """加载**来源可信**的快照（按日期升序）。

        ⚠ V0.79.0 任务 #163：按 ``data_source`` 过滤。
        历史 24 条中 5 条的 ``close`` 经查证是 **mock 序列末值**（`_mock_us_history`
        以 base=4430 生成，多次运行后残留），而快照此前无来源标记 ⇒ 混进回测会让
        样本量与指标失真。

        ⚠ **NULL 一律排除，不当 live**：历史行全为 NULL（无时间戳记录当时的 mock
        末值，事后无法准确回填），猜测回填等于伪造溯源信息。
        """
        stmt = (
            select(DailySnapshot)
            .where(
                DailySnapshot.tech_index.is_not(None),
                DailySnapshot.data_source.in_(_TRUSTED_SNAPSHOT_SOURCES),
            )
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

        ⚠⚠ V0.79.0：**返回值无法区分「真零收益」与「完全无数据」**——两者都是 0.0。
        空价格日历时全表返回 0.0，与「价格恰好不动」表现完全一致，而下游
        ``compute_sharpe`` 对零方差返回 0.0、``judge_hit`` 对 NEUTRAL 判
        ``|0| <= band`` 全命中 ⇒ 静默产出「Sharpe 恒 0 + 命中率虚高」的假结果。
        ⇒ 判定可用性**必须看价格日历是否存在**，不可用 ``值 != 0`` 反推；
        可用天数由 ``_count_days_with_next_close()`` 独立统计。
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

    async def _count_days_with_next_close(
        self,
        target: str,
        snapshot_dates: list[date],
    ) -> int:
        """统计「真正能算出 T+1 涨跌幅」的快照天数（V0.79.0）。

        ⚠ **不能用 ``next_returns[d] != 0.0`` 反推**：真零收益与完全无数据
        在返回值里不可区分（都是 0.0），而这两种情形的可信度截然不同。
        正确判据是「该日期在价格日历里**是否存在后继交易日**」。
        """
        if not snapshot_dates:
            return 0
        start = snapshot_dates[0]
        end = snapshot_dates[-1] + timedelta(days=5)
        bars = await self._gold.list_range(target, start=start, end=end)
        if len(bars) < 2:
            return 0
        price_dates = sorted({b.price_date for b in bars})
        # 「有后继交易日」= 该日期不是价格序列的最后一个；用集合运算而非逐日
        # 扫后继（O(n²)），且天然与 ``_build_next_returns`` 的取数口径一致。
        with_successor = set(price_dates[:-1])
        return len(with_successor & set(snapshot_dates))

    def _evaluate_grid(
        self,
        snapshots: list[DailySnapshot],
        next_returns: dict[date, float],
        tech_w: float,
        macro_w: float,
        news_w: float,
        bullish_threshold: float,
        bearish_threshold: float,
        *,
        tech_dim_weights: dict[str, float] | None = None,
        macro_dim_weights: dict[str, float] | None = None,
    ) -> BacktestGridRow:
        """单组参数组合：合成 → 方向 → 命中 → 聚合。

        V0.79.0 Step G：增 ``tech_dim_weights`` / ``macro_dim_weights`` 两个可选参数：

        - **都未提供**（默认）→ 旧行为：用 ``snap.tech_index`` / ``snap.macro_index``
          扁平分（向后兼容）。
        - **提供了 ``tech_dim_weights``** → 改用 ``snap.tech_detail`` JSON
          里每维度的 ``score`` 字段 + 用户提供的权重 **重新计算**技术面分（0=None 时
          **整根跳过**，与 V0.78.0 Step D「数据不足 ≠ 中性」同型纪律）。
        - ``macro_dim_weights`` 同上（macro_detail 已有 5 因子分，落地早于 Step G）。

        返回行的 ``tech_dim_weights`` / ``macro_dim_weights`` 字段回填本次使用的
        权重（None 表示本组合未启用嵌套），便于 UI 在「最胜出组合」上展示。
        """
        sims: list[_SimDay] = []
        for snap in snapshots:
            # ── 技术面：嵌套权重覆盖时读 tech_detail ──
            if tech_dim_weights is not None:
                tech_score = _aggregate_from_detail(
                    snap.tech_detail, tech_dim_weights, "tech"
                )
                if tech_score is None:
                    # 该日无 tech_detail（NULL 或缺字段）→ 跳过这根快照
                    # （不是「中性 50」，是「压根没算出来」，按 V0.78.0 Step D 收口）
                    continue
            else:
                tech_score = float(snap.tech_index)
            # ── 宏观：嵌套权重覆盖时读 macro_detail ──
            if macro_dim_weights is not None:
                macro_score = _aggregate_from_detail(
                    snap.macro_detail, macro_dim_weights, "macro"
                )
                if macro_score is None:
                    continue
            else:
                macro_score = float(snap.macro_index)
            score = tech_score * tech_w + macro_score * macro_w + float(snap.news_index) * news_w
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
            tech_dim_weights=tech_dim_weights,
            macro_dim_weights=macro_dim_weights,
        )

    @staticmethod
    def _aggregate(rows: list[BacktestGridRow]) -> BacktestSummary:
        """聚合 N 行结果为 summary。

        ⚠ **不设 ``usable``** —— 聚合只见到 rows，无从判断收益数据是否真实存在。
        故继承 schema 的保守默认 ``False``，由 ``run()`` 依据 coverage 显式覆盖。
        这样「单独调用 ``_aggregate``」与「run 未执行 coverage」两条路径都不会
        宣称结果可用。
        """
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
