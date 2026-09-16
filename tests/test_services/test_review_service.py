"""研判复盘服务测试（V0.66.0）：命中判定、交易日对齐、补录排除、校准统计。"""

import json
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news import NewsScore
from app.repositories.news import NewsScoreRepository
from app.repositories.review import GoldPriceRepository
from app.schemas.common import DirectionSignal
from app.services.review import ReviewService, judge_hit


def _svc(db: AsyncSession) -> ReviewService:
    return ReviewService(
        gold=GoldPriceRepository(db),
        news=NewsScoreRepository(db),
    )


async def _seed_prices(db: AsyncSession, closes: list[float], end_offset: int = 0):
    """按「连续交易日」铺价格：最后一条落在 today - end_offset。

    Returns:
        [(交易日, 收盘价), ...]（升序）
    """
    today = date.today()
    start = today - timedelta(days=len(closes) - 1 + end_offset)
    bars = [(start + timedelta(days=i), float(c)) for i, c in enumerate(closes)]
    await GoldPriceRepository(db).upsert_many(target="ny", bars=bars, source="test")
    return bars


async def _seed_score(
    db: AsyncSession,
    score_date: date,
    score: float,
    direction: str,
    *,
    basis: list[str] | None = None,
    slot: int = 1,
    backfilled: int = 0,
) -> None:
    db.add(
        NewsScore(
            score_date=score_date,
            slot=slot,
            score=score,
            direction=direction,
            notes="测试备注",
            basis=json.dumps(basis or [], ensure_ascii=False),
            review_note="",
            backfilled=backfilled,
            scored_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()


# ---------- 命中判定口径 ----------


def test_judge_hit_bullish_requires_gain() -> None:
    """看多：必须上涨才命中，持平（0%）算偏离。"""
    assert judge_hit(DirectionSignal.BULLISH, 1.5)[0] is True
    assert judge_hit(DirectionSignal.BULLISH, 0.0)[0] is False
    assert judge_hit(DirectionSignal.BULLISH, -0.8)[0] is False


def test_judge_hit_bearish_requires_drop() -> None:
    """看空：必须下跌才命中。"""
    assert judge_hit(DirectionSignal.BEARISH, -1.2)[0] is True
    assert judge_hit(DirectionSignal.BEARISH, 0.0)[0] is False
    assert judge_hit(DirectionSignal.BEARISH, 0.9)[0] is False


def test_judge_hit_neutral_uses_band() -> None:
    """看平：涨跌幅在 ±0.3% 容差内算命中。"""
    assert judge_hit(DirectionSignal.NEUTRAL, 0.2)[0] is True
    assert judge_hit(DirectionSignal.NEUTRAL, -0.3)[0] is True
    assert judge_hit(DirectionSignal.NEUTRAL, 0.5)[0] is False
    assert judge_hit(DirectionSignal.NEUTRAL, -1.0)[0] is False


# ---------- 价格日历 ----------


async def test_upsert_many_is_idempotent_and_keeps_change(db_session: AsyncSession) -> None:
    """重复回填幂等，且不会把已有涨跌幅抹平。"""
    repo = GoldPriceRepository(db_session)
    today = date.today()
    bars = [(today - timedelta(days=2), 100.0), (today - timedelta(days=1), 102.0), (today, 101.0)]

    assert await repo.upsert_many(target="ny", bars=bars, source="test") == 3
    rows = await repo.list_range("ny")
    assert [r.close for r in rows] == [100.0, 102.0, 101.0]
    assert rows[1].change_pct == 2.0  # (102-100)/100
    assert rows[2].change_pct == -0.98  # (101-102)/102 ≈ -0.98

    # 再回填一次：条数不变，值保持
    assert await repo.upsert_many(target="ny", bars=bars, source="test") == 3
    assert await repo.count("ny") == 3
    rows2 = await repo.list_range("ny")
    assert rows2[2].change_pct == -0.98


# ---------- 按交易日对齐 ----------


async def test_journal_aligns_t_plus_n(db_session: AsyncSession) -> None:
    """研判日对齐 T+1/T+3/T+5：基准为当日收盘，窗口按价格序列顺延。"""
    closes = [100, 102, 101, 103, 104, 100, 98, 99, 101, 105]
    bars = await _seed_prices(db_session, closes)
    d_a = bars[0][0]  # 100 → T+1 102(+2%) / T+3 103(+3%) / T+5 100(0%)
    d_b = bars[3][0]  # 103 → T+1 104(+0.97%) / T+3 98(-4.85%) / T+5 101(-1.94%)

    await _seed_score(db_session, d_a, 70, "bullish", basis=["美元指数"])
    await _seed_score(db_session, d_b, 30, "bearish", basis=["美债收益率"])

    out = await _svc(db_session).journal(days=10, horizon=1)

    assert out.total == 2
    assert [i.score_date for i in out.items] == [d_b, d_a]  # 日期倒序

    day_a = out.items[1]
    assert day_a.price_close == 100.0
    assert day_a.direction is DirectionSignal.BULLISH
    o = {x.horizon: x for x in day_a.outcomes}
    assert o[1].change_pct == 2.0 and o[1].hit is True
    assert o[3].change_pct == 3.0 and o[3].hit is True
    assert o[5].change_pct == 0.0 and o[5].hit is False  # 看多须严格上涨

    day_b = out.items[0]
    ob = {x.horizon: x for x in day_b.outcomes}
    assert ob[1].change_pct == 0.97 and ob[1].hit is False
    assert ob[3].change_pct == -4.85 and ob[3].hit is True
    assert ob[5].change_pct == -1.94 and ob[5].hit is True


async def test_journal_marks_pending_when_not_due(db_session: AsyncSession) -> None:
    """最近一天的 T+1 尚未到期 → 状态 pending，不计入命中。"""
    closes = [100, 101, 102]
    bars = await _seed_prices(db_session, closes)
    await _seed_score(db_session, bars[-1][0], 70, "bullish")

    out = await _svc(db_session).journal(days=10, horizon=1)

    assert out.total == 1
    assert out.pending == 1
    o = out.items[0].outcomes
    assert all(x.status == "pending" for x in o)
    assert o[0].hit is None
    assert "尚未到期" in o[0].label


async def test_journal_no_score_returns_empty(db_session: AsyncSession) -> None:
    """无研判记录时返回空列表（不因缺价格报错）。"""
    out = await _svc(db_session).journal(days=30)
    assert out.total == 0
    assert out.items == []


# ---------- 统计与校准 ----------


async def test_stats_hit_rate_and_groups(db_session: AsyncSession) -> None:
    """T+1 命中率、按方向分组、按窗口分组均按排除补录后的样本计算。"""
    closes = [100, 102, 101, 103, 104, 100, 98, 99, 101, 105]
    bars = await _seed_prices(db_session, closes)
    await _seed_score(db_session, bars[0][0], 70, "bullish", basis=["美元指数"])
    await _seed_score(db_session, bars[3][0], 30, "bearish", basis=["美债收益率"])

    s = await _svc(db_session).stats(days=10, horizon=1)

    assert s.total_days == 2
    assert s.evaluated == 2
    assert s.hits == 1
    assert s.hit_rate == 50.0
    assert s.sample_warning is True  # 样本 < 20

    by_dir = {d.direction: d for d in s.by_direction}
    assert by_dir[DirectionSignal.BULLISH].samples == 1
    assert by_dir[DirectionSignal.BULLISH].hit_rate == 100.0
    assert by_dir[DirectionSignal.BEARISH].samples == 1
    assert by_dir[DirectionSignal.BEARISH].hit_rate == 0.0
    assert by_dir[DirectionSignal.NEUTRAL].samples == 0
    assert by_dir[DirectionSignal.NEUTRAL].hit_rate is None

    by_h = {h.horizon: h for h in s.by_horizon}
    assert by_h[1].samples == 2 and by_h[1].hit_rate == 50.0
    assert by_h[3].samples == 2 and by_h[3].hit_rate == 100.0
    assert by_h[5].samples == 2 and by_h[5].hit_rate == 50.0


async def test_stats_calibration_buckets(db_session: AsyncSession) -> None:
    """校准曲线按分值分箱，给出该箱实际上涨概率与命中率。"""
    closes = [100, 102, 101, 103, 104, 100, 98, 99, 101, 105]
    bars = await _seed_prices(db_session, closes)
    await _seed_score(db_session, bars[0][0], 70, "bullish")
    await _seed_score(db_session, bars[3][0], 30, "bearish")

    s = await _svc(db_session).stats(days=10, horizon=1)
    buckets = {b.key: b for b in s.calibration}

    assert len(s.calibration) == 5
    assert buckets["60-80"].samples == 1
    assert buckets["60-80"].up_rate == 100.0
    assert buckets["60-80"].hit_rate == 100.0
    assert buckets["20-40"].samples == 1
    assert buckets["20-40"].hit_rate == 0.0
    assert buckets["0-20"].samples == 0 and buckets["0-20"].up_rate is None


async def test_stats_tag_win_rate(db_session: AsyncSession) -> None:
    """依据标签胜率：同一标签跨日合并统计。"""
    closes = [100, 102, 101, 103, 104, 100, 98, 99, 101, 105]
    bars = await _seed_prices(db_session, closes)
    await _seed_score(db_session, bars[0][0], 70, "bullish", basis=["美元指数", "央行购金"])
    await _seed_score(db_session, bars[3][0], 30, "bearish", basis=["美元指数"])

    s = await _svc(db_session).stats(days=10, horizon=1)
    tags = {t.tag: t for t in s.tags}

    assert tags["美元指数"].samples == 2
    assert tags["美元指数"].hits == 1
    assert tags["美元指数"].hit_rate == 50.0
    assert tags["央行购金"].samples == 1
    assert tags["央行购金"].hit_rate == 100.0


async def test_stats_excludes_backfilled(db_session: AsyncSession) -> None:
    """补录样本默认排除，避免前视偏差抬高命中率。"""
    closes = [100, 102, 101, 103, 104, 100, 98, 99, 101, 105]
    bars = await _seed_prices(db_session, closes)
    await _seed_score(db_session, bars[0][0], 70, "bullish")
    # 事后补录：已知会涨，若计入则命中率虚高
    await _seed_score(db_session, bars[3][0], 70, "bullish", backfilled=1)

    s = await _svc(db_session).stats(days=10, horizon=1)

    assert s.total_days == 2
    assert s.backfilled_excluded == 1
    assert s.evaluated == 1
    assert s.hits == 1
    assert s.hit_rate == 100.0


async def test_hint_for_score_uses_matching_bucket(db_session: AsyncSession) -> None:
    """打分前提示：按拟打分值命中对应分箱的历史表现。"""
    closes = [100, 102, 101, 103, 104, 100, 98, 99, 101, 105]
    bars = await _seed_prices(db_session, closes)
    await _seed_score(db_session, bars[0][0], 70, "bullish")

    hint = await _svc(db_session).hint_for_score(72.0, days=10)

    assert hint["bucket"] == "60-80"
    assert hint["samples"] == 1
    assert hint["hit_rate"] == 100.0
    assert hint["up_rate"] == 100.0
    assert hint["sample_warning"] is True


async def test_meta_reports_price_progress(db_session: AsyncSession) -> None:
    """元信息反映价格日历积累情况与预置依据标签。"""
    await _seed_prices(db_session, [100.0, 101.0, 102.0])

    m = await _svc(db_session).meta("ny")

    assert m.price_days == 3
    assert m.latest_price == 102.0
    assert "美元指数" in m.basis_tags
    assert m.horizons == [1, 3, 5]
    assert any(t["key"] == "ny" for t in m.targets)
