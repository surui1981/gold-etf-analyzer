"""AI chat API schemas（V0.97.0）"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.ai_chat import DEFAULT_MODEL


# ────────────── Conversation ──────────────


class AIConversationOut(BaseModel):
    """单条对话（列表 / 详情头部用）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: int
    title: str
    model: str
    message_count: int
    total_input_tokens: int
    total_output_tokens: int
    is_archived: bool
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime


class AICreateConversationIn(BaseModel):
    """建对话请求体。title 缺省由 service 派生（首条 user 消息）。"""

    title: str = Field("", description="可选；缺省由首条 user 消息派生")
    model: str = Field(DEFAULT_MODEL, description="LLM 模型名")


class AIUpdateConversationIn(BaseModel):
    """改对话请求体（rename / archive / unarchive）。"""

    title: Optional[str] = None
    is_archived: Optional[bool] = None


# ────────────── Message ──────────────


class AIMessageOut(BaseModel):
    """单条消息（含 tool 消息）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    user_id: int
    role: str  # user / assistant / tool
    content: str
    tool_name: Optional[str] = None
    tool_input: Optional[dict[str, Any]] = None
    tool_call_id: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latency_ms: Optional[int] = None
    error_code: Optional[str] = None
    created_at: datetime


class AIConversationDetailOut(BaseModel):
    """对话详情：对话 + 全部消息。"""

    conversation: AIConversationOut
    messages: list[AIMessageOut]


# ────────────── Send Message ──────────────


class AISendMessageIn(BaseModel):
    """发送 1 条用户消息请求体。"""

    content: str = Field(..., min_length=1, max_length=8000,
                         description="用户输入文本（自动 sanitize）")


class AIChatTurnOut(BaseModel):
    """1 次 send 调用的完整返回：user 消息 + 所有 assistant / tool 消息。"""

    user: AIMessageOut
    responses: list[AIMessageOut] = Field(
        ...,
        description="assistant + tool 消息（按时间顺序）",
    )


# ────────────── Health (用于 /api/v1/ai/health 探活) ──────────────


class AIHealthOut(BaseModel):
    """AI 服务健康检查（不开也能用，便于前端 feature flag 判断）。"""

    enabled: bool
    model: str
    per_user_per_minute: int
    daily_token_quota: int
    tools: list[str]
