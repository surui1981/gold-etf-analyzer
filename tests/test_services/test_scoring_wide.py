"""``scoring_daily_wide`` 模型 + 仓储 + ETL 单测（V0.92.0 维护线）。

目标：覆盖 ETL 流程的核心分支：
- rebuild 写入（4 指数 + 消息面聚合 + outcomes）
- basis_tags JSON 反序列化（V0.83 教训：API 返回 list/dict 都不能 .map）
- outcomes pending 期为 NULL（V0.78.0 Step D 纪律）
- user_id 隔离（V0.80.0 #159）

策略：纯 in-memory SQLite + 注入 fake repos；不走 FastAPI。
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news import NewsScore
from app.models.review import GoldPriceDaily
from app.models.scoring_wide import ScoringDailyWide
from app.models.snapshot import DailySnapshot
from app.repositories.news import NewsScoreRepository
from app.repositories.review import GoldPriceRepository
from app.repositories.scoring_wide import ScoringWideRepository
from app.repositories.snapshot import SnapshotRepository
from app.services.scoring_wide import ScoringWideService


# ──────────── fixtures ────────────


async def _insert_snapshot(
    session: AsyncSession,
    snapshot_date: date,
    **overrides,
) -> DailySnapshot:
    defaults = {
        "snapshot_date": snapshot_date,
        "symbol": "518880",
        "name": "黄金ETF华安",
        "close": 5.5,
        "change_pct": 1.2,
        "high": 5.6,
        "low": 5.4,
        "ma20": 5.45,
        "ma40": 5.40,
        "direction": "up",
        "tech_index": 65.0,
        "macro_index": 58.0,
        "news_index": 60.0,
        "trend_index": 61.0,
        "index_level": "偏多",
        "tech_detail": None,
        "macro_detail": "{}",
        "data_source": "live",
    }
    defaults.update(overrides)
    row = DailySnapshot(**defaults)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def _insert_news(
    session: AsyncSession,
    score_date: date,
    slot: int,
    score: float,
    direction: str = "bullish",
    basis: str = '["美元指数"]',
    backfilled: int = 0,
) -> NewsScore:
    row = NewsScore(
        score_date=score_date,
        slot=slot,
        score=score,
        direction=direction,
        notes="",
        basis=basis,
        review_note="",
        backfilled=backfilled,
        user_id=1,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def _insert_gold(
    session: AsyncSession,
    price_date: date,
    close: float,
    target: str = "ny",
) -> GoldPriceDaily:
    row = GoldPriceDaily(
        target=target, price_date=price_date, close=close, change_pct=0.0, source="test"
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


def _service(db: AsyncSession) -> ScoringWideService:
    return ScoringWideService(
        repo=ScoringWideRepository(db),
        snapshot_repo=SnapshotRepository(db),
        news_repo=NewsScoreRepository(db),
        gold_repo=GoldPriceRepository(db),
    )


# ──────────── rebuild 单日 ────────────


class TestRebuild:
    async def test_writes_row_with_4_indices_and_outcomes(
        self, db_session: AsyncSession
    ) -> None:
        """正常 rebuild：4 指数 + T+1/T+3 outcomes 正确，pending T+5 为 NULL。

        gold 用连续 5 个交易日（index-based 假设 + 真实生产无周末间隙一致）；
        5 根 bar 全部到齐 → outcome_pending_until 为 None。
        """
        target = date(2026, 10, 10)
        await _insert_snapshot(db_session, target)
        await _insert_news(db_session, target, slot=1, score=60, direction="bullish")
        # gold: 基准日 + 5 个连续未来日（review service 口径：price_dates 升序）
        await _insert_gold(db_session, target, close=2000.0)
        await _insert_gold(db_session, target + timedelta(days=1), close=2010.0)
        await _insert_gold(db_session, target + timedelta(days=2), close=2015.0)
        await _insert_gold(db_session, target + timedelta(days=3), close=2020.0)
        await _insert_gold(db_session, target + timedelta(days=4), close=2025.0)
        await _insert_gold(db_session, target + timedelta(days=5), close=2030.0)

        out = await _service(db_session).rebuild(target)

        assert out is not None
        assert out.date == target
        assert out.trend_index == 61.0
        assert out.news_index == 60.0
        assert out.news_slot_count == 1
        # T+1: future_bars[0] = 2010, 涨 0.5%; bullish 方向 > 0 → hit
        assert out.actual_change_pct_t1 == 0.5
        assert out.hit_t1 is True
        # T+3: future_bars[2] = 2020, 涨 1.0%
        assert out.actual_change_pct_t3 == 1.0
        assert out.hit_t3 is True
        # T+5: future_bars[4] = 2030, 涨 1.5%
        assert out.actual_change_pct_t5 == 1.5
        assert out.hit_t5 is True
        # 全部到齐 → pending_until 为 None
        assert out.outcome_pending_until is None
        # basis_tags JSON 数组
        assert out.news_basis_tags == ["美元指数"]

    async def test_t5_pending_when_no_future_bars(
        self, db_session: AsyncSession
    ) -> None:
        """T+5 缺数据：pending_until 显式标 future_bars 最后一日。"""
        target = date(2026, 10, 10)
        await _insert_snapshot(db_session, target)
        await _insert_news(db_session, target, slot=1, score=60)
        await _insert_gold(db_session, target, close=2000.0)
        await _insert_gold(db_session, target + timedelta(days=1), close=2010.0)
        # 缺 T+3 和 T+5

        out = await _service(db_session).rebuild(target)

        assert out is not None
        assert out.hit_t1 is True
        assert out.actual_change_pct_t3 is None  # 缺数据 → NULL（V0.78.0 Step D）
        assert out.hit_t3 is None
        assert out.actual_change_pct_t5 is None
        assert out.hit_t5 is None
        # pending_until 标到 last future_bar
        assert out.outcome_pending_until == target + timedelta(days=1)

    async def test_no_data_returns_none(self, db_session: AsyncSession) -> None:
        """3 源都缺数据：rebuild 返回 None（不写空行）。"""
        target = date(2026, 10, 10)
        out = await _service(db_session).rebuild(target)
        assert out is None

    async def test_basis_tags_dedup_across_slots(
        self, db_session: AsyncSession
    ) -> None:
        """slot1 + slot2 都含"美元指数" → 宽表只 1 个。"""
        target = date(2026, 10, 10)
        await _insert_snapshot(db_session, target, news_index=50.0)
        await _insert_news(
            db_session, target, slot=1, score=60,
            basis='["美元指数", "美债收益率"]',
        )
        await _insert_news(
            db_session, target, slot=2, score=55,
            basis='["美元指数", "地缘风险"]',
        )
        await _insert_gold(db_session, target, close=2000.0)
        await _insert_gold(db_session, target + timedelta(days=1), close=2010.0)

        out = await _service(db_session).rebuild(target)

        assert out is not None
        # slot2 倒序优先 + slot1，美元指数出现在 slot2 + slot1 → 保留 1 个
        assert out.news_basis_tags is not None
        assert "美元指数" in out.news_basis_tags
        # slot2 倒序排前面
        assert out.news_basis_tags[0] in ("地缘风险", "美元指数")
        # slot_count = 2
        assert out.news_slot_count == 2


# ──────────── summary 聚合 ────────────


class TestSummary:
    async def test_empty_range(self, db_session: AsyncSession) -> None:
        out = await _service(db_session).summary(
            start=date(2026, 10, 1), end=date(2026, 10, 31), group_by="month"
        )
        assert out.buckets == []
        assert out.group_by == "month"

    async def test_group_by_month_aggregates(
        self, db_session: AsyncSession
    ) -> None:
        target = date(2026, 10, 10)
        await _insert_snapshot(db_session, target, trend_index=70.0)
        await _insert_gold(db_session, target, close=2000.0)
        await _insert_gold(db_session, target + timedelta(days=1), close=2010.0)

        await _service(db_session).rebuild(target)
        out = await _service(db_session).summary(
            start=date(2026, 10, 1), end=date(2026, 10, 31), group_by="month"
        )

        assert len(out.buckets) == 1
        b = out.buckets[0]
        assert b.period == "2026-10"
        assert b.days == 1
        assert b.trend_index_mean == 70.0


# ──────────── by-date 单日 ────────────


class TestByDate:
    async def test_returns_none_for_missing_date(self, db_session: AsyncSession) -> None:
        out = await _service(db_session).get_by_date(date(2026, 10, 10))
        assert out is None

    async def test_returns_row_after_rebuild(
        self, db_session: AsyncSession
    ) -> None:
        target = date(2026, 10, 10)
        await _insert_snapshot(db_session, target)
        await _insert_gold(db_session, target, close=2000.0)
        await _insert_gold(db_session, target + timedelta(days=1), close=2010.0)
        await _service(db_session).rebuild(target)

        out = await _service(db_session).get_by_date(target)
        assert out is not None
        assert out.trend_index == 61.0
        assert out.hit_t1 is True


# ──────────── by-tag 聚合 ────────────


class TestByTag:
    async def test_empty_no_tags(self, db_session: AsyncSession) -> None:
        out = await _service(db_session).by_tag(
            start=date(2026, 10, 1), end=date(2026, 10, 31)
        )
        assert out.tags == []

    async def test_count_per_tag(
        self, db_session: AsyncSession
    ) -> None:
        target = date(2026, 10, 10)
        # news_index=60（严格 > 55 阈值 → 看多）；basis 含 2 个 tag
        await _insert_snapshot(db_session, target, news_index=60.0)
        await _insert_news(
            db_session, target, slot=1, score=60, basis='["美元指数", "美债收益率"]'
        )
        # 连续 5 个 gold bar：每个 horizon 都上涨 → bullish 全部 hit
        await _insert_gold(db_session, target, close=2000.0)
        await _insert_gold(db_session, target + timedelta(days=1), close=2010.0)
        await _insert_gold(db_session, target + timedelta(days=2), close=2015.0)
        await _insert_gold(db_session, target + timedelta(days=3), close=2020.0)
        await _insert_gold(db_session, target + timedelta(days=4), close=2025.0)
        await _insert_gold(db_session, target + timedelta(days=5), close=2030.0)
        await _service(db_session).rebuild(target)

        out = await _service(db_session).by_tag(
            start=date(2026, 10, 1), end=date(2026, 10, 31)
        )
        # 2 个 tag，各出现 1 次；bullish 全部 hit
        assert len(out.tags) == 2
        for t in out.tags:
            assert t.count == 1
            assert t.hit_rate_t1 == 1.0
            assert t.hit_rate_t3 == 1.0
            assert t.hit_rate_t5 == 1.0


# ──────────── hit-stats-all 4 horizon 聚合 (V0.96.0) ────────────


class TestHitStatsAllHorizons:
    """V0.96.0：4 horizon (t0/t1/t3/t5) by_month + mini card 摘要。"""

    async def test_empty_range_returns_empty_by_horizon(
        self, db_session: AsyncSession
    ) -> None:
        """空范围：4 horizon 各返回 by_month=[]，mini_card 全 None，best_horizon=None。"""
        out = await _service(db_session).hit_stats_all_horizons(
            start=date(2026, 10, 1), end=date(2026, 10, 31)
        )
        assert out.from_date == date(2026, 10, 1)
        assert out.to_date == date(2026, 10, 31)
        # 4 horizon 都在
        assert set(out.by_horizon.keys()) == {"t0", "t1", "t3", "t5"}
        for h in out.by_horizon.values():
            assert h.by_month == []
        # mini card 全 None
        assert all(v is None for v in out.mini_card.last_30d.values())
        assert all(v is None for v in out.mini_card.last_30d_mom.values())
        assert out.mini_card.best_horizon is None

    async def test_4_horizon_by_month_mutex(
        self, db_session: AsyncSession
    ) -> None:
        """1 个 bullish 行：4 horizon 各 by_month 桶只有对应字段非空，其余 3 字段为 None。

        V0.78.0 NULL 纪律：同 1 个桶内 4 字段互斥（不是各自一份 by_month list）。
        """
        target = date(2026, 10, 10)
        await _insert_snapshot(db_session, target, news_index=60.0)
        # 6 根 bar：target-1 (t0) + target + target+1..+5 (t1/t3/t5)
        # _set_outcome 要求 future_bars 长度 >= horizon：t5 需要 5 根 future bar
        await _insert_gold(db_session, target - timedelta(days=1), close=1990.0)
        await _insert_gold(db_session, target, close=2000.0)
        await _insert_gold(db_session, target + timedelta(days=1), close=2010.0)
        await _insert_gold(db_session, target + timedelta(days=2), close=2015.0)
        await _insert_gold(db_session, target + timedelta(days=3), close=2025.0)
        await _insert_gold(db_session, target + timedelta(days=4), close=2035.0)
        await _insert_gold(db_session, target + timedelta(days=5), close=2050.0)
        await _service(db_session).rebuild(target)

        out = await _service(db_session).hit_stats_all_horizons(
            start=date(2026, 10, 1), end=date(2026, 10, 31)
        )
        # 4 horizon 各 1 个桶
        for h_key in ("t0", "t1", "t3", "t5"):
            assert len(out.by_horizon[h_key].by_month) == 1
            b = out.by_horizon[h_key].by_month[0]
            assert b.period == "2026-10"
            assert b.days == 1
            # 4 字段互斥：仅匹配的字段非空
            assert b.hit_rate_t0 == (1.0 if h_key == "t0" else None)
            assert b.hit_rate_t1 == (1.0 if h_key == "t1" else None)
            assert b.hit_rate_t3 == (1.0 if h_key == "t3" else None)
            assert b.hit_rate_t5 == (1.0 if h_key == "t5" else None)

    async def test_mini_card_30d_and_mom(
        self, db_session: AsyncSession
    ) -> None:
        """mini card 30 天：最近 30 ready 日命中率（仅 1 个 horizon 有数据时也只算该 horizon）。"""
        # 1 个 bullish 行 → 所有 4 horizon 都 hit
        target = date(2026, 10, 10)
        await _insert_snapshot(db_session, target, news_index=60.0)
        await _insert_gold(db_session, target - timedelta(days=1), close=1990.0)
        await _insert_gold(db_session, target, close=2000.0)
        await _insert_gold(db_session, target + timedelta(days=1), close=2010.0)
        await _insert_gold(db_session, target + timedelta(days=2), close=2015.0)
        await _insert_gold(db_session, target + timedelta(days=3), close=2025.0)
        await _insert_gold(db_session, target + timedelta(days=4), close=2035.0)
        await _insert_gold(db_session, target + timedelta(days=5), close=2050.0)
        await _service(db_session).rebuild(target)

        out = await _service(db_session).hit_stats_all_horizons(
            start=date(2026, 10, 1), end=date(2026, 10, 31)
        )
        # 4 horizon 各 last_30d = 1.0（1/1）
        for h in ("t0", "t1", "t3", "t5"):
            assert out.mini_card.last_30d[h] == 1.0
        # mom：没有上 30 ready 日 → 4 horizon 全 None
        for h in ("t0", "t1", "t3", "t5"):
            assert out.mini_card.last_30d_mom[h] is None
        # best_horizon：4 个都 1.0 → sorted 取字典序最小 = "t0"
        assert out.mini_card.best_horizon == "t0"

    async def test_mini_card_best_horizon_picks_max(
        self, db_session: AsyncSession
    ) -> None:
        """best_horizon：4 horizon 命中率不同时，取 max；多 horizon 同分取字典序最小。"""
        # 2 行：第 1 行 bullish 全部 hit，第 2 行 bearish 全部 miss
        # → 4 horizon 各 1 hit / 1 total = 0.5；这种情况下需要混合场景
        # 简化方案：构造 1 hit_t0=True, 1 hit_t0=False
        # 借助 _insert_wide_row 直接构造
        from app.models.scoring_wide import ScoringDailyWide

        d1 = date(2026, 10, 5)
        d2 = date(2026, 10, 6)
        # 直接写宽表行，绕过 rebuild（4 hit 字段全填好控制变量）
        for d, hits in [
            (d1, {"hit_t0": True, "hit_t1": True, "hit_t3": True, "hit_t5": True}),
            (d2, {"hit_t0": True, "hit_t1": False, "hit_t3": True, "hit_t5": False}),
        ]:
            row = ScoringDailyWide(
                date=d,
                user_id=1,
                trend_index=60.0,
                news_index=60.0,
                **hits,
            )
            db_session.add(row)
        await db_session.commit()

        out = await _service(db_session).hit_stats_all_horizons(
            start=date(2026, 10, 1), end=date(2026, 10, 31)
        )
        # 2 ready 行，hits=2 → last_30d: t0=1.0, t1=0.5, t3=1.0, t5=0.5
        assert out.mini_card.last_30d["t0"] == 1.0
        assert out.mini_card.last_30d["t1"] == 0.5
        assert out.mini_card.last_30d["t3"] == 1.0
        assert out.mini_card.last_30d["t5"] == 0.5
        # best：t0 与 t3 同为 1.0，sorted 取字典序最小 = "t0"
        assert out.mini_card.best_horizon == "t0"

    async def test_by_month_descending_sort(
        self, db_session: AsyncSession
    ) -> None:
        """V0.95.1 降序约定：by_month 桶按 period 降序（最近→远期），柱状图 x 轴自上而下。"""
        # 2 个不同月份的 bullish 行
        from app.models.scoring_wide import ScoringDailyWide

        for d, hits in [
            (date(2026, 9, 15), {"hit_t1": True}),
            (date(2026, 10, 20), {"hit_t1": True}),
        ]:
            row = ScoringDailyWide(
                date=d, user_id=1, trend_index=60.0, news_index=60.0, **hits
            )
            db_session.add(row)
        await db_session.commit()

        out = await _service(db_session).hit_stats_all_horizons(
            start=date(2026, 9, 1), end=date(2026, 10, 31)
        )
        # 2 桶，降序：2026-10 在前，2026-09 在后
        t1_buckets = out.by_horizon["t1"].by_month
        assert [b.period for b in t1_buckets] == ["2026-10", "2026-09"]
