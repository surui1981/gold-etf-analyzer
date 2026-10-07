"""分析记录仓储：封装对 AnalysisRecord 表的所有访问。"""

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis import AnalysisRecord
from app.utils.user_scope import resolve_user_id


class AnalysisRepository:
    """数据访问层：屏蔽 SQL 细节，服务层只面向领域对象。

    ⚠ **V0.80.0 数据隔离（任务 #159 第 2 批）**：``create`` 落库时写入归属用户，
    ``list_recent`` 按当前用户过滤。改前**完全没有用户过滤** ⇒ 多用户下
    一个用户能看到另一个用户的机会分析记录（含因子明细与评分）。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **fields: object) -> AnalysisRecord:
        """插入一条分析记录并返回带 ID 的完整对象。

        Args:
            **fields: 与 AnalysisRecord 列同名的字段

        Returns:
            已持久化的 AnalysisRecord（含 id / created_at）
        """
        user_id = resolve_user_id(fields.pop("user_id", None))
        record = AnalysisRecord(user_id=user_id, **fields)
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)  # 回填 server_default 的 created_at
        return record

    async def list_recent(
        self, limit: int = 20, user_id: int | None = None
    ) -> list[AnalysisRecord]:
        """按创建时间倒序返回**当前用户**的最近记录。

        Args:
            limit: 返回条数上限
            user_id: 用户 ID；None=取当前请求上下文（V0.75.2）

        Returns:
            最近的 AnalysisRecord 列表（已按用户过滤）
        """
        user_id = resolve_user_id(user_id)
        stmt = (
            select(AnalysisRecord)
            .where(AnalysisRecord.user_id == user_id)
            .order_by(desc(AnalysisRecord.created_at))
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
