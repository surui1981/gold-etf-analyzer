"""AI chat API schemas（V0.97.0）"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.ai_chat import DEFAULT_MODEL, ROLE_ASSISTANT
from app.utils.logger import get_logger
from app.utils.protocol_strip import strip_protocol_markup

logger = get_logger(__name__)

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

    title: str | None = None
    is_archived: bool | None = None


# ────────────── Message ──────────────


class AIMessageOut(BaseModel):
    """单条消息（含 tool 消息）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    user_id: int
    role: str  # user / assistant / tool
    content: str
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_call_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None
    error_code: str | None = None
    created_at: datetime

    @field_validator("tool_input", mode="before")
    @classmethod
    def _parse_tool_input(cls, v: Any) -> dict[str, Any] | None:
        """反序列化 tool_input：dict 直接透传 / str JSON 解析 / None / 损坏 → None。

        ⚠️ **V0.120.2 修的真缺陷（本文件的存在理由）**
        落库格式（``repositories/ai_chat.py:172``）是 ``json.dumps(...)`` **字符串**，
        而本 schema 对外契约是 **dict**（前端按 ``input.from`` / ``input.days`` 取值，
        见 ``static/ask.js::summarizeInput``）。
        ``from_attributes=True`` 会把 ORM 的**字符串**属性直接喂给 ``dict[str, Any]``
        ⇒ Pydantic ValidationError ⇒ **整个对话 500**
        （前端只看到「加载对话失败：Internal Server Error」）。

        **落库侧是对的，错的是接口边界没解码** —— 与 ``SnapshotOut.macro_detail``
        完全同类（那列也是 Text JSON、schema 也是 dict），修法照抄它。

        **为什么此前 2007 条测试全绿**：mock LLM 的 tool_use 入参是**空 dict ``{}``**
        ⇒ ``repositories`` 的 ``if tool_input else None`` 把它判成 falsy ⇒ 落库 NULL
        ⇒ 校验通过。真实 LLM 传的是**非空**入参
        （实测 ``get_scoring_summary({"from": ..., "to": ...})``）⇒ 存成 JSON 字符串
        ⇒ 才炸。⇒ 空入参把真缺陷藏住了（见 ``stub-hides-replaced-caller``）。

        损坏 JSON（脏数据）按同一纪律处理：log warning + 置 None ——
        **一个坏字段不该让整个对话打不开**（数据不足 ≠ 中性，不兜底为 ``{}``）。
        """
        if v is None:
            return None
        if isinstance(v, dict):
            return v
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, dict):
                    return parsed
                preview = v[:200] + ("…" if len(v) > 200 else "")
                logger.warning(
                    "AIMessageOut.tool_input 顶层非 dict（%s）→ 置 None（preview=%r）",
                    type(parsed).__name__,
                    preview,
                )
                return None
            except (json.JSONDecodeError, ValueError):
                preview = v[:200] + ("…" if len(v) > 200 else "")
                logger.warning(
                    "AIMessageOut.tool_input JSON 反序列化失败 → 置 None（preview=%r）",
                    preview,
                )
                return None
        logger.warning(
            "AIMessageOut.tool_input 收到非预期类型 %s → 置 None",
            type(v).__name__,
        )
        return None

    @model_validator(mode="after")
    def _strip_protocol_markup(self) -> AIMessageOut:
        """清洗 assistant 正文里的 miniMax 原生 tool-call 协议残留（V0.120.3）。

        ⚠️ **只清洗 assistant**：tool 消息正文**本身就是** JSON（含 ``name`` 键），
        清洗规则 3 会把工具数据整段毁掉。

        为什么要读时清洗而不是改库：污染行是上游会话畸形时落下的（生产库实测 8 条），
        读时清洗对历史行与新行**同时生效**，不用写生产库、不用迁移。
        原始数据保留在库里作为证据。
        """
        if self.role == ROLE_ASSISTANT and self.content:
            cleaned = strip_protocol_markup(self.content)
            if cleaned != self.content:
                self.content = cleaned
        return self


class AIConversationDetailOut(BaseModel):
    """对话详情：对话 + 全部消息。"""

    conversation: AIConversationOut
    messages: list[AIMessageOut]


# ────────────── Send Message ──────────────


class AISendMessageIn(BaseModel):
    """发送 1 条用户消息请求体。"""

    content: str = Field(
        ..., min_length=1, max_length=8000, description="用户输入文本（自动 sanitize）"
    )


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
