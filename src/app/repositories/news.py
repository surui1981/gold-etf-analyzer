"""消息面打分仓储（V0.65.0：每日最多 3 次，按 slot 区分）。"""

from datetime import date, datetime, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news import NewsScore


class NewsScoreRepository:
    """消息面每日打分数据访问。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_date(self, score_date: date) -> list[NewsScore]:
        """当日已打分的全部槽位，按 slot 升序（第 1 次 → 第 3 次）。"""
        stmt = (
            select(NewsScore)
            .where(NewsScore.score_date == score_date)
            .order_by(NewsScore.slot)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_by_slot(self, score_date: date, slot: int) -> NewsScore | None:
        """取指定日期 + 槽位的记录。"""
        stmt = select(NewsScore).where(
            NewsScore.score_date == score_date, NewsScore.slot == slot
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_date(self, score_date: date) -> NewsScore | None:
        """取当日**最新一次**打分（兼容旧调用：单值语义取最后一个槽位）。"""
        stmt = (
            select(NewsScore)
            .where(NewsScore.score_date == score_date)
            .order_by(NewsScore.slot.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_previous(self, score_date: date, slot: int) -> NewsScore | None:
        """查询 (score_date, slot) 之前最近一次打分（供「沿用上次」）。

        同日更早槽位与历史日期都算，便于第 2/3 次打分一键沿用上一次研判。
        """
        stmt = (
            select(NewsScore)
            .where(
                or_(
                    NewsScore.score_date < score_date,
                    and_(NewsScore.score_date == score_date, NewsScore.slot < slot),
                )
            )
            .order_by(NewsScore.score_date.desc(), NewsScore.slot.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_recent(self, limit: int = 15) -> list[NewsScore]:
        """最近若干条打分（跨日，按时间倒序），供历史回看。"""
        stmt = (
            select(NewsScore)
            .order_by(NewsScore.score_date.desc(), NewsScore.slot.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def upsert(
        self,
        *,
        score_date: date,
        slot: int,
        score: float,
        direction: str,
        notes: str = "",
    ) -> NewsScore:
        """写入指定槽位；已存在则覆盖（用于修正），并刷新打分时刻。"""
        now = datetime.now(timezone.utc)
        existing = await self.get_by_slot(score_date, slot)
        if existing is None:
            record = NewsScore(
                score_date=score_date,
                slot=slot,
                score=score,
                direction=direction,
                notes=notes,
                scored_at=now,
            )
            self._session.add(record)
        else:
            existing.score = score
            existing.direction = direction
            existing.notes = notes
            existing.scored_at = now
            record = existing
        await self._session.commit()
        await self._session.refresh(record)
        return record

    async def delete_slot(self, score_date: date, slot: int) -> bool:
        """撤销某次打分；不存在返回 False。"""
        record = await self.get_by_slot(score_date, slot)
        if record is None:
            return False
        await self._session.delete(record)
        await self._session.commit()
        return True
