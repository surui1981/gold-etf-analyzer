"""客户端埋点底座：新增 telemetry_events 表（V0.68.0）

Revision ID: b7c5d9e3f1a2
Revises: a3d9e1f7b2c4
Create Date: 2026-09-18 10:00:00.000000

迁移策略（SQLite 友好、可重复执行）
----------------------------------
新增 ``telemetry_events`` 表 —— 前端 5+ 类事件（page_view / action_click /
range_change / error_caught / palette_open / palette_query / palette_select /
nav_drawer_open / nav_drawer_select / theme_change）的 append-only 持久化。

字段说明：
- ``id`` 自增主键
- ``event_type`` 32 字符串（白名单校验）
- ``page`` 128 字符串（来源页路径，必须 ``/`` 开头）
- ``payload`` TEXT 存 JSON 文本（dict，业务负载由前端约定；服务端不解析）
- ``user_id`` / ``session_id`` / ``trace_id`` 32 字符串
  （V0.75.0 多用户上线前 user_id 固定 "1"）
- ``client_ts`` 客户端事件时间（仅参考；服务端以 ``created_at`` 为准）
- ``created_at`` 服务端入库时间（带时区）

索引策略：
- 复合索引 ``(event_type, created_at)`` 覆盖「按类型 + 时间窗口」聚合查询
- 单列索引覆盖 user_id / session_id / trace_id / created_at

注：append-only 表，``user_id`` 为 ``user_id=1`` 的预留默认
（V0.75.0 多用户时切到真实 ID）。``create_all`` 也可创建，
此处显式声明以保证 Alembic 链条完整（``upgrade head`` 一次到位）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b7c5d9e3f1a2"
down_revision: Union[str, Sequence[str], None] = "a3d9e1f7b2c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "telemetry_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False,
                  comment="事件类型（白名单校验）"),
        sa.Column("page", sa.String(length=128), nullable=False,
                  comment="来源页路径（必须 / 开头）"),
        sa.Column("payload", sa.Text(), nullable=False, server_default="",
                  comment="业务负载（JSON 文本，服务端不解析）"),
        sa.Column("user_id", sa.String(length=32), nullable=False, server_default="1",
                  comment="用户 ID（V0.75.0 前预留）"),
        sa.Column("session_id", sa.String(length=32), nullable=False, server_default="-",
                  comment="客户端会话 ID（UUIDv4 hex）"),
        sa.Column("trace_id", sa.String(length=32), nullable=True,
                  comment="服务端 trace_id 透传"),
        sa.Column("client_ts", sa.DateTime(timezone=True), nullable=True,
                  comment="客户端事件时间（仅参考）"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False,
                  comment="服务端入库时间"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_telemetry_events_event_type"), "telemetry_events", ["event_type"], unique=False
    )
    op.create_index(
        op.f("ix_telemetry_events_page"), "telemetry_events", ["page"], unique=False
    )
    op.create_index(
        op.f("ix_telemetry_events_user_id"), "telemetry_events", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_telemetry_events_session_id"), "telemetry_events", ["session_id"], unique=False
    )
    op.create_index(
        op.f("ix_telemetry_events_trace_id"), "telemetry_events", ["trace_id"], unique=False
    )
    op.create_index(
        op.f("ix_telemetry_events_created_at"), "telemetry_events", ["created_at"], unique=False
    )
    op.create_index(
        "ix_telemetry_events_type_created",
        "telemetry_events",
        ["event_type", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_telemetry_events_type_created", table_name="telemetry_events")
    op.drop_index(op.f("ix_telemetry_events_created_at"), table_name="telemetry_events")
    op.drop_index(op.f("ix_telemetry_events_trace_id"), table_name="telemetry_events")
    op.drop_index(op.f("ix_telemetry_events_session_id"), table_name="telemetry_events")
    op.drop_index(op.f("ix_telemetry_events_user_id"), table_name="telemetry_events")
    op.drop_index(op.f("ix_telemetry_events_page"), table_name="telemetry_events")
    op.drop_index(op.f("ix_telemetry_events_event_type"), table_name="telemetry_events")
    op.drop_table("telemetry_events")
