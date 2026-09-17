"""研判复盘服务（V0.66.0）：把「判断」和「结果」放到同一张表里对齐。

闭环设计::

    记录（分值 + 方向 + 依据）→ 对比（T+1/T+3/T+5 金价涨跌）
    → 统计（命中率 / 校准曲线 / 依据胜率）→ 反馈（下次打分时提示历史胜率）

关键口径
--------
- **基准价**：研判日（或之前最近一个交易日）的收盘价。窗口一律按**交易日**
  对齐（自动跳过周末），而非自然日。
- **命中判定**：
  - 看多（>55）：T+H 收盘 > 基准收盘 → 命中
  - 看空（<45）：T+H 收盘 < 基准收盘 → 命中
  - 中性：|涨跌幅| ≤ ``NEUTRAL_BAND_PCT``（默认 0.3%）→ 命中
- **补录排除**：含补录记录（``backfilled``）的日期默认不参与命中率统计，
  因为补录时已知道后续走势，计入会系统性抬高准确率（前视偏差）。
"""

from bisect import bisect_right
from datetime import date, timedelta

from app.models.review import (
    DEFAULT_REVIEW_TARGET,
    NEUTRAL_BAND_PCT,
    REVIEW_HORIZONS,
)
from app.repositories.news import NewsScoreRepository
from app.repositories.review import GoldPriceRepository
from app.schemas.common import DirectionSignal
from app.schemas.review import (
    BASIS_TAGS,
    BackfillOut,
    CalibrationBucketOut,
    DirectionStatsOut,
    HorizonStatsOut,
    JournalDayOut,
    JournalOut,
    JournalSlotOut,
    OutcomeOut,
    ReviewMetaOut,
    ReviewStatsOut,
    TagStatsOut,
)
from app.services.news import aggregate_slots, direction_of, parse_basis
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 复盘基准标的可选项（与趋势追踪口径一致）
REVIEW_TARGETS: tuple[tuple[str, str], ...] = (
    ("ny", "纽约金 COMEX"),
    ("etf", "黄金ETF 518880"),
    ("gram", "上海金克价"),
)
_TARGET_LABELS = dict(REVIEW_TARGETS)

# 中文星期
_WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

# 分值分箱（用于校准曲线：看「打多少分时实际上涨概率多大」）
_SCORE_BUCKETS: tuple[tuple[float, float], ...] = (
    (0, 20),
    (20, 40),
    (40, 60),
    (60, 80),
    (80, 100),
)

# 样本不足阈值：低于此值标注「仅供参考」
_MIN_SAMPLES = 20


def judge_hit(direction: DirectionSignal, change_pct: float) -> tuple[bool, str]:
    """按方向判定是否命中，返回 (是否命中, 可读说明)。

    Args:
        direction: 研判方向。
        change_pct: 基准日到目标日的涨跌幅 %。
    """
    if direction is DirectionSignal.BULLISH:
        hit = change_pct > 0
        return hit, f"看多，实际{'上涨' if hit else '下跌'} {change_pct:+.2f}%"
    if direction is DirectionSignal.BEARISH:
        hit = change_pct < 0
        return hit, f"看空，实际{'下跌' if hit else '上涨'} {change_pct:+.2f}%"
    hit = abs(change_pct) <= NEUTRAL_BAND_PCT
    if hit:
        return True, f"看平，实际几乎持平 {change_pct:+.2f}%"
    return False, f"看平，实际{'上涨' if change_pct > 0 else '下跌'} {change_pct:+.2f}%"


