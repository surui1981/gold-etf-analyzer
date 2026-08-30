"""分析记录仓储：封装对 AnalysisRecord 表的所有访问。"""

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis import AnalysisRecord


class AnalysisRepository:
    """数据访问层：屏蔽 SQL 细节，服务层只面向领域对象。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **fields: object) -> AnalysisRecord:
        """插入一条分析记录并返回带 ID 的完整对象。

        Args:
            **fields: 与 AnalysisRecord 列同名的字段

        Returns:
            已持久化的 AnalysisRecord（含 id / created_at）
        """
        record = AnalysisRecord(**fields)
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)  # 回填 server_default 的 created_at
        return record

    async def list_recent(self, limit: int = 20) -> list[AnalysisRecord]:
        """按创建时间倒序返回最近记录。

        Args:
            limit: 返回条数上限

        Returns:
            最近的 AnalysisRecord 列表
        """
        stmt = (
            select(AnalysisRecord)
            .order_by(desc(AnalysisRecord.created_at))
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
