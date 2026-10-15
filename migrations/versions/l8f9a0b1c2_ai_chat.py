"""AI 智能分析 chat 表（V0.97.0 · 多轮对话 + 工具只读）

Revision ID: l8f9a0b1c2
Revises: k7e8f9a0b1c2
Create Date: 2026-10-15 16:00:00.000000

迁移背景
----------
V0.96.0 之前所有业务页只能展示**预计算指标**（trend / portfolio / news / review /
scoring / data-health 9 页），用户**无法自然语言提问**「为什么今天评分低了 /
现在适合加仓吗」。本版新增 AI 智能分析页（/ask），用户与 Claude 模型多轮对话，
LLM 通过只读 tool 调项目数据（market / scoring / portfolio / warning /
etf_flows），对话按时间持久化便于回看。

迁移策略
--------
- 2 张新表，**完全不碰**既有表（V0.79.0 #162 纪律：仓储白名单同步即可，零数据迁移）
- ``ai_conversations`` 1 行 = 1 个对话：``id`` 用 String(36) uuid4（生成在应用层，
  避免 SQLite autoincrement 与 uuid 混用的索引问题）
- ``ai_messages`` 1 行 = 1 条 user/assistant/tool 消息；``conversation_id`` ON DELETE
  CASCADE 保证删对话级联清消息；``user_id`` 冗余存（V0.80.0 #159 隔离加速 query）
- 索引：
  - ``ix_ai_conv_user_lastmsg`` (user_id, last_message_at DESC) —— 列表页主索引
  - ``ix_ai_conv_user_archived`` (user_id, is_archived) —— 归档过滤
  - ``ix_ai_msg_conv_created`` (conversation_id, created_at) —— 单对话历史
  - ``ix_ai_msg_user_created`` (user_id, created_at) —— 跨对话审计
- 数值列（``message_count`` / token 计数）允许 0 默认（V0.78.0 NULL 纪律的应用
  形式：「无 token 是合法状态」≠「未知 token」，用 0 兜底；其他 nullable 字段
  ``tool_*`` / ``error_code`` / ``latency_ms`` 仍遵循 NULL 纪律）

⚠ V0.79.0 任务 #162 教训：本版**新增**表，无既有数据，不需要 backfill 仓储白名单
   同步（仓储类全新建）。但 ``AIMessageRepository.insert`` / ``list_recent`` 字段
   白名单要写全，避免后续加列时漏路径（与 ``ScoringWideRepository.upsert`` 同
   陷阱）。
⚠ V0.80.0 #159 教训：所有 query 默认 ``user_id`` 过滤，测试 1 例专门验证
   跨用户访问「查不到」（不抛 403，避免泄露存在性）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "l8f9a0b1c2"
down_revision: str | Sequence[str] | None = "k7e8f9a0b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """建 ai_conversations + ai_messages 两表 + 4 索引。"""
    op.create_table(
        "ai_conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
            comment="V0.80.0 数据隔离：对话归属用户",
        ),
        sa.Column(
            "title",
            sa.String(120),
            nullable=False,
            server_default="",
            comment="对话标题（首条 user 消息自动派生 ≤ 24 字）",
        ),
        sa.Column(
            "model",
            sa.String(64),
            nullable=False,
            server_default="claude-sonnet-4-5",
            comment="LLM 模型名（claude-sonnet-4-5 / claude-opus-4-1 ...）",
        ),
        sa.Column(
            "message_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="消息数（user + assistant + tool，含 tool）",
        ),
        sa.Column(
            "total_input_tokens",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="累计 input tokens（用于 cost cap）",
        ),
        sa.Column(
            "total_output_tokens",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="累计 output tokens",
        ),
        sa.Column(
            "is_archived",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="软删除：归档后默认列表不显示",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_message_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            comment="最后一条消息时间（列表页排序键）",
        ),
    )
    op.create_index(
        "ix_ai_conv_user_lastmsg",
        "ai_conversations",
        ["user_id", sa.text("last_message_at DESC")],
    )
    op.create_index(
        "ix_ai_conv_user_archived",
        "ai_conversations",
        ["user_id", "is_archived"],
    )

    op.create_table(
        "ai_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("ai_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            nullable=False,
            comment="V0.80.0 #159 冗余存：跨用户审计加速",
        ),
        sa.Column(
            "role",
            sa.String(16),
            nullable=False,
            comment='user / assistant / tool（tool = assistant tool_use 的执行结果）',
        ),
        sa.Column(
            "content",
            sa.Text(),
            nullable=False,
            server_default="",
            comment="消息正文（user 文本 / assistant 文本 / tool JSON）",
        ),
        sa.Column(
            "tool_name",
            sa.String(64),
            nullable=True,
            comment="tool_use 时填 tool 名（get_market_overview ...）",
        ),
        sa.Column(
            "tool_input",
            sa.Text(),
            nullable=True,
            comment="tool_use 的入参 JSON 字符串",
        ),
        sa.Column(
            "tool_call_id",
            sa.String(64),
            nullable=True,
            comment="tool 消息对应 assistant tool_use 的 id",
        ),
        sa.Column(
            "input_tokens",
            sa.Integer(),
            nullable=True,
            comment="assistant 消息时填；user/tool 消息为 NULL",
        ),
        sa.Column(
            "output_tokens",
            sa.Integer(),
            nullable=True,
            comment="assistant 消息时填",
        ),
        sa.Column(
            "latency_ms",
            sa.Integer(),
            nullable=True,
            comment="assistant 消息时填（LLM 响应耗时，调试用）",
        ),
        sa.Column(
            "error_code",
            sa.String(32),
            nullable=True,
            comment="失败标记（429 / 500 / timeout）；失败时**不入库**故当前保留预留",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_ai_msg_conv_created",
        "ai_messages",
        ["conversation_id", "created_at"],
    )
    op.create_index(
        "ix_ai_msg_user_created",
        "ai_messages",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    """回滚：先 ai_messages（外键依赖），再 ai_conversations。"""
    op.drop_index("ix_ai_msg_user_created", table_name="ai_messages")
    op.drop_index("ix_ai_msg_conv_created", table_name="ai_messages")
    op.drop_table("ai_messages")
    op.drop_index("ix_ai_conv_user_archived", table_name="ai_conversations")
    op.drop_index("ix_ai_conv_user_lastmsg", table_name="ai_conversations")
    op.drop_table("ai_conversations")
