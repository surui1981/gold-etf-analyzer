"""消息面打分服务测试：默认中性、保存生效、上次打分（沿用功能）。"""

from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news import NewsScore
from app.repositories.news import NewsScoreRepository
from app.schemas.news import NewsScoreIn
from app.services.news import NewsScoreService


def _svc(db: AsyncSession) -> NewsScoreService:
    return NewsScoreService(NewsScoreRepository(db))


async def test_default_neutral_without_history(db_session: AsyncSession) -> None:
    """未打分且无历史 → 中性 50，scored=False，last_score 为 None。"""
    out = await _svc(db_session).get_today()

    assert out.scored is False
    assert out.score == 50.0
    assert out.last_score is None
    assert out.last_date is None


async def test_save_then_scored(db_session: AsyncSession) -> None:
    """保存后当日返回已打分状态与分数。"""
    svc = _svc(db_session)
    saved = await svc.save_today(NewsScoreIn(score=70, direction="bullish", notes="投行看多"))

    assert saved.scored is True
    assert saved.score == 70.0

    out = await svc.get_today()
    assert out.scored is True
    assert out.score == 70.0
    assert out.notes == "投行看多"


async def test_save_invalidates_served_cache(db_session: AsyncSession) -> None:
    """消息面评分保存 → TrendService.invalidate_for_news（→ served cache 清空）。"""
    from app.services import cache as served_cache

    # 预填一份缓存，模拟"今日评估已生成"
    served_cache.invalidate()
    # 用任意 GoldTrendOut 占位（仅测试缓存键是否被清空）
    from datetime import date
    from app.schemas.common import DirectionSignal
    from app.schemas.market import (
        GoldTrendMetrics, GoldTrendOut, GoldTrendPoint,
        MacroIndexOut, NewsIndexOut, TrendDirection,
        TrendIndexLevel, TrendIndexOut,
    )
    today = date.today()
    placeholder = GoldTrendOut(
        symbol="GC", name="test", days=1,
        points=[GoldTrendPoint(date=today, close=1.0, ma5=None, ma20=None, ma40=None)],
        metrics=GoldTrendMetrics(
            start_date=today, end_date=today, trading_days=1,
            start_price=1.0, end_price=1.0, change_pct=0.0,
            high=1.0, low=1.0, ma20=None, ma40=None,
            change_pct_1d=0.0, change_pct_5d=0.0,
            direction=TrendDirection.SIDEWAYS, unit="", summary="",
        ),
        indicators=[],
        index=TrendIndexOut(score=50.0, level=TrendIndexLevel.SIDEWAYS,
                            direction=DirectionSignal.NEUTRAL, summary=""),
        macro=MacroIndexOut(score=50.0, direction=DirectionSignal.NEUTRAL, factors=[], summary=""),
        news=NewsIndexOut(score=50.0, direction=DirectionSignal.NEUTRAL, note="", scored=False),
        data_sources={}, degraded=False, freshness=None,
    )
    served_cache.set_served("ny", placeholder)
    assert served_cache.get_served("ny") is placeholder

    # 保存消息面 → 应触发失效
    svc = _svc(db_session)
    await svc.save_today(NewsScoreIn(score=80, direction="bullish", notes=""))

    # 缓存被清空（下次请求全量重算）
    assert served_cache.get_served("ny") is None


async def test_last_score_for_reuse(db_session: AsyncSession) -> None:
    """历史打分可作为上次分数返回（供「沿用上次」）。"""
    yesterday = date.today() - timedelta(days=1)
    db_session.add(
        NewsScore(score_date=yesterday, score=35.0, direction="bearish", notes="昨日看空")
    )
    await db_session.commit()

    out = await _svc(db_session).get_today()

    assert out.scored is False  # 今日仍未打分
    assert out.last_score == 35.0
    assert out.last_date == yesterday
    assert out.last_notes == "昨日看空"


async def test_save_overwrites_same_day(db_session: AsyncSession) -> None:
    """同日重复保存为覆盖，不产生多条记录。"""
    svc = _svc(db_session)
    await svc.save_today(NewsScoreIn(score=40, direction="bearish", notes="初次"))
    await svc.save_today(NewsScoreIn(score=65, direction="bullish", notes="修正"))

    out = await svc.get_today()
    assert out.score == 65.0
    assert out.notes == "修正"
