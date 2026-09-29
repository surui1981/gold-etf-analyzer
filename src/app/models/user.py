"""用户与会话 ORM 模型（V0.75.0 认证骨架）。

设计要点
--------
- **服务端会话（server-side session）**：cookie 里只放**不透明随机串**
  （``secrets.token_urlsafe(32)``，43 字符），认证事实存 ``sessions`` 表。
  好处：登出 / 改密 / 禁用用户可**即时撤销**，且能审计「在线设备」；
  代价是每请求一次本地 SQLite 查询（开销可忽略）。
  取舍详见 ``docs/ux-roadmap.md`` V0.75.0 节。
- **单用户模式（``AUTH_ENABLED=false``）零破坏**：此模式下 ``sessions`` 表为空，
  所有请求以 ``LEGACY_USER_ID`` 运行，行为与 V0.74.3 完全一致；
  两张表只是「已建好但未启用」，不参与任何既有查询。
- **时间字段一律 UTC**：SQLite 的 ``DATETIME`` 不保存时区偏移（SQLAlchemy
  sqlite 方言按字面量格式化），因此写入与比较统一使用**朴素 UTC**，
  由 :func:`utcnow` / :func:`as_naive_utc` 兜底，避免「aware 与 naive 相减」
  抛 ``TypeError``。
- **密码只存哈希**：``password_hash`` 为 bcrypt（cost=12）输出，形如
  ``$2b$12$...``；明文永不落库、永不入日志。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# 单用户模式（AUTH_ENABLED=false）下所有请求归属的「本机用户」。
# 与 V0.62.0 起 accounts.user_id 的既有取值保持一致（迁移把历史数据归入 id=1）。
LEGACY_USER_ID = 1

# 角色：目前仅区分「所有者」与「成员」。所有者可管理其他用户（V0.75.2 用户管理）。
ROLE_OWNER = "owner"
ROLE_MEMBER = "member"

# 会话有效期默认 14 天（可用 SESSION_TTL_HOURS 覆盖）。
DEFAULT_SESSION_TTL_HOURS = 24 * 14


def utcnow() -> datetime:
    """当前朴素 UTC 时间（与 SQLite 存储格式对齐）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def as_naive_utc(value: datetime | None) -> datetime | None:
    """把可能带时区的 datetime 归一为朴素 UTC；None 原样返回。

    SQLite 读回的是朴素值，但若某处写入了 aware 值（或测试直接构造），
    比较前必须归一，否则 ``aware - naive`` 会抛 ``TypeError``。
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


class User(Base):
    """应用用户。

    单用户模式下本表**可以为空**（认证关闭，无人登录）；
    多用户模式下每个家庭成员 / 合伙人一行。
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 登录名。存**规范化小写**形式（服务层负责 normalize），唯一索引保证不重复注册。
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, comment="登录名（小写）"
    )

    display_name: Mapped[str] = mapped_column(String(64), default="", comment="展示名（顶栏 chip）")

    # bcrypt(cost=12) 输出，约 60 字符；留 255 以便未来换算法（argon2 更长）
    password_hash: Mapped[str] = mapped_column(String(255), comment="bcrypt 哈希，明文永不落库")

    role: Mapped[str] = mapped_column(
        String(16), default=ROLE_MEMBER, comment="角色：owner（可管用户）/ member"
    )

    # 禁用而非删除：禁用后所有会话立即失效，数据仍保留（数据隔离下用户数据不丢）
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="False = 已禁用（登录被拒 + 会话作废）"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="注册时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最近一次登录成功时间"
    )

    def __repr__(self) -> str:  # pragma: no cover
        state = "启用" if self.is_active else "禁用"
        return f"<User {self.id} {self.email} ({self.role}/{state})>"


class UserSession(Base):
    """服务端会话。

    表名刻意取 ``sessions``（而非 ``user_sessions``）——它就是这个应用的会话表，
    没有第二套；ORM 类名带 ``User`` 前缀只为避免与 SQLAlchemy ``Session`` 重名。
    """

    __tablename__ = "sessions"

    # 主键即 cookie 里的不透明随机串（43 字符 base64url）；不存自增 id，
    # 避免暴露「会话总数」这类无意义信息。
    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="不透明会话 ID")

    user_id: Mapped[int] = mapped_column(Integer, index=True, comment="归属用户 users.id")

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, comment="过期时间（朴素 UTC，绝对过期）"
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最近一次用该会话发请求的时间"
    )

    # 撤销而非删除：登出 / 改密 / 禁用用户时置位，保留审计痕迹
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="非空 = 已撤销（登出 / 改密 / 禁用）"
    )

    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True, comment="设备标识")
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="签发时的客户端 IP")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="登录时间"
    )

    @property
    def is_live(self) -> bool:
        """是否仍可用于认证（未撤销且未过期）。"""
        if self.revoked_at is not None:
            return False
        expires = as_naive_utc(self.expires_at)
        return expires is not None and expires > utcnow()

    def __repr__(self) -> str:  # pragma: no cover
        state = "有效" if self.is_live else "失效"
        return f"<UserSession {self.id[:8]}… user={self.user_id} ({state})>"


# 过期会话清理（delete_expired）与「查用户在线会话」都走该复合索引
Index("ix_sessions_user_revoked", UserSession.user_id, UserSession.revoked_at)
