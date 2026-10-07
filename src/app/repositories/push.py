"""V0.72.0 P3-b：push_subscriptions 仓储。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.push import PushSubscription
from app.utils.user_scope import ALL_USERS, resolve_user_id


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
        user_id: int | None = None,
    ) -> PushSubscription:
        """同一 (user_id, endpoint) 重复订阅视为同一记录（更新密钥 + 取消归档）。

        ⚠ V0.80.0：查找键从 ``endpoint`` 改为 ``(user_id, endpoint)`` ——
        同一台设备可能登录不同用户，只按 endpoint 匹配会让 B 用户覆盖
        A 用户的订阅密钥（推送到错误的人）。
        """
        user_id = resolve_user_id(user_id)
        existing = await self._session.scalar(
            select(PushSubscription).where(
                PushSubscription.endpoint == endpoint,
                PushSubscription.user_id == user_id,
            ),
        )
        if existing is not None:
            existing.p256dh = p256dh
            existing.auth = auth
            existing.user_agent = user_agent
            existing.archived_at = None
            await self._session.commit()
            return existing
        sub = PushSubscription(
            user_id=user_id,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            user_agent=user_agent,
        )
        self._session.add(sub)
        await self._session.commit()
        return sub

    async def list_active(self, user_id: int | None = None) -> list[PushSubscription]:
        """未归档的订阅（**默认仅当前用户**；系统级推送需显式传 user_id）。

        ⚠ V0.80.0：默认按用户过滤。⚠ **系统级广播必须显式传参** ——
        若推送服务需要在全库范围取订阅（服务级推送），须由调用方明确表达，
        不能靠「忘了传 ⇒ 不过滤」的默认行为实现（那正是越权的成因）。
        """
        # ⚠ V0.80.0：``ALL_USERS`` 是显式的「不限用户」哨兵值 —— 只有服务级操作
        # （告警广播 / 管理员验证）才允许用它。其余调用走默认的当前用户过滤。
        stmt = select(PushSubscription).where(PushSubscription.archived_at.is_(None))
        if user_id is None:
            user_id = resolve_user_id(None)
        if user_id != ALL_USERS:
            stmt = stmt.where(PushSubscription.user_id == user_id)
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def archive_by_endpoint(self, endpoint: str, user_id: int | None = None) -> bool:
        """archive 失效订阅（push 服务返 410 Gone 时调用）。

        V0.80.0：跨用户归档一律 False（不碰别人的订阅）。
        """
        user_id = resolve_user_id(user_id)
        result = await self._session.execute(
            update(PushSubscription)
            .where(PushSubscription.endpoint == endpoint)
            .where(PushSubscription.user_id == user_id)
            .where(PushSubscription.archived_at.is_(None))
            .values(archived_at=datetime.now(timezone.utc))
        )
        await self._session.commit()
        return result.rowcount > 0  # type: ignore[no-any-return]

    async def delete_by_endpoint(self, endpoint: str, user_id: int | None = None) -> bool:
        """用户主动退订时硬删（跨用户退订返回 False）。"""
        user_id = resolve_user_id(user_id)
        sub = await self._session.scalar(
            select(PushSubscription).where(
                PushSubscription.endpoint == endpoint,
                PushSubscription.user_id == user_id,
            ),
        )
        if sub is None:
            return False
        await self._session.delete(sub)
        await self._session.commit()
        return True
