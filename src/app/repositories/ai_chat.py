"""AI chat 数据访问层（V0.97.0）

2 个仓储：
- :class:`AIConversationRepository` —— 对话 CRUD + 列表 + token 累计
- :class:`AIMessageRepository` —— 消息 CRUD + 历史 50 条 + 单条查询

所有方法默认按当前用户过滤（V0.80.0 #159 隔离）；越权访问表现为「查不到」。

⚠ V0.79.0 任务 #162 教训：仓储方法**不写宽表**（本版无宽表），但 ``insert``
   / ``bump_stats`` 字段白名单要写全，未来加列时只动一处即可（不在多处
   散落）。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_chat import AIConversation, AIMessage
from app.utils.user_scope import resolve_user_id


class AIConversationRepository:
    """对话表 CRUD。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, conv_id: str, user_id: int | None = None) -> AIConversation | None:
        """按 id 取对话（user_id 隔离）。不存在或越权均返回 None。"""
        user_id = resolve_user_id(user_id)
        stmt = select(AIConversation).where(
            and_(
                AIConversation.id == conv_id,
                AIConversation.user_id == user_id,
            )
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create(
        self,
        *,
        conv_id: str,
        user_id: int,
        title: str = "",
        model: str = "claude-sonnet-4-5",
    ) -> AIConversation:
        """建新对话（id 在调用方生成）。"""
        conv = AIConversation(
            id=conv_id,
            user_id=user_id,
            title=title,
            model=model,
        )
        self._session.add(conv)
        await self._session.commit()
        return conv

    async def list_for_user(
        self,
        *,
        user_id: int | None = None,
        limit: int = 20,
        offset: int = 0,
        include_archived: bool = False,
    ) -> list[AIConversation]:
        """列某用户的对话（按 last_message_at 倒序）。

        Args:
            user_id: 不传则取当前请求上下文。
            limit: 1-100。
            offset: 分页偏移。
            include_archived: True 时含归档对话。
        """
        user_id = resolve_user_id(user_id)
        stmt = select(AIConversation).where(AIConversation.user_id == user_id)
        if not include_archived:
            stmt = stmt.where(AIConversation.is_archived.is_(False))
        stmt = stmt.order_by(desc(AIConversation.last_message_at)).limit(limit).offset(offset)
        return list((await self._session.execute(stmt)).scalars().all())

    async def update(
        self,
        conv_id: str,
        *,
        user_id: int | None = None,
        title: str | None = None,
        is_archived: bool | None = None,
    ) -> AIConversation | None:
        """更新 title / is_archived（patch 端点用）。"""
        conv = await self.get(conv_id, user_id=user_id)
        if conv is None:
            return None
        if title is not None:
            conv.title = title
        if is_archived is not None:
            conv.is_archived = is_archived
        conv.updated_at = datetime.utcnow()
        await self._session.commit()
        return conv

    async def bump_stats(
        self,
        conv_id: str,
        *,
        last_message_at: datetime,
        add_input: int = 0,
        add_output: int = 0,
        add_messages: int = 0,
    ) -> None:
        """更新 last_message_at + 累计 token + message_count（1 次 1 assistant 轮）。"""
        # 不需要 user_id —— 调用方已 check 权限
        conv = await self.get(conv_id)
        if conv is None:
            return
        conv.last_message_at = last_message_at
        conv.updated_at = last_message_at
        conv.total_input_tokens = (conv.total_input_tokens or 0) + add_input
        conv.total_output_tokens = (conv.total_output_tokens or 0) + add_output
        conv.message_count = (conv.message_count or 0) + add_messages
        await self._session.commit()

    async def count_for_user(
        self,
        *,
        user_id: int | None = None,
        include_archived: bool = False,
    ) -> int:
        """统计某用户的对话数（前端分页 / quota UI 用）。"""
        from sqlalchemy import func

        user_id = resolve_user_id(user_id)
        stmt = select(func.count(AIConversation.id)).where(AIConversation.user_id == user_id)
        if not include_archived:
            stmt = stmt.where(AIConversation.is_archived.is_(False))
        return int((await self._session.execute(stmt)).scalar() or 0)


class AIMessageRepository:
    """消息表 CRUD。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(
        self,
        *,
        msg_id: str,
        conversation_id: str,
        user_id: int,
        role: str,
        content: str = "",
        tool_name: str | None = None,
        tool_input: dict[str, Any] | None = None,
        tool_call_id: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        latency_ms: int | None = None,
    ) -> AIMessage:
        """插 1 条消息。``tool_input`` 自动 JSON 序列化。"""
        msg = AIMessage(
            id=msg_id,
            conversation_id=conversation_id,
            user_id=user_id,
            role=role,
            content=content,
            tool_name=tool_name,
            tool_input=json.dumps(tool_input, ensure_ascii=False) if tool_input else None,
            tool_call_id=tool_call_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )
        self._session.add(msg)
        await self._session.commit()
        return msg

    async def list_for_conversation(
        self,
        conv_id: str,
        *,
        user_id: int | None = None,
    ) -> list[AIMessage]:
        """列某对话的全部消息（按 created_at 升序）—— 端点 ``GET /conversations/{id}`` 用。"""
        user_id = resolve_user_id(user_id)
        # 先验证对话归属（防越权 list）
        conv = await AIConversationRepository(self._session).get(conv_id, user_id=user_id)
        if conv is None:
            return []
        stmt = (
            select(AIMessage)
            .where(AIMessage.conversation_id == conv_id)
            .order_by(AIMessage.created_at.asc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_recent(
        self,
        conv_id: str,
        *,
        limit: int = 50,
    ) -> list[AIMessage]:
        """最近 N 条消息（升序，给 LLM 拼 history 用）。

        不做 user_id 过滤（调用方已 check 对话归属）。
        """
        # 取 N 条倒序，再翻转为升序 —— 这样 N > 总数也只回全部
        stmt = (
            select(AIMessage)
            .where(AIMessage.conversation_id == conv_id)
            .order_by(desc(AIMessage.created_at))
            .limit(limit)
        )
        rows = list((await self._session.execute(stmt)).scalars().all())
        rows.reverse()
        return rows

    async def count_for_conversation(self, conv_id: str) -> int:
        """统计对话的消息数（V0.97 暂未使用，预留给 cost UI）。"""
        from sqlalchemy import func

        stmt = select(func.count(AIMessage.id)).where(AIMessage.conversation_id == conv_id)
        return int((await self._session.execute(stmt)).scalar() or 0)

    async def delete(self, msg_id: str) -> None:
        """按 id 删 1 条消息（V0.97 LLM 失败时回滚 user_msg 用）。"""
        msg = await self._session.get(AIMessage, msg_id)
        if msg is not None:
            await self._session.delete(msg)
            await self._session.commit()
