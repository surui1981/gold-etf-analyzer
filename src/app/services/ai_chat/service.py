"""AI chat 服务编排（V0.97.0 · 多轮对话 + 工具只读）

职责
----
- 对话生命周期：建 / 列 / 改 / 归档
- 消息发送：1 user message → 1-N assistant（含 tool 轮），全部入库
- 历史 50 条窗口（V0.95.1 排序约定 + V0.78.0 NULL 纪律）
- token 累计 + 配额扣减
- 失败不入库（避免污染历史）
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from app.models.ai_chat import (
    AIConversation,
    AIMessage,
    DEFAULT_MODEL,
    ROLE_ASSISTANT,
    ROLE_TOOL,
    ROLE_USER,
)
from app.repositories.ai_chat import AIConversationRepository, AIMessageRepository
from app.services.ai_chat.prompts import (
    _build_system_prompt,
    _derive_title,
    _sanitize_user_text,
)
from app.services.ai_chat.proxy_fallbacks import (
    _has_tool_result_block,
    _inline_tool_results_as_text,
    _is_tool_result_id_mismatch,
)
from app.services.ai_chat.serializers import _to_claude_messages
from app.services.llm.claude import ClaudeClient, LLMError
from app.services.llm.tools import ToolDispatcher

logger = logging.getLogger(__name__)


class AIChatService:
    """AI 对话编排服务。"""

    def __init__(
        self,
        *,
        conv_repo: AIConversationRepository,
        msg_repo: AIMessageRepository,
        llm: ClaudeClient,
        tool_dispatcher: ToolDispatcher,
        user_message_max_chars: int = 8000,
        max_tool_rounds: int = 3,
    ) -> None:
        self._conv = conv_repo
        self._msg = msg_repo
        self._llm = llm
        self._tools = tool_dispatcher
        self._user_msg_max = user_message_max_chars
        self._max_tool_rounds = max_tool_rounds

    # ────────────── 对话 CRUD ──────────────

    async def create_conversation(
        self, *, user_id: int, title: str = "", model: str = DEFAULT_MODEL
    ) -> AIConversation:
        return await self._conv.create(
            conv_id=str(uuid.uuid4()), user_id=user_id, title=title, model=model,
        )

    async def list_conversations(
        self, *, user_id: int, limit: int = 20, offset: int = 0,
        include_archived: bool = False,
    ) -> list[AIConversation]:
        return await self._conv.list_for_user(
            user_id=user_id, limit=limit, offset=offset,
            include_archived=include_archived,
        )

    async def get_conversation_detail(
        self, *, conv_id: str, user_id: int
    ) -> tuple[AIConversation, list[AIMessage]] | None:
        conv = await self._conv.get(conv_id, user_id=user_id)
        if conv is None:
            return None
        msgs = await self._msg.list_for_conversation(conv_id, user_id=user_id)
        return conv, msgs

    async def update_conversation(
        self, *, conv_id: str, user_id: int,
        title: Optional[str] = None, is_archived: Optional[bool] = None,
    ) -> AIConversation | None:
        return await self._conv.update(
            conv_id, user_id=user_id, title=title, is_archived=is_archived,
        )

    # ────────────── 核心：发送消息 ──────────────

    async def send_message(
        self, *, conversation_id: str, user_id: int, user_text: str,
    ) -> tuple[AIMessage, list[AIMessage]]:
        """1 user message → 1-N assistant（含 tool 轮）+ 任意 tool 消息。

        Returns:
            (user_msg, [assistant_msg, tool_msg?, assistant_msg?, ...])

        Raises:
            ValueError: 对话不存在 / user_text 空。
            LLMError: 模型最终失败（4xx 业务错误 / 重试用尽）。
        """
        if not user_text or not user_text.strip():
            raise ValueError("user_text is empty")

        conv = await self._conv.get(conversation_id, user_id=user_id)
        if conv is None:
            raise ValueError("conversation not found or access denied")

        # 1. 持久化 user message（先入库，保证历史完整；失败时已入库的也要 rollback 思路：
        #    V0.97 简化：失败场景统一抛 LLMError，user message 保留）
        sanitized = _sanitize_user_text(user_text, self._user_msg_max)
        user_msg = await self._msg.insert(
            msg_id=str(uuid.uuid4()), conversation_id=conversation_id,
            user_id=user_id, role=ROLE_USER, content=sanitized,
        )

        # 2. 拼历史（最近 50 条）
        history = await self._msg.list_recent(conversation_id, limit=50)
        messages = _to_claude_messages(history)

        # 3. system prompt
        system = _build_system_prompt(conv.model)

        # 4. 多轮 tool_use 循环
        all_msgs: list[AIMessage] = [user_msg]
        total_in_tok = 0
        total_out_tok = 0
        start_ts = datetime.utcnow()

        for round_idx in range(self._max_tool_rounds):
            try:
                response = await self._llm.ask(
                    system=system, messages=messages,
                    tools=self._tools.schemas(),
                )
            except LLMError as exc:
                # V0.97.0 hotfix：miniMax 代理在第 2 轮拒收 ``tool_result``，
                # 报 ``tool result's tool id(call-...) not found (2013)``。
                # 代理不跨 round 追踪 tool_use_id（OpenAI 风格 stateless 行为），
                # 但 Anthropic 协议要求 tool_result.tool_use_id 必须配对。
                # → 3 级降级链路：
                #   L1：把 tool_result 块转纯文本 + 重试（不带 tools）
                #   L2：把前一条 assistant 的 tool_use 也转纯文本（彻底平铺对话）
                #   L3：完全清空历史，只问用户原问题（代理 stateless 也能答）
                if _is_tool_result_id_mismatch(exc) and _has_tool_result_block(messages):
                    logger.warning(
                        "tool_result id mismatch (proxy 2013); falling back for conv=%s round=%d",
                        conversation_id, round_idx,
                    )
                    # L1：内联 tool_result + 重试（不带 tools）
                    inlined = _inline_tool_results_as_text(messages)
                    try:
                        response = await self._llm.ask(
                            system=system, messages=inlined, tools=None,
                        )
                    except LLMError as exc2:
                        if not _is_tool_result_id_mismatch(exc2):
                            # 非 2013 错误（4xx 业务错误等）→ 抛
                            await self._msg.delete(user_msg.id)
                            raise
                        # L2：miniMax 代理可能见到 tool_use 残留也拒；L1 已内联 tool_result
                        # 且把前一条 assistant 的 tool_use 也转成纯文本（在 _inline_ 里），
                        # 若仍 2013 = 代理对这条历史有更深问题 → L3
                        logger.warning(
                            "L1 inlined-retry also 2013; L3 fresh-only for conv=%s",
                            conversation_id,
                        )
                        # L3：只发 user 原始问题（不传历史）—— 代理 stateless 也能答
                        try:
                            response = await self._llm.ask(
                                system=system,
                                messages=[{"role": "user", "content": user_msg.content}],
                                tools=None,
                            )
                        except LLMError:
                            await self._msg.delete(user_msg.id)
                            raise
                else:
                    # 失败：user_msg 已入库但 assistant 没出 → 整个 turn 视为失败
                    # ⚠ V0.97 简化：失败时把 user_msg 删掉，避免脏历史
                    #   （V0.98 可加 retry-after 字段）
                    await self._msg.delete(user_msg.id)
                    raise

            total_in_tok += response.input_tokens
            total_out_tok += response.output_tokens

            # 持久化 assistant 消息
            tool_input_json: Optional[dict[str, Any]] = None
            if response.tool_calls:
                # 单 assistant 消息只存「第一个 tool_use」（简化展示；多 tool 走
                # 后续 tool 消息的 tool_call_id 关联）
                tool_input_json = response.tool_calls[0].input
            asst_msg = await self._msg.insert(
                msg_id=str(uuid.uuid4()), conversation_id=conversation_id,
                user_id=user_id, role=ROLE_ASSISTANT,
                content=response.text,
                tool_name=response.tool_calls[0].name if response.tool_calls else None,
                tool_input=tool_input_json,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                latency_ms=int((datetime.utcnow() - start_ts).total_seconds() * 1000),
            )
            all_msgs.append(asst_msg)

            if not response.tool_calls:
                # 终态：直接返回
                break

            # 有 tool_use：执行 + 拼回 messages
            for tc in response.tool_calls:
                result = await self._tools.execute(tc, user_id=user_id)
                # 持久化 tool 消息
                tool_msg = await self._msg.insert(
                    msg_id=str(uuid.uuid4()), conversation_id=conversation_id,
                    user_id=user_id, role=ROLE_TOOL,
                    content=result.content, tool_name=result.name,
                    tool_call_id=tc.id,
                )
                all_msgs.append(tool_msg)
                # 拼回 Claude 格式 messages
                messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": result.content,
                    }],
                })
            # 续下一轮
        else:
            # 走完 max_tool_rounds 仍没拿到 end_turn —— 强结（防失控）
            logger.warning(
                "conversation %s hit max_tool_rounds=%d without end_turn",
                conversation_id, self._max_tool_rounds,
            )

        # 5. 更新会话统计
        await self._conv.bump_stats(
            conversation_id,
            last_message_at=datetime.utcnow(),
            add_input=total_in_tok,
            add_output=total_out_tok,
            add_messages=len(all_msgs),  # 含 user + assistant + tool 全部计数
        )

        # 6. 首次发送时如果 title 为空，自动派生
        if not conv.title and user_msg.content:
            derived = _derive_title(user_msg.content)
            if derived:
                await self._conv.update(
                    conversation_id, user_id=user_id, title=derived,
                )

        return user_msg, all_msgs[1:]  # 跳过 user_msg，只返 assistant+tool
