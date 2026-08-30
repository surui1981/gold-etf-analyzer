"""消息面打分仓储。"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news import NewsScore


class NewsScoreRepository:
    """消息面每日打分数据访问。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_date(self, score_date: date) -> NewsScore | None:
        stmt = select(NewsScore).where(NewsScore.score_date == score_date)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def upsert(
        self,
        *,
        score_date: date,
        score: float,
        direction: str,
        notes: str = "",
    ) -> NewsScore:
        existing = await self.get_by_date(score_date)
        if existing is None:
            record = NewsScore(score_date=score_date, score=score, direction=direction, notes=notes)
            self._session.add(record)
        else:
            existing.score = score
            existing.direction = direction
            existing.notes = notes
            record = existing
        await self._session.commit()
        return record
