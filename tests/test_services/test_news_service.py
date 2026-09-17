"""消息面打分服务测试：默认中性、每日 3 次槽位、1:2:3 加权、撤销与历史。

V0.65.0 起每日最多 3 次打分（slot 1/2/3），当日有效分值按「越晚权重越高」
的 1:2:3 加权合成。
"""

from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news import NewsScore
from app.repositories.news import NewsScoreRepository
from app.schemas.news import NewsScoreIn
from app.services.news import NewsScoreService


def _svc(db: AsyncSession) -> NewsScoreService:
    return NewsScoreService(NewsScoreRepository(db))


async def test_default_neutral_without_history(db_session: AsyncSession) -> None:
    """未打分且无历史 → 中性 50，scored=False，槽位全空。"""
    out = await _svc(db_session).get_today()

    assert out.scored is False
    assert out.score == 50.0
    assert out.slots == []
    assert out.used_slots == 0
    assert out.remaining_slots == 3
    assert out.next_slot == 1
    assert out.last_score is None
    assert out.last_date is None


async def test_first_save_uses_slot_1(db_session: AsyncSession) -> None:
    """首次打分自动占用第 1 个槽位，权重 1。"""
    svc = _svc(db_session)
    out = await svc.save_today(NewsScoreIn(score=70, direction="bullish", notes="投行看多"))

    assert out.scored is True
    assert out.score == 70.0
    assert out.used_slots == 1
    assert out.remaining_slots == 2
    assert out.next_slot == 2
    assert out.weighted is False
    assert len(out.slots) == 1
    assert out.slots[0].slot == 1
    assert out.slots[0].weight == 1
    assert out.slots[0].scored_at is not None


async def test_three_saves_fill_slots_and_weighted(db_session: AsyncSession) -> None:
    """3 次打分依次占用 slot 1/2/3，有效分值按 1:2:3 加权。"""
    svc = _svc(db_session)
    await svc.save_today(NewsScoreIn(score=40, direction="bearish"))
    await svc.save_today(NewsScoreIn(score=60, direction="bullish"))
    out = await svc.save_today(NewsScoreIn(score=70, direction="bullish"))

    assert [s.slot for s in out.slots] == [1, 2, 3]
    assert [s.weight for s in out.slots] == [1, 2, 3]
    assert out.used_slots == 3
    assert out.remaining_slots == 0
    assert out.next_slot is None
    assert out.weighted is True
    # (1×40 + 2×60 + 3×70) / 6 = 370/6 = 61.666… → 61.7
    assert out.score == 61.7
    assert out.formula == "(1×40 + 2×60 + 3×70) ÷ 6"


async def test_fourth_save_without_slot_rejected(db_session: AsyncSession) -> None:
    """3 次用尽后留空 slot 再提交 → 报错（不再静默覆盖）。"""
    svc = _svc(db_session)
    for s in (40, 60, 70):
        await svc.save_today(NewsScoreIn(score=s, direction="neutral"))

    with pytest.raises(ValueError, match="3 次打分机会已用完"):
        await svc.save_today(NewsScoreIn(score=80, direction="bullish"))


async def test_explicit_slot_overwrites(db_session: AsyncSession) -> None:
    """显式指定 slot → 覆盖该槽位（用于修正），不占用新槽位。"""
    svc = _svc(db_session)
    await svc.save_today(NewsScoreIn(score=40, direction="bearish"))
    await svc.save_today(NewsScoreIn(score=60, direction="bullish"))
    await svc.save_today(NewsScoreIn(score=70, direction="bullish"))

    out = await svc.save_today(NewsScoreIn(score=45, direction="neutral", slot=2))

    assert len(out.slots) == 3
    assert out.used_slots == 3
    assert [round(s.score) for s in out.slots] == [40, 45, 70]
    # (1×40 + 2×45 + 3×70) / 6 = 340/6 = 56.666… → 56.7
    assert out.score == 56.7


async def test_delete_slot_releases_and_reweighs(db_session: AsyncSession) -> None:
    """撤销某次打分 → 释放槽位，剩余按权重重新归一。"""
    svc = _svc(db_session)
    await svc.save_today(NewsScoreIn(score=40, direction="bearish"))
    await svc.save_today(NewsScoreIn(score=60, direction="neutral"))
    await svc.save_today(NewsScoreIn(score=70, direction="bullish"))

    out = await svc.delete_slot(2)

    assert [s.slot for s in out.slots] == [1, 3]
    assert out.used_slots == 2
    assert out.next_slot == 2
    # (1×40 + 3×70) / 4 = 250/4 = 62.5
    assert out.score == 62.5


