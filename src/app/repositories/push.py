"""V0.72.0 P3-b：push_subscriptions 仓储。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.push import PushSubscription


class PushSubscriptionRepository:
    """Web Push 订阅仓储：upsert by endpoint + 查询活跃订阅 + archive 失效订阅。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        *,
        endpoint: str,
        p256dh: str,
        auth: str,
        user_agent: str | None = None,
    ) -> PushSubscription:
        """同一 endpoint 重复订阅视为同一记录（更新密钥 + 取消归档）。"""
        existing = await self._session.scalar(
            select(PushSubscription).where(PushSubscription.endpoint == endpoint),
        )
        if existing is not None:
            existing.p256dh = p256dh
            existing.auth = auth
            existing.user_agent = user_agent
            existing.archived_at = None
            await self._session.commit()
            return existing
        sub = PushSubscription(
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            user_agent=user_agent,
        )
        self._session.add(sub)
        await self._session.commit()
        return sub

    async def list_active(self) -> list[PushSubscription]:
        """未归档的所有订阅。"""
        result = await self._session.scalars(
            select(PushSubscription).where(PushSubscription.archived_at.is_(None)),
        )
        return list(result.all())

    async def archive_by_endpoint(self, endpoint: str) -> bool:
        """archive 失效订阅（push 服务返 410 Gone 时调用）。"""
        result = await self._session.execute(
            update(PushSubscription)
            .where(PushSubscription.endpoint == endpoint)
            .where(PushSubscription.archived_at.is_(None))
            .values(archived_at=datetime.now(timezone.utc))
        )
        await self._session.commit()
        return result.rowcount > 0  # type: ignore[no-any-return]

    async def delete_by_endpoint(self, endpoint: str) -> bool:
        """用户主动退订时硬删。"""
        sub = await self._session.scalar(
            select(PushSubscription).where(PushSubscription.endpoint == endpoint),
        )
        if sub is None:
            return False
        await self._session.delete(sub)
        await self._session.commit()
        return True
