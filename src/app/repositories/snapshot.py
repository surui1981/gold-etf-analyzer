"""每日快照仓储：按日 upsert 与历史查询。"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.snapshot import DailySnapshot


class SnapshotRepository:
    """每日评估快照数据访问。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_date(self, snapshot_date: date) -> DailySnapshot | None:
        """按日期查询快照。"""
        stmt = select(DailySnapshot).where(DailySnapshot.snapshot_date == snapshot_date)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def upsert(self, snapshot: DailySnapshot) -> DailySnapshot:
        """按日期插入或更新（同一自然日重复捕获为更新）。"""
        existing = await self.get_by_date(snapshot.snapshot_date)
        if existing is None:
            self._session.add(snapshot)
        else:
            for field in (
                "close", "change_pct", "high", "low", "ma20", "ma40", "direction",
                "tech_index", "macro_index", "trend_index", "index_level", "macro_detail",
            ):
                setattr(existing, field, getattr(snapshot, field))
        await self._session.commit()
        return snapshot

    async def list_recent(self, days: int = 30) -> list[DailySnapshot]:
        """最近 N 天快照（按日期倒序）。"""
        stmt = (
            select(DailySnapshot)
            .order_by(DailySnapshot.snapshot_date.desc())
            .limit(days)
        )
        return list((await self._session.execute(stmt)).scalars().all())
