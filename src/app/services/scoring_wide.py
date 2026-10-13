"""打分数据宽表服务（V0.92.0 · 历史打分数据汇总）

ETL 入口：``rebuild(target_date)`` 把 3 张事实表
（``daily_snapshots`` / ``news_scores`` / ``gold_price_daily``）合并为 1 行
``scoring_daily_wide``，由 ``DailySnapshotService.capture_today`` 与
``NewsScoreService.save_today`` 写时 hook 触发。

聚合查询：4 个端点对应 4 个方法（``summary`` / ``by-date`` / ``hit-stats`` / ``by-tag``），
均从宽表读 O(天数)，避免 4-6 表 JOIN + JSON parse。

⚠ **纪律**
- V0.78.0 Step D：所有数值列允许 NULL（**绝不**用 50 / 0 兜底）
- V0.79.0 任务 #162：宽表写失败**不**回滚源表 —— 宽表是"读优化副本"
- V0.80.0 #159：所有查询默认按当前用户过滤
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import date, timedelta

from app.models.review import DEFAULT_REVIEW_TARGET, REVIEW_HORIZONS
from app.models.scoring_wide import ScoringDailyWide
from app.repositories.news import NewsScoreRepository
from app.repositories.review import GoldPriceRepository
from app.repositories.snapshot import SnapshotRepository
from app.schemas.common import DirectionSignal
from app.schemas.review import BASIS_TAGS
from app.schemas.scoring_wide import (
    ScoringByTagOut,
    ScoringHitCalibrationBucket,
    ScoringHitDirectionStat,
    ScoringHitStatsOut,
    ScoringSummaryBucket,
    ScoringSummaryOut,
    ScoringTagStat,
    ScoringWideListOut,
    ScoringWideOut,
)
from app.services.news import aggregate_slots, direction_of, parse_basis
from app.services.review import judge_hit
from app.utils.logger import get_logger
from app.utils.user_scope import resolve_user_id

logger = get_logger(__name__)


class ScoringWideService:
    """打分数据宽表服务：ETL + 4 聚合查询。"""

    def __init__(
        self,
        repo,  # ScoringWideRepository
        snapshot_repo: SnapshotRepository,
        news_repo: NewsScoreRepository,
        gold_repo: GoldPriceRepository,
    ) -> None:
        self._repo = repo
        self._snapshot = snapshot_repo
        self._news = news_repo
        self._gold = gold_repo

    # ──────────── ETL: build_row + rebuild ────────────

    async def rebuild(self, target_date: date, user_id: int | None = None) -> ScoringWideOut | None:
        """重算单日宽表行（幂等）。写时 hook 调用 + 离线 CLI 回填。

        Returns:
            写入的 ``ScoringWideOut``；若当日无任何源数据（无 snapshot / 无 news / 无 gold），
            返回 ``None``（不写空行）。

        Raises:
            不抛异常（V0.79.0 任务 #162 教训：宽表写失败**不**影响源表）。
            失败时 log.warning 后返回 ``None``。
        """
        user_id = resolve_user_id(user_id)
        try:
            row = await self._build_row(target_date, user_id)
            if row is None:
                return None
            await self._repo.upsert(row)
            logger.info(
                "scoring_daily_wide rebuilt: date=%s trend=%s news=%s/%d",
                row.date,
                row.trend_index,
                row.news_index,
                row.news_slot_count or 0,
            )
            return ScoringWideOut.model_validate(row)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "scoring_daily_wide rebuild failed: date=%s err=%s",
                target_date,
                exc,
            )
            return None

    async def _build_row(self, target_date: date, user_id: int) -> ScoringDailyWide | None:
        """把 3 张事实表合并成 1 行 ScoringDailyWide（不落库）。"""
        # ── 1. daily_snapshots ──
        snap = await self._snapshot.get_by_date(target_date)
        # ── 2. news_scores（当日所有 slot）──
        news_records = await self._news.list_by_date(target_date, user_id=user_id)
        # ── 3. gold_price_daily：基准日 + T+1/T+3/T+5 ──
        gold_base = await self._gold.get_on(DEFAULT_REVIEW_TARGET, target_date)

        # 3 个源都缺 → 不写空行
        if snap is None and not news_records and gold_base is None:
            return None

        row = ScoringDailyWide(date=target_date, user_id=user_id)
        if snap is not None:
            row.snapshot_id = snap.id
            row.tech_index = snap.tech_index
            row.macro_index = snap.macro_index
            row.news_index = snap.news_index
            row.trend_index = snap.trend_index
            row.index_level = snap.index_level
            row.close = snap.close
            row.change_pct = snap.change_pct
            row.direction = snap.direction
            row.data_source = snap.data_source

        # ── 消息面聚合 ──
        if news_records:
            effective, _formula, _weighted = aggregate_slots(news_records)
            row.news_index = effective  # 优先用 ETL 实时聚合（覆盖 snapshot 的缓存值）
            row.news_slot_count = len(news_records)
            row.news_backfilled_count = sum(int(r.backfilled) for r in news_records)
            # basis_tags 跨 slot 去重，保留顺序（slot3 出现顺序优先倒序排）
            seen: set[str] = set()
            tags: list[str] = []
            for r in reversed(news_records):
                for tag in parse_basis(r.basis):
                    if tag not in seen:
                        seen.add(tag)
                        tags.append(tag)
            if tags:
                # 只保留在 BASIS_TAGS 白名单内的标签（防 schema 漂移脏数据）
                tags = [t for t in tags if t in BASIS_TAGS]
            row.news_basis_tags = json.dumps(tags, ensure_ascii=False) if tags else None
            row.direction = direction_of(effective).value  # 覆盖 snap.direction
        else:
            row.news_slot_count = 0
            row.news_backfilled_count = 0
            row.news_basis_tags = None

        # ── outcomes：T+1/T+3/T+5 ──
        if gold_base is not None and gold_base.close > 0:
            # 取 target_date 之后最多 10 个交易日的 gold_price_daily
            # （含节假日补位，10 天覆盖 T+5 99% 情形）
            future_bars = await self._gold.list_range(
                DEFAULT_REVIEW_TARGET,
                start=target_date + timedelta(days=1),
                end=target_date + timedelta(days=10),
            )
            # 计算当前已知的 outcome_pending_until
            news_dir = direction_of(row.news_index) if row.news_index is not None else None
            for horizon in REVIEW_HORIZONS:  # (1, 3, 5)
                if len(future_bars) >= horizon:
                    future = future_bars[horizon - 1]
                    change_pct = (future.close - gold_base.close) / gold_base.close * 100
                    self._set_outcome(row, horizon, change_pct, news_dir, future.price_date)
            # pending_until：5 个交易日的最末日（若 T+5 已就绪则为 None）
            if len(future_bars) >= 5:
                row.outcome_pending_until = None
            else:
                # 还未到 T+5 → pending 到 future_bars 最后一日
                row.outcome_pending_until = future_bars[-1].price_date if future_bars else None

        return row

    @staticmethod
    def _set_outcome(
        row: ScoringDailyWide,
        horizon: int,
        change_pct: float,
        news_dir: DirectionSignal | None,
        future_date: date,
    ) -> None:
        """写入 T+horizon 的 actual_change_pct + hit 判定。"""
        if news_dir is None:
            return  # 无消息面方向 → outcomes 留 NULL（**不**兜底）
        hit, _label = judge_hit(news_dir, change_pct)
        if horizon == 1:
            row.actual_change_pct_t1 = round(change_pct, 2)
            row.hit_t1 = hit
        elif horizon == 3:
            row.actual_change_pct_t3 = round(change_pct, 2)
            row.hit_t3 = hit
        elif horizon == 5:
            row.actual_change_pct_t5 = round(change_pct, 2)
            row.hit_t5 = hit

    # ──────────── 读端点：by-date ────────────

    async def get_by_date(
        self, target_date: date, user_id: int | None = None
    ) -> ScoringWideOut | None:
        """取单日宽表行。"""
        user_id = resolve_user_id(user_id)
        row = await self._repo.get_by_date(target_date, user_id=user_id)
        return ScoringWideOut.model_validate(row) if row else None

    async def list_in_range(
        self, start: date, end: date, user_id: int | None = None
    ) -> ScoringWideListOut:
        """取区间内宽表行（升序）。"""
        user_id = resolve_user_id(user_id)
        rows = await self._repo.list_in_range(start, end, user_id=user_id)
        return ScoringWideListOut(
            total=len(rows),
            rows=[ScoringWideOut.model_validate(r) for r in rows],
        )

    # ──────────── 读端点：summary 聚合 ────────────

    async def summary(
        self,
        start: date,
        end: date,
        group_by: str = "month",
        tag: str | None = None,
        user_id: int | None = None,
    ) -> ScoringSummaryOut:
        """按 day/week/month 分桶聚合。tag 可选（按 basis_tags JSON 包含判定过滤）。"""
        if group_by not in ("day", "week", "month"):
            raise ValueError(f"group_by must be day|week|month, got {group_by!r}")
        user_id = resolve_user_id(user_id)
        rows = await self._repo.list_in_range(start, end, user_id=user_id)
        if tag:
            rows = [r for r in rows if r.news_basis_tags and tag in json.loads(r.news_basis_tags)]

        # 按桶分组
        buckets_map: dict[str, list[ScoringDailyWide]] = defaultdict(list)
        for r in rows:
            key = self._bucket_key(r.date, group_by)
            buckets_map[key].append(r)

        buckets: list[ScoringSummaryBucket] = []
        for key in sorted(buckets_map.keys()):
            grp = buckets_map[key]
            trend_vals = [r.trend_index for r in grp if r.trend_index is not None]
            news_vals = [r.news_index for r in grp if r.news_index is not None]
            hit_t1 = [r.hit_t1 for r in grp if r.hit_t1 is not None]
            hit_t3 = [r.hit_t3 for r in grp if r.hit_t3 is not None]
            hit_t5 = [r.hit_t5 for r in grp if r.hit_t5 is not None]
            up = sum(1 for r in grp if r.direction == "up")
            down = sum(1 for r in grp if r.direction == "down")
            side = sum(1 for r in grp if r.direction == "sideways")
            buckets.append(
                ScoringSummaryBucket(
                    period=key,
                    days=len(grp),
                    trend_index_mean=round(statistics.fmean(trend_vals), 1) if trend_vals else None,
                    trend_index_median=round(statistics.median(trend_vals), 1) if trend_vals else None,
                    news_index_mean=round(statistics.fmean(news_vals), 1) if news_vals else None,
                    hit_rate_t1=round(sum(hit_t1) / len(hit_t1), 3) if hit_t1 else None,
                    hit_rate_t3=round(sum(hit_t3) / len(hit_t3), 3) if hit_t3 else None,
                    hit_rate_t5=round(sum(hit_t5) / len(hit_t5), 3) if hit_t5 else None,
                    up_days=up,
                    down_days=down,
                    sideways_days=side,
                )
            )
        return ScoringSummaryOut(
            from_date=start, to_date=end, group_by=group_by, tag=tag, buckets=buckets
        )

    @staticmethod
    def _bucket_key(d: date, group_by: str) -> str:
        if group_by == "day":
            return d.isoformat()
        if group_by == "month":
            return f"{d.year:04d}-{d.month:02d}"
        # week: ISO week "2026-W42"
        iso = d.isocalendar()
        return f"{iso[0]:04d}-W{iso[1]:02d}"

    # ──────────── 读端点：hit-stats ────────────

    async def hit_stats(
        self,
        start: date,
        end: date,
        horizon: str = "t5",
        user_id: int | None = None,
    ) -> ScoringHitStatsOut:
        """按 horizon 聚合命中率 + by_direction + by_month + calibration。"""
        if horizon not in ("t1", "t3", "t5"):
            raise ValueError(f"horizon must be t1|t3|t5, got {horizon!r}")
        horizon_n = int(horizon[1:])
        user_id = resolve_user_id(user_id)
        rows = await self._repo.list_in_range(start, end, user_id=user_id)

        # 过滤出该 horizon 已就绪的行（hit 字段非 NULL）
        hit_col = {1: "hit_t1", 3: "hit_t3", 5: "hit_t5"}[horizon_n]
        ready = [r for r in rows if getattr(r, hit_col) is not None]

        # 整体命中率
        total = len(ready)
        hit_count = sum(1 for r in ready if getattr(r, hit_col))
        overall = round(hit_count / total, 3) if total else None

        # by_direction（按 news_index 方向分类）
        by_dir_map: dict[str, list[bool]] = defaultdict(list)
        for r in ready:
            if r.news_index is None:
                continue
            d = direction_of(r.news_index)
            by_dir_map[d.value].append(getattr(r, hit_col))
        by_direction: list[ScoringHitDirectionStat] = [
            ScoringHitDirectionStat(
                direction=d,
                hit_count=sum(v),
                total=len(v),
                hit_rate=round(sum(v) / len(v), 3) if v else 0.0,
            )
            for d, v in sorted(by_dir_map.items())
        ]

        # by_month（复用 summary bucket）
        buckets_map: dict[str, list[ScoringDailyWide]] = defaultdict(list)
        for r in ready:
            key = self._bucket_key(r.date, "month")
            buckets_map[key].append(r)
        by_month: list[ScoringSummaryBucket] = []
        for key in sorted(buckets_map.keys()):
            grp = buckets_map[key]
            hits = [getattr(r, hit_col) for r in grp]
            by_month.append(
                ScoringSummaryBucket(
                    period=key,
                    days=len(grp),
                    hit_rate_t1=None,
                    hit_rate_t3=None,
                    hit_rate_t5=round(sum(hits) / len(hits), 3) if hits else None,
                )
            )

        # calibration（按分值分箱：0-20, 20-40, 40-60, 60-80, 80-100）
        cal_buckets: list[tuple[int, int, str]] = [
            (0, 20, "0-20"),
            (20, 40, "20-40"),
            (40, 60, "40-60"),
            (60, 80, "60-80"),
            (80, 101, "80-100"),
        ]
        cal_map: dict[str, list[bool]] = defaultdict(list)
        for r in ready:
            if r.news_index is None:
                continue
            for lo, hi, label in cal_buckets:
                if lo <= r.news_index < hi:
                    cal_map[label].append(getattr(r, hit_col))
                    break
        calibration: list[ScoringHitCalibrationBucket] = [
            ScoringHitCalibrationBucket(
                score_bucket=label,
                hit_count=sum(v),
                total=len(v),
                hit_rate=round(sum(v) / len(v), 3) if v else 0.0,
            )
            for _, _, label in cal_buckets
            if (v := cal_map.get(label, []))
        ]

        return ScoringHitStatsOut(
            horizon=horizon,
            sample_size=total,
            overall_hit_rate=overall,
            by_direction=by_direction,
            by_month=by_month,
            calibration=calibration,
        )

    # ──────────── 读端点：by-tag ────────────

    async def by_tag(
        self,
        start: date,
        end: date,
        user_id: int | None = None,
    ) -> ScoringByTagOut:
        """按 basis_tags 维度统计出现次数与各 horizon 命中率。"""
        user_id = resolve_user_id(user_id)
        rows = await self._repo.list_in_range(start, end, user_id=user_id)
        # tag → {count, hits_t1, hits_t3, hits_t5}
        tag_stats: dict[str, dict[str, int]] = defaultdict(
            lambda: {"count": 0, "h1": 0, "t1": 0, "h3": 0, "t3": 0, "h5": 0, "t5": 0}
        )
        for r in rows:
            if not r.news_basis_tags:
                continue
            try:
                tags = json.loads(r.news_basis_tags)
            except (json.JSONDecodeError, TypeError):
                continue
            for tag in tags:
                if tag not in BASIS_TAGS:
                    continue
                s = tag_stats[tag]
                s["count"] += 1
                for h, key in ((1, "t1"), (3, "t3"), (5, "t5")):
                    hit_attr = f"hit_{key}"
                    hit_val = getattr(r, hit_attr)
                    if hit_val is not None:
                        s[key] += 1
                        if hit_val:
                            s[f"h{key[1]}"] += 1
        tags_out: list[ScoringTagStat] = []
        for tag, s in sorted(tag_stats.items(), key=lambda x: -x[1]["count"]):
            tags_out.append(
                ScoringTagStat(
                    tag=tag,
                    count=s["count"],
                    hit_rate_t1=round(s["h1"] / s["t1"], 3) if s["t1"] else None,
                    hit_rate_t3=round(s["h3"] / s["t3"], 3) if s["t3"] else None,
                    hit_rate_t5=round(s["h5"] / s["t5"], 3) if s["t5"] else None,
                )
            )
        return ScoringByTagOut(from_date=start, to_date=end, tags=tags_out)
