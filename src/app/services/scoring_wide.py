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
    ScoringHorizonVerdict,
    ScoringSummaryBucket,
    ScoringSummaryOut,
    ScoringTagStat,
    ScoringVerdictOut,
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

        # ── V0.93.0：T+0 outcome（当日 close vs 上一交易日 close）──
        # 定位「当日尾盘快速反馈」：用户做今日打分后无需等次日即可知沪金当日 close
        # 是否印证研判方向。注意 T+0 含打分时刻已发生的盘内信息（数据泄露），
        # **不**用于评估「预测能力」，仅作快速 sanity check。
        # 上一交易日由 ``latest_before(target, date)`` 自动处理节假日/周末（取 < target_date 最近一条）。
        if gold_base is not None and gold_base.close > 0:
            gold_prev = await self._gold.latest_before(DEFAULT_REVIEW_TARGET, target_date)
            if gold_prev is not None and gold_prev.close > 0:
                change_pct = (gold_base.close - gold_prev.close) / gold_prev.close * 100
                news_dir = (
                    direction_of(row.news_index) if row.news_index is not None else None
                )
                if news_dir is not None:
                    hit, _label = judge_hit(news_dir, change_pct)
                    row.actual_change_pct_t0 = round(change_pct, 2)
                    row.hit_t0 = hit

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
        hit_filter: str = "all",
        horizon: str = "t1",
        user_id: int | None = None,
    ) -> ScoringSummaryOut:
        """按 day/week/month 分桶聚合。tag 可选（按 basis_tags JSON 包含判定过滤）。

        V0.92.1 hotfix：新增 ``hit_filter``（"yes" / "no" / "all"）按 ``horizon``
        指定的 ``hit_t{horizon}`` 字段在行级过滤行，再分桶。聚合后单日桶（group_by=day
        且桶内 1 行）的 ``hit`` 字段承载该行 hit 状态；week/month 桶 / pending 行 → None。
        """
        if group_by not in ("day", "week", "month"):
            raise ValueError(f"group_by must be day|week|month, got {group_by!r}")
        if hit_filter not in ("all", "yes", "no"):
            raise ValueError(f"hit_filter must be all|yes|no, got {hit_filter!r}")
        if horizon not in ("t0", "t1", "t3", "t5"):
            raise ValueError(f"horizon must be t0|t1|t3|t5, got {horizon!r}")
        hit_attr = f"hit_{horizon}"
        user_id = resolve_user_id(user_id)
        rows = await self._repo.list_in_range(start, end, user_id=user_id)
        if tag:
            rows = [r for r in rows if r.news_basis_tags and tag in json.loads(r.news_basis_tags)]
        # V0.92.1 hotfix：行级命中筛选（pending 行在"是"/"否"下被排除，"全部"下保留）
        if hit_filter in ("yes", "no"):
            want = hit_filter == "yes"
            rows = [r for r in rows if getattr(r, hit_attr) == want]

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
            hit_t0 = [r.hit_t0 for r in grp if r.hit_t0 is not None]  # V0.93.0
            hit_t1 = [r.hit_t1 for r in grp if r.hit_t1 is not None]
            hit_t3 = [r.hit_t3 for r in grp if r.hit_t3 is not None]
            hit_t5 = [r.hit_t5 for r in grp if r.hit_t5 is not None]
            up = sum(1 for r in grp if r.direction == "up")
            down = sum(1 for r in grp if r.direction == "down")
            side = sum(1 for r in grp if r.direction == "sideways")
            # V0.92.1 hotfix：单日桶（group_by=day 且桶内恰 1 行）→ 承载该行 hit 状态
            bucket_hit: bool | None = None
            if group_by == "day" and len(grp) == 1:
                bucket_hit = getattr(grp[0], hit_attr)
            buckets.append(
                ScoringSummaryBucket(
                    period=key,
                    days=len(grp),
                    trend_index_mean=round(statistics.fmean(trend_vals), 1) if trend_vals else None,
                    trend_index_median=round(statistics.median(trend_vals), 1) if trend_vals else None,
                    news_index_mean=round(statistics.fmean(news_vals), 1) if news_vals else None,
                    hit_rate_t0=round(sum(hit_t0) / len(hit_t0), 3) if hit_t0 else None,  # V0.93.0
                    hit_rate_t1=round(sum(hit_t1) / len(hit_t1), 3) if hit_t1 else None,
                    hit_rate_t3=round(sum(hit_t3) / len(hit_t3), 3) if hit_t3 else None,
                    hit_rate_t5=round(sum(hit_t5) / len(hit_t5), 3) if hit_t5 else None,
                    up_days=up,
                    down_days=down,
                    sideways_days=side,
                    hit=bucket_hit,
                )
            )
        return ScoringSummaryOut(
            from_date=start,
            to_date=end,
            group_by=group_by,
            tag=tag,
            hit_filter=hit_filter,
            horizon=horizon,
            buckets=buckets,
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
        """按 horizon 聚合命中率 + by_direction + by_month + calibration。

        V0.93.0：horizon 支持 ``t0`` —— 当日 close vs 上一交易日 close。
        """
        if horizon not in ("t0", "t1", "t3", "t5"):
            raise ValueError(f"horizon must be t0|t1|t3|t5, got {horizon!r}")
        # V0.93.0：t0 特例（horizon_n=0，"hit_t0"），其余保持原 1/3/5 映射
        hit_col = {0: "hit_t0", 1: "hit_t1", 3: "hit_t3", 5: "hit_t5"}[
            0 if horizon == "t0" else int(horizon[1:])
        ]
        user_id = resolve_user_id(user_id)
        rows = await self._repo.list_in_range(start, end, user_id=user_id)

        # 过滤出该 horizon 已就绪的行（hit 字段非 NULL）
        # V0.93.0：hit_col 已在上面映射好
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

        # by_month（复用 summary bucket）—— 按 horizon 选字段：t0/t1/t3/t5 互斥
        buckets_map: dict[str, list[ScoringDailyWide]] = defaultdict(list)
        for r in ready:
            key = self._bucket_key(r.date, "month")
            buckets_map[key].append(r)
        by_month: list[ScoringSummaryBucket] = []
        for key in sorted(buckets_map.keys()):
            grp = buckets_map[key]
            hits = [getattr(r, hit_col) for r in grp]
            rate = round(sum(hits) / len(hits), 3) if hits else None
            by_month.append(
                ScoringSummaryBucket(
                    period=key,
                    days=len(grp),
                    # V0.93.0：4 个 horizon 互斥，命中 rate 写入与 horizon 匹配字段
                    hit_rate_t0=rate if horizon == "t0" else None,
                    hit_rate_t1=rate if horizon == "t1" else None,
                    hit_rate_t3=rate if horizon == "t3" else None,
                    hit_rate_t5=rate if horizon == "t5" else None,
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

    # ──────────── 预测评估卡（V0.94.0） ────────────

    async def verdict(
        self,
        target_date: date,
        user_id: int | None = None,
    ) -> ScoringVerdictOut:
        """预测评估卡：取单日宽表行 → 推导方向 → 4 horizon 状态 → 一句话总结。

        V0.94.0 定位「打分后的预测判断」：用户完成 capture_today 后，
        本方法给出 4 个 horizon 的 ready/pending/missing 状态 + 一句话 summary，
        供前端 scoring 页顶部 verdict card 渲染。

        Returns:
            ``ScoringVerdictOut``。无打分行时 ``no_score=True``、summary 走「暂无打分」分支。
        """
        user_id = resolve_user_id(user_id)
        row = await self._repo.get_by_date(target_date, user_id=user_id)
        if row is None:
            return ScoringVerdictOut(
                target_date=target_date,
                news_index=None,
                prediction_direction=None,
                prediction_confidence=None,
                verdicts=[],
                basis_tags=[],
                summary=f"{target_date.isoformat()} 暂无打分数据（先做 capture_today）",
                no_score=True,
            )

        # 推导方向 + 置信度
        news_index = row.news_index
        prediction_direction: str | None = None
        prediction_confidence: float | None = None
        if news_index is not None:
            dir_sig = direction_of(news_index)
            prediction_direction = dir_sig.value  # "bullish" / "bearish" / "neutral"
            # 置信度：距 50 中位的绝对距离（0-50）→ 0-100 标度
            prediction_confidence = round(abs(news_index - 50) * 2, 1)

        # 4 个 horizon 状态
        verdicts: list[ScoringHorizonVerdict] = []
        # (horizon 字符串, hit 字段, change 字段, pending_until 计算函数)
        horizon_specs: list[tuple[str, str, str]] = [
            ("t0", "hit_t0", "actual_change_pct_t0"),
            ("t1", "hit_t1", "actual_change_pct_t1"),
            ("t3", "hit_t3", "actual_change_pct_t3"),
            ("t5", "hit_t5", "actual_change_pct_t5"),
        ]
        for horizon, hit_attr, change_attr in horizon_specs:
            hit = getattr(row, hit_attr)
            change_pct = getattr(row, change_attr)
            if hit is not None and change_pct is not None:
                status = "ready"
                pending_until = None
            elif hit is None and change_pct is None:
                status = "pending"
                # pending_until：等待到该日收盘后才有 outcome
                if horizon == "t0":
                    pending_until = target_date  # 当日 close 落库后即可用
                elif horizon == "t1":
                    pending_until = target_date + timedelta(days=1)
                elif horizon == "t3":
                    pending_until = target_date + timedelta(days=3)
                else:  # t5
                    pending_until = target_date + timedelta(days=5)
            else:
                # 字段不一致：1 个 NULL 1 个 非 NULL → 视为缺数据
                status = "missing"
                pending_until = None
            verdicts.append(
                ScoringHorizonVerdict(
                    horizon=horizon,
                    status=status,
                    actual_change_pct=change_pct,
                    hit=hit,
                    pending_until=pending_until,
                )
            )

        # 依据标签（去重）
        basis_tags: list[str] = []
        if row.news_basis_tags:
            try:
                basis_tags = json.loads(row.news_basis_tags)
            except (json.JSONDecodeError, TypeError):
                basis_tags = []

        # 一句话总结
        summary = self._build_verdict_summary(
            target_date, news_index, prediction_direction, prediction_confidence, verdicts
        )

        return ScoringVerdictOut(
            target_date=target_date,
            news_index=news_index,
            prediction_direction=prediction_direction,
            prediction_confidence=prediction_confidence,
            verdicts=verdicts,
            basis_tags=basis_tags,
            summary=summary,
            no_score=False,
        )

    @staticmethod
    def _build_verdict_summary(
        target_date: date,
        news_index: float | None,
        direction: str | None,
        confidence: float | None,
        verdicts: list[ScoringHorizonVerdict],
    ) -> str:
        """构造 verdict 卡的一句话总结（前端可直接展示，不做 i18n 转换）。

        文案结构：「{date} · 你{direction_cn}（{confidence}）·
        {horizon_hit_miss_summary}。」
        """
        date_str = target_date.isoformat()
        if direction is None or news_index is None:
            return f"{date_str} · 暂无研判（news_index=NULL）"

        direction_cn = {
            "bullish": "看多",
            "bearish": "看空",
            "neutral": "看平",
        }.get(direction, direction)
        conf_str = f"{confidence:.0f}" if confidence is not None else "—"
        head = f"{date_str} · 你{direction_cn}（{conf_str} 分）"

        # 4 horizon 状态串联
        parts: list[str] = []
        for v in verdicts:
            if v.status == "ready":
                if v.hit is True:
                    parts.append(f"{v.horizon.upper()} 命中（{v.actual_change_pct:+.2f}%）")
                else:
                    parts.append(f"{v.horizon.upper()} 未命中（{v.actual_change_pct:+.2f}%）")
            elif v.status == "pending":
                parts.append(f"{v.horizon.upper()} 等待中")
            else:
                parts.append(f"{v.horizon.upper()} 缺数据")
        return f"{head} · {' / '.join(parts)}。"
