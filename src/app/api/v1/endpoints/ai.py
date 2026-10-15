"""AI 智能分析 API 端点（V0.97.0 · 6 端点）

挂载在 ``/api/v1/ai`` 前缀下，依赖：
- ``PerUserRateLimitMiddleware``（per-user 限速 + 配额，仅作用于本前缀）
- ``get_current_user`` / ``require_user``（V0.80.0 user_id 隔离）
"""

from __future__ import annotations

import logging
from datetime import date as date_cls
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db_session, require_user
from app.repositories.ai_chat import AIConversationRepository, AIMessageRepository
from app.schemas.ai_chat import (
    AIChatTurnOut,
    AIConversationDetailOut,
    AIConversationOut,
    AICreateConversationIn,
    AIHealthOut,
    AIMessageOut,
    AISendMessageIn,
    AIUpdateConversationIn,
)
from app.services.ai_chat import AIChatService
from app.services.llm.claude import ClaudeClient, LLMError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])


# ────────────── DI ──────────────


def get_ai_chat_service(request: Request, session: AsyncSession = Depends(get_db_session)) -> AIChatService:
    """从 app.state 拿 LLM client / tool dispatcher（main.py 启动时挂载）。"""
    llm: ClaudeClient | None = getattr(request.app.state, "llm_client", None)
    tool_dispatcher = getattr(request.app.state, "tool_dispatcher", None)
    settings = request.app.state.settings

    if llm is None or tool_dispatcher is None:
        raise HTTPException(
            status_code=503,
            detail="AI 智能分析未启用（LLM_API_KEY 未配置）",
        )

    return AIChatService(
        conv_repo=AIConversationRepository(session),
        msg_repo=AIMessageRepository(session),
        llm=llm,
        tool_dispatcher=tool_dispatcher,
        user_message_max_chars=settings.llm_user_message_max_chars,
        max_tool_rounds=settings.llm_max_tool_rounds,
    )


# ────────────── 6 端点 ──────────────


@router.get("/health", response_model=AIHealthOut, summary="AI 服务探活")
async def ai_health(request: Request) -> AIHealthOut:
    """前端 feature flag 用：返回 enabled + model + 限速配置 + tool 列表。"""
    settings = request.app.state.settings
    llm = getattr(request.app.state, "llm_client", None)
    enabled = bool(settings.llm_api_key and llm is not None)
    return AIHealthOut(
        enabled=enabled,
        model=settings.llm_model,
        per_user_per_minute=settings.llm_per_user_per_minute,
        daily_token_quota=settings.llm_daily_token_quota,
        tools=[
            "get_market_overview", "get_scoring_summary",
            "get_user_portfolio", "get_warning_summary",
            "get_etf_recent_flows",
        ],
    )


@router.post(
    "/conversations", response_model=AIConversationOut,
    status_code=201, summary="建新对话",
)
async def create_conversation(
    body: AICreateConversationIn,
    user=Depends(require_user),
    svc: AIChatService = Depends(get_ai_chat_service),
) -> AIConversationOut:
    conv = await svc.create_conversation(
        user_id=user.id, title=body.title, model=body.model,
    )
    return AIConversationOut.model_validate(conv)


@router.get(
    "/conversations", response_model=list[AIConversationOut],
    summary="列对话（按 last_message_at 倒序）",
)
async def list_conversations(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    include_archived: bool = Query(False),
    user=Depends(require_user),
    svc: AIChatService = Depends(get_ai_chat_service),
) -> list[AIConversationOut]:
    rows = await svc.list_conversations(
        user_id=user.id, limit=limit, offset=offset,
        include_archived=include_archived,
    )
    return [AIConversationOut.model_validate(r) for r in rows]


@router.get(
    "/conversations/{conv_id}", response_model=AIConversationDetailOut,
    summary="取单对话 + 全部消息",
)
async def get_conversation(
    conv_id: str,
    user=Depends(require_user),
    svc: AIChatService = Depends(get_ai_chat_service),
) -> AIConversationDetailOut:
    detail = await svc.get_conversation_detail(conv_id=conv_id, user_id=user.id)
    if detail is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    conv, msgs = detail
    return AIConversationDetailOut(
        conversation=AIConversationOut.model_validate(conv),
        messages=[AIMessageOut.model_validate(m) for m in msgs],
    )


@router.patch(
    "/conversations/{conv_id}", response_model=AIConversationOut,
    summary="改对话（rename / archive / unarchive）",
)
async def update_conversation(
    conv_id: str,
    body: AIUpdateConversationIn,
    user=Depends(require_user),
    svc: AIChatService = Depends(get_ai_chat_service),
) -> AIConversationOut:
    conv = await svc.update_conversation(
        conv_id=conv_id, user_id=user.id,
        title=body.title, is_archived=body.is_archived,
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return AIConversationOut.model_validate(conv)


@router.delete(
    "/conversations/{conv_id}", status_code=204,
    summary="归档对话（软删除，is_archived=True）",
)
async def archive_conversation(
    conv_id: str,
    user=Depends(require_user),
    svc: AIChatService = Depends(get_ai_chat_service),
) -> None:
    conv = await svc.update_conversation(
        conv_id=conv_id, user_id=user.id, is_archived=True,
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")


@router.post(
    "/conversations/{conv_id}/messages", response_model=AIChatTurnOut,
    summary="发送 1 条用户消息（同步返回 1 assistant + 可能多 tool 轮）",
)
async def send_message(
    conv_id: str,
    body: AISendMessageIn,
    user=Depends(require_user),
    svc: AIChatService = Depends(get_ai_chat_service),
) -> AIChatTurnOut:
    """1 user message → 1-N assistant（含 tool 轮）+ 任意 tool 消息。"""
    try:
        user_msg, responses = await svc.send_message(
            conversation_id=conv_id, user_id=user.id, user_text=body.content,
        )
    except ValueError as exc:
        # 对话不存在 / 内容空
        msg = str(exc)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg) from exc
        raise HTTPException(status_code=400, detail=msg) from exc
    except LLMError as exc:
        logger.warning("LLM error in send_message: %s", exc)
        raise HTTPException(
            status_code=503, detail=f"模型服务异常：{str(exc)[:200]}",
        ) from exc

    return AIChatTurnOut(
        user=AIMessageOut.model_validate(user_msg),
        responses=[AIMessageOut.model_validate(m) for m in responses],
    )
