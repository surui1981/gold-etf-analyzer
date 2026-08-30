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
