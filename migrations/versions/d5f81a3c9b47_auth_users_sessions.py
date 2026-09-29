"""V0.75.0：认证骨架（users + sessions 表）

Revision ID: d5f81a3c9b47
Revises: 9e2f4a1b8c7d
Create Date: 2026-09-29 14:40:00.000000

迁移策略
--------
- 新建 ``users`` 表：``email`` 规范化小写 + **唯一索引**（防重复注册）；
  密码只存 bcrypt(cost=12) 哈希；``is_active`` 支持「禁用而不删数据」。
- 新建 ``sessions`` 表：主键为不透明随机串（cookie 值本身），
  ``user_id`` / ``expires_at`` / ``ix_sessions_user_revoked`` 三个索引覆盖
  「按 ID 取会话」「清理过期」「列出某用户在线设备」三条查询路径。
- **不建外键**：与 ``push_subscriptions`` 保持一致的取舍 —— SQLite 默认关闭
  ``PRAGMA foreign_keys``，外键形同注释却会在批量迁移时引入锁等待；
  归属关系由服务层保证（``sessions.user_id`` 只由 AuthService 写入）。
- **不改任何既有表**：本版是「认证骨架」，``user_id`` 透传到业务表
  属 V0.75.1 数据隔离，届时另一支迁移（含复合索引调整）单独处理。
- **不 seed 任何行**：单用户模式（``AUTH_ENABLED=false``）下 Users 表允许为空，
  请求以 ``LEGACY_USER_ID=1`` 运行，与 V0.74.3 行为一致。

回滚
----
``downgrade()`` 仅 drop 两张表；因本版未改动既有表，
既有的 ``accounts.user_id``（恒为 1）等历史数据**不受影响**，可安全回滚。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5f81a3c9b47"
down_revision: str | Sequence[str] | None = "9e2f4a1b8c7d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "email",
            sa.String(length=255),
            nullable=False,
            comment="登录名（小写）",
        ),
        sa.Column(
            "display_name",
            sa.String(length=64),
            nullable=False,
            server_default="",
            comment="展示名（顶栏 chip）",
        ),
        sa.Column(
            "password_hash",
            sa.String(length=255),
            nullable=False,
            comment="bcrypt 哈希，明文永不落库",
        ),
        sa.Column(
            "role",
            sa.String(length=16),
            nullable=False,
            server_default="member",
            comment="角色：owner（可管用户）/ member",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
            comment="False = 已禁用（登录被拒 + 会话作废）",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "last_login_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="最近一次登录成功时间",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # unique=True + index=True 在 SQLAlchemy 侧生成的就是「唯一索引」，名称固定 ix_users_email。
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "sessions",
        sa.Column(
            "id",
            sa.String(length=64),
            nullable=False,
            comment="不透明会话 ID（cookie 值本身）",
        ),
        sa.Column("user_id", sa.Integer(), nullable=False, comment="归属用户 users.id"),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="过期时间（朴素 UTC，绝对过期）",
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="最近一次用该会话发请求的时间",
        ),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="非空 = 已撤销（登出 / 改密 / 禁用）",
        ),
        sa.Column("user_agent", sa.String(length=256), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])
    op.create_index("ix_sessions_user_revoked", "sessions", ["user_id", "revoked_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_sessions_user_revoked", table_name="sessions")
    op.drop_index("ix_sessions_expires_at", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
