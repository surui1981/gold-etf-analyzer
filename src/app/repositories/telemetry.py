"""前端埋点仓储（V0.68.0）。

设计：append-only。前端只 INSERT，服务端无更新 / 删除（按 retention SQL 由清理脚本处理）。
"""

import json
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.telemetry import TelemetryEvent


class TelemetryRepository:
    """埋点事件数据访问（append-only 写入 + 派生聚合读）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(self, event: TelemetryEvent) -> TelemetryEvent:
        """插入单条埋点（commit 由调用方控制）。"""
        self._session.add(event)
        await self._session.flush()
        return event

    async def insert_batch(self, events: list[TelemetryEvent]) -> int:
        """批量插入；返回成功条数（SQLAlchemy 自动 commit）。"""
        if not events:
            return 0
        self._session.add_all(events)
        await self._session.commit()
        return len(events)

    async def count_by_type(self, since: datetime) -> dict[str, int]:
        """按事件类型统计条数（>= since）。"""
        stmt = (
            select(TelemetryEvent.event_type, func.count(TelemetryEvent.id))
            .where(TelemetryEvent.created_at >= since)
            .group_by(TelemetryEvent.event_type)
        )
        rows = (await self._session.execute(stmt)).all()
        return {evt: int(cnt) for evt, cnt in rows}

    async def count_total(self, since: datetime) -> int:
        """统计总条数（>= since）。"""
        stmt = select(func.count(TelemetryEvent.id)).where(TelemetryEvent.created_at >= since)
        return int((await self._session.execute(stmt)).scalar() or 0)


def _event_to_model(
    *,
    event_type: str,
    page: str,
    payload: dict[str, object],
    session_id: str,
    trace_id: str | None,
) -> TelemetryEvent:
    """从上报字段构造 ORM 模型（payload 序列化为 JSON 文本）。"""
    return TelemetryEvent(
        event_type=event_type[:32],
        page=page[:128],
        payload=json.dumps(payload, ensure_ascii=False, separators=(",", ":"))[:8192],
        session_id=session_id[:32],
        trace_id=(trace_id or None) and trace_id[:32],
        user_id="1",  # V0.75.0 前预留
        created_at=datetime.now(timezone.utc),
    )


__all__ = ["TelemetryRepository", "_event_to_model"]