async def test_delete_missing_slot_raises(db_session: AsyncSession) -> None:
    """撤销不存在的槽位 → 报错。"""
    with pytest.raises(ValueError, match="不存在"):
        await _svc(db_session).delete_slot(2)


async def test_reuse_previous_slot_same_day(db_session: AsyncSession) -> None:
    """第 2 次打分时，「沿用上次」应指向同日第 1 次（而非只找历史日期）。"""
    svc = _svc(db_session)
    await svc.save_today(NewsScoreIn(score=35, direction="bearish", notes="早间看空"))

    out = await svc.get_today()

    assert out.scored is True
    assert out.next_slot == 2
    assert out.last_score == 35.0
    assert out.last_date == date.today()
    assert out.last_notes == "早间看空"


async def test_last_score_from_history(db_session: AsyncSession) -> None:
    """无当日打分时，「沿用上次」取历史最近一次。"""
    yesterday = date.today() - timedelta(days=1)
    db_session.add(
        NewsScore(score_date=yesterday, slot=1, score=35.0, direction="bearish", notes="昨日看空")
    )
    await db_session.commit()

    out = await _svc(db_session).get_today()

    assert out.scored is False
    assert out.last_score == 35.0
    assert out.last_date == yesterday
    assert out.last_notes == "昨日看空"


async def test_history_lists_desc(db_session: AsyncSession) -> None:
    """历史记录按日期/槽位倒序返回。"""
    svc = _svc(db_session)
    yesterday = date.today() - timedelta(days=1)
    db_session.add(
        NewsScore(score_date=yesterday, slot=1, score=30.0, direction="bearish", notes="昨")
    )
    await db_session.commit()
    await svc.save_today(NewsScoreIn(score=60, direction="bullish", notes="今"))
    await svc.save_today(NewsScoreIn(score=70, direction="bullish", notes="今2"))

    hist = await svc.get_history(limit=10)

    assert hist.total == 3
    assert hist.items[0].score_date == date.today()
    assert hist.items[0].slot == 2
    assert hist.items[-1].score_date == yesterday


async def test_save_invalidates_served_cache(db_session: AsyncSession) -> None:
    """消息面评分保存 → TrendService.invalidate_for_news（→ served cache 清空）。"""
    from app.services import cache as served_cache

    served_cache.invalidate()
    from app.schemas.common import DirectionSignal
    from app.schemas.market import (
        GoldTrendMetrics,
        GoldTrendOut,
        GoldTrendPoint,
        MacroIndexOut,
        NewsIndexOut,
        TrendDirection,
        TrendIndexLevel,
        TrendIndexOut,
    )

    today = date.today()
    placeholder = GoldTrendOut(
        symbol="GC",
        name="test",
        days=1,
        points=[GoldTrendPoint(date=today, close=1.0, ma5=None, ma20=None, ma40=None)],
        metrics=GoldTrendMetrics(
            start_date=today,
            end_date=today,
            trading_days=1,
            start_price=1.0,
            end_price=1.0,
            change_pct=0.0,
            high=1.0,
            low=1.0,
            ma20=None,
            ma40=None,
            change_pct_1d=0.0,
            change_pct_5d=0.0,
            direction=TrendDirection.SIDEWAYS,
            unit="",
            summary="",
        ),
        indicators=[],
        index=TrendIndexOut(
            score=50.0,
            level=TrendIndexLevel.SIDEWAYS,
            direction=DirectionSignal.NEUTRAL,
            summary="",
        ),
        macro=MacroIndexOut(score=50.0, direction=DirectionSignal.NEUTRAL, factors=[], summary=""),
        news=NewsIndexOut(score=50.0, direction=DirectionSignal.NEUTRAL, note="", scored=False),
        data_sources={},
        degraded=False,
        freshness=None,
    )
    served_cache.set_served("ny", placeholder)
    assert served_cache.get_served("ny") is placeholder

    await _svc(db_session).save_today(NewsScoreIn(score=80, direction="bullish", notes=""))

    assert served_cache.get_served("ny") is None
