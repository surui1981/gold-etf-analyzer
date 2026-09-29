"""用户与会话仓储：封装 User / UserSession 的数据访问（V0.75.0）。

分层约定（与 :mod:`app.repositories.account` 一致）：仓储负责「查/写 + commit」，
不承载业务规则（密码策略、锁定、审计等一律在 :mod:`app.services.auth`）。

**为什么不用 ``session.commit()`` 直接暴露给端点**：仓储内部提交能让每个方法
自成事务边界（登录 = 「写 session + 更新 last_login_at」两次写，由服务层显式分派），
也便于测试用内存库替换。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserSession, utcnow


class DuplicateEmailError(Exception):
    """邮箱（登录名）已存在。**由唯一索引兜底**，不依赖服务层的先查后写。

    并发注册两个相同邮箱时，先查后写会双双通过检查 → 靠 ``ix_users_email``
    唯一索引拦下第二个，捕获 ``IntegrityError`` 后转为本异常。
    """


class UserRepository:
    """用户表数据访问。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: int) -> User | None:
        """按主键查询用户。"""
        stmt = select(User).where(User.id == user_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        """按规范化邮箱查询用户（调用方须先 lowercase）。"""
        stmt = select(User).where(User.email == email)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def count(self) -> int:
        """用户总数（用于「首个注册者成为 owner」判定）。"""
        stmt = select(func.count()).select_from(User)
        return int((await self._session.execute(stmt)).scalar_one())

    async def list_all(self) -> list[User]:
        """全部用户（按 id 升序）。V0.75.2 用户管理页使用。"""
        stmt = select(User).order_by(User.id)
        return list((await self._session.execute(stmt)).scalars().all())

    async def create(
        self,
        *,
        email: str,
        password_hash: str,
        display_name: str = "",
        role: str = "member",
    ) -> User:
        """新建用户并提交。

        Raises:
            DuplicateEmailError: ``email`` 已存在（唯一索引冲突）。
        """
        user = User(
            email=email,
            password_hash=password_hash,
            display_name=display_name or email.split("@", 1)[0],
            role=role,
        )
        self._session.add(user)
        try:
            await self._session.commit()
        except IntegrityError as exc:  # 唯一索引冲突（并发注册同邮箱）
            await self._session.rollback()
            raise DuplicateEmailError(email) from exc
        await self._session.refresh(user)
        return user

    async def mark_login(self, user: User, when: datetime) -> None:
        """记录登录成功时间（best-effort，失败不阻断登录）。"""
        user.last_login_at = when
        await self._session.commit()

    async def update_password_hash(self, user: User, password_hash: str) -> None:
        """更新密码哈希并提交（改密后由服务层撤销该用户全部会话）。"""
        user.password_hash = password_hash
        await self._session.commit()

    async def set_active(self, user: User, *, is_active: bool) -> None:
        """启用 / 禁用用户（禁用后服务层会撤销其全部会话）。"""
        user.is_active = is_active
        await self._session.commit()


class SessionRepository:
    """会话表数据访问。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        session_id: str,
        user_id: int,
        expires_at: datetime,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> UserSession:
        """签发一条会话并提交。"""
        row = UserSession(
            id=session_id,
            user_id=user_id,
            expires_at=expires_at,
            user_agent=(user_agent or None),
            ip=(ip or None),
        )
        self._session.add(row)
        await self._session.commit()
        return row

    async def get(self, session_id: str) -> UserSession | None:
        """按会话 ID 查询（**不过滤**撤销/过期，交由服务层判定并给出区分原因）。"""
        stmt = select(UserSession).where(UserSession.id == session_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def touch(self, session_id: str, when: datetime) -> None:
        """刷新 ``last_seen_at``（best-effort，用于「设备活跃度」审计）。"""
        stmt = update(UserSession).where(UserSession.id == session_id).values(last_seen_at=when)
        await self._session.execute(stmt)
        await self._session.commit()

    async def revoke(self, session_id: str, when: datetime) -> None:
        """撤销单个会话（登出）。"""
        stmt = (
            update(UserSession)
            .where(UserSession.id == session_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=when)
        )
        await self._session.execute(stmt)
        await self._session.commit()

    async def revoke_all_for_user(
        self,
        user_id: int,
        when: datetime,
        *,
        except_session_id: str | None = None,
    ) -> int:
        """撤销某用户的全部有效会话，返回受影响行数。

        ``except_session_id`` 用于「改密后保留当前设备登录」的场景；
        禁用用户 / 强制下线时传 None（全部踢掉）。
        """
        stmt = update(UserSession).where(
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
        )
        if except_session_id is not None:
            stmt = stmt.where(UserSession.id != except_session_id)
        result = await self._session.execute(stmt.values(revoked_at=when))
        await self._session.commit()
        return int(result.rowcount or 0)

    async def list_active_for_user(self, user_id: int) -> list[UserSession]:
        """某用户当前有效会话（未撤销 + 未过期），按登录时间倒序。"""
        now = utcnow()
        stmt = (
            select(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now,
            )
            .order_by(UserSession.created_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def delete_expired(self, before: datetime) -> int:
        """物理删除已过期且已撤销的会话（清理任务用），返回删除行数。"""
        stmt = delete(UserSession).where(
            UserSession.expires_at < before,
            UserSession.revoked_at.is_not(None),
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return int(result.rowcount or 0)


__all__ = ["DuplicateEmailError", "SessionRepository", "UserRepository"]