class ReviewService:
    """研判复盘：价格回填 + 按日归档 + 命中率/校准统计。"""

    def __init__(
        self,
        gold: GoldPriceRepository,
        news: NewsScoreRepository,
        trend=None,
    ) -> None:
        self._gold = gold
        self._news = news
        self._trend = trend

    # ---------- 元信息 ----------

    async def meta(self, target: str = DEFAULT_REVIEW_TARGET) -> ReviewMetaOut:
        """复盘页配置：可选标的、窗口、预置依据标签、价格积累情况。"""
        target = self._normalize_target(target)
        latest = await self._gold.latest(target)
        return ReviewMetaOut(
            target=target,
            targets=[{"key": k, "label": v} for k, v in REVIEW_TARGETS],
            horizons=list(REVIEW_HORIZONS),
            basis_tags=list(BASIS_TAGS),
            neutral_band_pct=NEUTRAL_BAND_PCT,
            price_days=await self._gold.count(target),
            latest_price_date=latest.price_date if latest else None,
            latest_price=float(latest.close) if latest else None,
        )

    # ---------- 价格回填 ----------

    async def backfill(self, days: int = 60, target: str = DEFAULT_REVIEW_TARGET) -> BackfillOut:
        """从行情接口回填历史日收盘价，建立/刷新价格日历。

        价格日历是对比基准，与评估值解耦：可随时重跑，幂等覆盖。
        """
        target = self._normalize_target(target)
        if self._trend is None:
            raise ValueError("趋势服务未注入，无法回填价格")

        trend = await self._trend.analyze(days=days, target=target)
        bars = [(p.date, float(p.close)) for p in trend.points]
        source = (trend.data_sources or {}).get(target, "") or "live"
        written = await self._gold.upsert_many(target=target, bars=bars, source=source)

        logger.info(
            "Review price backfilled: target=%s days=%d written=%d (%s ~ %s)",
            target,
            days,
            written,
            bars[0][0] if bars else "-",
            bars[-1][0] if bars else "-",
        )
        return BackfillOut(
            target=target,
            requested_days=days,
            written=written,
            price_days=await self._gold.count(target),
            start_date=bars[0][0] if bars else None,
            end_date=bars[-1][0] if bars else None,
            source=source,
        )

    # ---------- 内部：按日对齐 ----------

    def _normalize_horizon(self, horizon: int) -> int:
        return horizon if horizon in REVIEW_HORIZONS else REVIEW_HORIZONS[0]

    @staticmethod
    def _normalize_target(target: str | None) -> str:
        keys = {k for k, _ in REVIEW_TARGETS}
        return target if target in keys else DEFAULT_REVIEW_TARGET

    async def _build_days(
        self,
        days: int,
        target: str,
        horizons: tuple[int, ...] = REVIEW_HORIZONS,
    ) -> list[JournalDayOut]:
        """把打分记录与价格序列按交易日对齐，产出逐日复盘行。"""
        today = date.today()
        window_start = today - timedelta(days=max(days, 0))

        records = await self._news.list_between(window_start, today)
        if not records:
            return []

        # 价格序列：多取 10 个自然日缓冲，保证早期研判日也能找到基准价
        price_start = window_start - timedelta(days=10)
        prices = await self._gold.list_range(target, start=price_start)
        price_dates = [p.price_date for p in prices]
        price_close = {p.price_date: float(p.close) for p in prices}

        # 按日期分组
        grouped: dict[date, list] = {}
        for r in records:
            grouped.setdefault(r.score_date, []).append(r)

        items: list[JournalDayOut] = []
        for score_date in sorted(grouped, reverse=True):
            rows = grouped[score_date]
            effective, formula, weighted = aggregate_slots(rows)

            # 基准日：价格日历中不晚于研判日的最近一个交易日
            base_idx = bisect_right(price_dates, score_date) - 1
            base_date = price_dates[base_idx] if base_idx >= 0 else None
            base_close = price_close.get(base_date) if base_date else None

            outcomes = [
                self._outcome(prices, price_dates, base_idx, base_close, effective, h)
                for h in horizons
            ]

            tags: list[str] = []
            for r in rows:
                for tag in parse_basis(r.basis):
                    if tag not in tags:
                        tags.append(tag)

            items.append(
                JournalDayOut(
                    score_date=score_date,
                    weekday=_WEEKDAYS[score_date.weekday()],
                    evaluated=True,
                    effective_score=effective,
                    direction=direction_of(effective),
                    weighted=weighted,
                    formula=formula,
                    slots=[
                        JournalSlotOut(
                            slot=r.slot,
                            score=float(r.score),
                            direction=DirectionSignal(r.direction),
                            notes=r.notes or "",
                            basis=parse_basis(r.basis),
                            review_note=r.review_note or "",
                            scored_at=r.scored_at,
                            backfilled=bool(r.backfilled),
                        )
                        for r in rows
                    ],
                    basis=tags,
                    notes=rows[-1].notes or "",
                    review_note=next((r.review_note for r in reversed(rows) if r.review_note), ""),
                    backfilled=any(bool(r.backfilled) for r in rows),
                    price_date=base_date,
                    price_close=base_close,
                    outcomes=outcomes,
                )
            )
        return items

    @staticmethod
    def _outcome(
        prices: list,
        price_dates: list[date],
        base_idx: int,
        base_close: float | None,
        effective: float,
        horizon: int,
    ) -> OutcomeOut:
        """计算某个窗口的对比结果（基准日 → 之后第 horizon 个交易日）。"""
        target_idx = base_idx + horizon
        if base_close is None or base_idx < 0:
            return OutcomeOut(horizon=horizon, status="pending", label="缺基准价，无法对比")
        if target_idx >= len(price_dates):
            return OutcomeOut(horizon=horizon, status="pending", label=f"T+{horizon} 尚未到期")

        target_date = price_dates[target_idx]
        close = float(prices[target_idx].close)
        change_pct = round((close - base_close) / base_close * 100, 2)
        hit, label = judge_hit(direction_of(effective), change_pct)
        return OutcomeOut(
            horizon=horizon,
            date=target_date,
            close=close,
            change_pct=change_pct,
            hit=hit,
            status="hit" if hit else "miss",
            label=label,
        )

    # ---------- 研判日志 ----------

    async def journal(
        self,
        days: int = 30,
        target: str = DEFAULT_REVIEW_TARGET,
        horizon: int = 1,
    ) -> JournalOut:
        """按日期倒序返回研判归档 + 后续金价对比。"""
        target = self._normalize_target(target)
        horizon = self._normalize_horizon(horizon)
        items = await self._build_days(days, target, REVIEW_HORIZONS)

        pending = 0
        for day in items:
            primary = next((o for o in day.outcomes if o.horizon == horizon), None)
            if primary is None or primary.status == "pending":
                pending += 1

        latest = await self._gold.latest(target)
        return JournalOut(
            target=target,
            days=days,
            horizon=horizon,
            total=len(items),
            pending=pending,
            price_days=await self._gold.count(target),
            latest_price_date=latest.price_date if latest else None,
            items=items,
        )

    # ---------- 统计 ----------

    async def stats(
        self,
        days: int = 90,
        target: str = DEFAULT_REVIEW_TARGET,
        horizon: int = 1,
    ) -> ReviewStatsOut:
        """命中率 / 按方向 / 校准曲线 / 依据标签胜率。"""
        target = self._normalize_target(target)
        horizon = self._normalize_horizon(horizon)
        items = await self._build_days(days, target, REVIEW_HORIZONS)

        excluded = sum(1 for d in items if d.backfilled)
        usable = [d for d in items if not d.backfilled]

        def primary(day: JournalDayOut) -> OutcomeOut | None:
            return next((o for o in day.outcomes if o.horizon == horizon), None)

        resolved = [d for d in usable if (primary(d) and primary(d).status != "pending")]
        pending = len(usable) - len(resolved)

        hits = sum(1 for d in resolved if primary(d).hit)
        hit_rate = round(hits / len(resolved) * 100, 1) if resolved else None

        changes = [primary(d).change_pct for d in resolved if primary(d).change_pct is not None]
        scores = [d.effective_score for d in resolved]

        return ReviewStatsOut(
            target=target,
            days=days,
            horizon=horizon,
            total_days=len(items),
            evaluated=len(resolved),
            hits=hits,
            hit_rate=hit_rate,
            pending=pending,
            backfilled_excluded=excluded,
            avg_score=round(sum(scores) / len(scores), 1) if scores else None,
            avg_change=round(sum(changes) / len(changes), 2) if changes else None,
            by_direction=self._by_direction(resolved, primary),
            by_horizon=self._by_horizon(usable),
            calibration=self._calibration(resolved, primary),
            tags=self._by_tag(resolved, primary),
            sample_warning=len(resolved) < _MIN_SAMPLES,
            note=(
                f"样本 {len(resolved)} 天，低于 {_MIN_SAMPLES} 天时统计波动较大，仅供参考"
                if len(resolved) < _MIN_SAMPLES
                else f"样本 {len(resolved)} 天"
            ),
        )

    @staticmethod
    def _by_direction(resolved: list[JournalDayOut], primary) -> list[DirectionStatsOut]:
        labels = {
            DirectionSignal.BULLISH: "看多",
            DirectionSignal.BEARISH: "看空",
            DirectionSignal.NEUTRAL: "看平",
        }
        out: list[DirectionStatsOut] = []
        for direction in (
            DirectionSignal.BULLISH,
            DirectionSignal.BEARISH,
            DirectionSignal.NEUTRAL,
        ):
            group = [d for d in resolved if d.direction is direction]
            hits = sum(1 for d in group if primary(d).hit)
            out.append(
                DirectionStatsOut(
                    direction=direction,
                    label=labels[direction],
                    samples=len(group),
                    hits=hits,
                    hit_rate=round(hits / len(group) * 100, 1) if group else None,
                )
            )
        return out

    @staticmethod
    def _by_horizon(usable: list[JournalDayOut]) -> list[HorizonStatsOut]:
        out: list[HorizonStatsOut] = []
        for h in REVIEW_HORIZONS:
            pairs = [next((o for o in d.outcomes if o.horizon == h), None) for d in usable]
            done = [o for o in pairs if o is not None and o.status != "pending"]
            hits = sum(1 for o in done if o.hit)
            out.append(
                HorizonStatsOut(
                    horizon=h,
                    samples=len(done),
                    hits=hits,
                    hit_rate=round(hits / len(done) * 100, 1) if done else None,
                )
            )
        return out

    @staticmethod
    def _calibration(resolved: list[JournalDayOut], primary) -> list[CalibrationBucketOut]:
        """分值分箱校准：理想情况下「打 80 分」的上涨概率应显著高于「打 20 分」。"""
        buckets: list[CalibrationBucketOut] = []
        for lower, upper in _SCORE_BUCKETS:
            group = [
                d
                for d in resolved
                if lower <= d.effective_score < upper or (upper == 100 and d.effective_score == 100)
            ]
            if not group:
                buckets.append(
                    CalibrationBucketOut(key=f"{int(lower)}-{int(upper)}", lower=lower, upper=upper)
                )
                continue
            changes = [primary(d).change_pct for d in group if primary(d).change_pct is not None]
            ups = sum(1 for c in changes if c > 0)
            hits = sum(1 for d in group if primary(d).hit)
            buckets.append(
                CalibrationBucketOut(
                    key=f"{int(lower)}-{int(upper)}",
                    lower=lower,
                    upper=upper,
                    samples=len(group),
                    avg_score=round(sum(d.effective_score for d in group) / len(group), 1),
                    up_rate=round(ups / len(changes) * 100, 1) if changes else None,
                    hit_rate=round(hits / len(group) * 100, 1),
                )
            )
        return buckets

    @staticmethod
    def _by_tag(resolved: list[JournalDayOut], primary) -> list[TagStatsOut]:
        """依据标签胜率：同一标签在多天出现时合并统计。"""
        stats: dict[str, list[bool]] = {}
        for day in resolved:
            hit = bool(primary(day).hit)
            for tag in day.basis:
                stats.setdefault(tag, []).append(hit)
        out = [
            TagStatsOut(
                tag=tag,
                samples=len(flags),
                hits=sum(1 for f in flags if f),
                hit_rate=round(sum(1 for f in flags if f) / len(flags) * 100, 1),
            )
            for tag, flags in stats.items()
        ]
        out.sort(key=lambda t: (-t.samples, -(t.hit_rate or 0)))
        return out

    # ---------- 供打分页的「历史提示」 ----------

    async def hint_for_score(
        self, score: float, days: int = 90, target: str = DEFAULT_REVIEW_TARGET
    ) -> dict:
        """给定分值，返回该分值区间历史上的命中率与上涨概率（供打分页即时提示）。"""
        data = await self.stats(days=days, target=target)
        bucket = next(
            (
                b
                for b in data.calibration
                if b.lower <= score < b.upper or (b.upper == 100 and score == 100)
            ),
            None,
        )
        return {
            "bucket": bucket.key if bucket else "",
            "samples": bucket.samples if bucket else 0,
            "hit_rate": bucket.hit_rate if bucket else None,
            "up_rate": bucket.up_rate if bucket else None,
            "overall_hit_rate": data.hit_rate,
            "overall_samples": data.evaluated,
            "sample_warning": data.sample_warning,
        }
