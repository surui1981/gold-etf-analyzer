"""V0.72.0 P3-b：Web Push 订阅表 push_subscriptions

Revision ID: 9e2f4a1b8c7d
Revises: 8b7b4d0ce5fb
Create Date: 2026-09-21 06:00:00.000000

迁移策略
--------
- 新建 push_subscriptions 表（id / endpoint unique / p256dh / auth / user_agent / created_at / archived_at）
- endpoint 唯一索引（同一浏览器多次订阅视为同一记录）
- archived_at 索引（查询活跃订阅 WHERE archived_at IS NULL）
- 无外键（当前单用户模型，V0.75+ 多用户加 user_id 时再扩）

回滚
----
drop table push_subscriptions 即可；不影响业务。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9e2f4a1b8c7d"
down_revision: str | Sequence[str] | None = "8b7b4d0ce5fb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "endpoint",
            sa.String(length=512),
            nullable=False,
            comment="FCM/Mozilla 推送端点 URL",
        ),
        sa.Column(
            "p256dh",
            sa.Text(),
            nullable=False,
            comment="椭圆曲线公钥（base64url）",
        ),
        sa.Column(
            "auth",
            sa.Text(),
            nullable=False,
            comment="认证密钥（base64url）",
        ),
        sa.Column(
            "user_agent",
            sa.String(length=256),
            nullable=True,
            comment="订阅时浏览器 UA，便于按设备过滤",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "archived_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="410 Gone 时设此字段；查询时 WHERE archived_at IS NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("endpoint", name="uq_push_subscriptions_endpoint"),
    )
    op.create_index(
        "ix_push_subscriptions_archived_at",
        "push_subscriptions",
        ["archived_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_push_subscriptions_archived_at", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")