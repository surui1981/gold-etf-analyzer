"""AI 智能分析 ORM 模型（V0.97.0 · 多轮对话 + 工具只读）

2 张表：
- ``AIConversation``：1 行 = 1 个对话，按 ``last_message_at`` 倒序展示
- ``AIMessage``：1 行 = 1 条 user/assistant/tool 消息

设计要点
--------
- **id 用 String(36) uuid4**（不是 autoincrement int）：方便前端直接生成 id
  做乐观 UI（先建本地占位、server 返回后比对）；与既有 ``push_subscriptions.id``
  （int 自增）模式不同，本版选 uuid 是有意识的
- **user_id 冗余存 ai_messages**：V0.80.0 #159 隔离，让「跨对话历史审计」不 JOIN
  conversations 表
- **CASCADE on delete** conversation → messages：删对话级联清消息，避免悬挂
- **数值列默认 0 / 文本列默认 ""**：与 V0.78.0 NULL 纪律不冲突 —— 计数类（消息数 /
  token 累计）「为 0」是合法状态，nullable 的 ``tool_*`` / ``error_code`` / ``latency_ms``
  仍遵循 NULL 纪律（缺字段 = 未知，非 0）

⚠ V0.80.0 #159 教训：所有 query 默认 ``user_id`` 过滤（仓储层强制），越权访问
   表现为「查不到」（返回空 list / None），不用 403，避免泄露。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# 消息角色常量（与 ai_messages.role 列对齐）
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_TOOL = "tool"

# 默认模型（与 config.LLM_MODEL 默认值一致）
DEFAULT_MODEL = "claude-sonnet-4-5"

# 标题自动截断长度（首条 user 消息派生）
TITLE_MAX_CHARS = 24


class AIConversation(Base):
    """AI 对话：1 行 = 1 个对话线程。

    Attributes:
        id: uuid4 字符串（应用层生成）。
        user_id: V0.80.0 #159 数据隔离。
        title: 标题（首条 user 消息自动派生，可手动改）。
        model: LLM 模型名。
        message_count: 消息数（user + assistant + tool）。
        total_input_tokens / total_output_tokens: 累计 token（cost 监控）。
        is_archived: 软删除标记。
        created_at / updated_at: 元。
        last_message_at: 最后一条消息时间（列表页排序键）。
    """

    __tablename__ = "ai_conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        comment="V0.80.0 数据隔离：对话归属用户",
    )
    title: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        server_default="",
        comment=f"对话标题（首条 user 消息自动派生 ≤ {TITLE_MAX_CHARS} 字）",
    )
    model: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        server_default=DEFAULT_MODEL,
        comment="LLM 模型名",
    )
    message_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="消息数"
    )
    total_input_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="累计 input tokens"
    )
    total_output_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="累计 output tokens"
    )
    is_archived: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="0",
        comment="软删除：归档后默认列表不显示",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        comment="最后一条消息时间（列表页排序键）",
    )

    __table_args__ = (
        Index("ix_ai_conv_user_lastmsg", "user_id", "last_message_at"),
        Index("ix_ai_conv_user_archived", "user_id", "is_archived"),
    )


class AIMessage(Base):
    """AI 消息：1 行 = 1 条 user/assistant/tool 消息。

    Attributes:
        id: uuid4 字符串。
        conversation_id: FK -> AIConversation.id（CASCADE）。
        user_id: V0.80.0 #159 冗余存（跨对话审计加速）。
        role: user / assistant / tool。
        content: 消息正文（user 文本 / assistant 文本 / tool JSON 字符串）。
        tool_name: assistant tool_use 时填 tool 名。
        tool_input: tool_use 入参 JSON 字符串。
        tool_call_id: tool 消息对应 assistant tool_use 的 id。
        input_tokens / output_tokens: assistant 消息时填。
        latency_ms: assistant 消息时填（LLM 响应耗时）。
        error_code: 失败标记（保留预留，V0.97 失败不入库）。
        created_at: 消息时间。
    """

    __tablename__ = "ai_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ai_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="V0.80.0 #159 冗余存"
    )
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="user / assistant / tool"
    )
    content: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="", comment="消息正文"
    )
    tool_name: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="tool_use 时填 tool 名"
    )
    tool_input: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="tool_use 入参 JSON 字符串"
    )
    tool_call_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="tool 消息对应 assistant tool_use id"
    )
    input_tokens: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="assistant 消息时填"
    )
    output_tokens: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="assistant 消息时填"
    )
    latency_ms: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="assistant 消息时填（LLM 响应耗时）"
    )
    error_code: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, comment="失败标记（V0.97 失败不入库，保留预留）"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_ai_msg_conv_created", "conversation_id", "created_at"),
        Index("ix_ai_msg_user_created", "user_id", "created_at"),
    )
