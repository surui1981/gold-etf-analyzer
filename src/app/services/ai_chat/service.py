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

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from app.models.ai_chat import (
    DEFAULT_MODEL,
    ROLE_ASSISTANT,
    ROLE_TOOL,
    ROLE_USER,
    AIConversation,
    AIMessage,
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
            conv_id=str(uuid.uuid4()),
            user_id=user_id,
            title=title,
            model=model,
        )

    async def list_conversations(
        self,
        *,
        user_id: int,
        limit: int = 20,
        offset: int = 0,
        include_archived: bool = False,
    ) -> list[AIConversation]:
        return await self._conv.list_for_user(
            user_id=user_id,
            limit=limit,
            offset=offset,
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
        self,
        *,
        conv_id: str,
        user_id: int,
        title: str | None = None,
        is_archived: bool | None = None,
    ) -> AIConversation | None:
        return await self._conv.update(
            conv_id,
            user_id=user_id,
            title=title,
            is_archived=is_archived,
        )

    # ────────────── 核心：发送消息 ──────────────

    def _final_answer_prompt(self, *, user_msg: AIMessage, all_msgs: list[AIMessage]) -> str:
        """构造「安全网」提示：把本轮已有内容压成**一段纯文本**。

        ⚠️ **V0.120.3**：线上「正文为空」有两种成因 ——
        (a) 工具连续报错 ⇒ 模型反复重试同一个工具 ⇒ ``max_tool_rounds`` 耗尽；
        (b) 模型只发 ``tool_use`` 不发正文。
        两种情况用户都只看到**空白回复**（不是格式问题）。

        ⚠️ 为什么不复用 ``messages`` 列表：那里面是 assistant(tool_use) /
        user(tool_result) 块，miniMax 代理对 tool_use_id 配对极敏感（2013）。
        **纯文本 = 零协议风险**。

        Args:
            user_msg: 本轮的用户消息
            all_msgs: 本轮已产生的消息（assistant / tool）

        Returns:
            一段纯文本提示（作为单条 user 消息发给模型）
        """
        parts: list[str] = [f"用户问题：\n{user_msg.content}"]
        for m in all_msgs[1:]:
            if m.role == ROLE_ASSISTANT and m.content:
                parts.append(f"（此前分析）\n{m.content}")
            elif m.role == ROLE_TOOL:
                parts.append(f"（工具 {m.tool_name or '?'} 的返回）\n{m.content}")
        parts.append(
            "请基于以上信息直接给出最终结论（不要再调用任何工具）。"
            "若数据缺失就明说缺什么，不要编造数字。"
        )
        return "\n\n".join(parts)

    async def send_message(
        self,
        *,
        conversation_id: str,
        user_id: int,
        user_text: str,
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
            msg_id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            user_id=user_id,
            role=ROLE_USER,
            content=sanitized,
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
        # 本轮是否出现过正文（用来判断要不要走「安全网」补一段结论）
        has_text = False

        for round_idx in range(self._max_tool_rounds):
            try:
                response = await self._llm.ask(
                    system=system,
                    messages=messages,
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
                        conversation_id,
                        round_idx,
                    )
                    # L1：内联 tool_result + 重试（不带 tools）
                    inlined = _inline_tool_results_as_text(messages)
                    try:
                        response = await self._llm.ask(
                            system=system,
                            messages=inlined,
                            tools=None,
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
            has_text = has_text or bool(response.text)

            # 持久化 assistant 消息
            tool_input_json: dict[str, Any] | None = None
            if response.tool_calls:
                # 单 assistant 消息只存「第一个 tool_use」（简化展示；多 tool 走
                # 后续 tool 消息的 tool_call_id 关联）
                tool_input_json = response.tool_calls[0].input
            asst_msg = await self._msg.insert(
                msg_id=str(uuid.uuid4()),
                conversation_id=conversation_id,
                user_id=user_id,
                role=ROLE_ASSISTANT,
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
            #
            # ⚠️ **V0.120.3 修的真缺陷**（用户报「对话给出的格式 不方便阅读」的根因）
            # Anthropic 协议要求 ``assistant(tool_use) → user(tool_result)`` **配对**。
            # 原实现只 append 了 ``user(tool_result)``，**assistant 的 tool_use 回合
            # 从未回传** ⇒ 上游收到畸形会话（连续两条 user 消息，且 tool_result
            # 找不到配对的 tool_use）⇒ miniMax 退化成本地 tool-call 协议、当正文吐出，
            # 用户看到的是 `]<]minimax[>[<tool_call> {"name":…}` 这类垃圾。
            # 实测 A/B（直连上游）：缺 assistant 回合 ⇒ HTTP 400；
            # 补上 ⇒ HTTP 200 + 完整 Markdown 答案。
            assistant_blocks: list[dict[str, Any]] = []
            if response.text:
                assistant_blocks.append({"type": "text", "text": response.text})
            for tc in response.tool_calls:
                assistant_blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.input or {},
                    }
                )
            tool_result_blocks: list[dict[str, Any]] = []
            for tc in response.tool_calls:
                result = await self._tools.execute(tc, user_id=user_id)
                # 持久化 tool 消息
                tool_msg = await self._msg.insert(
                    msg_id=str(uuid.uuid4()),
                    conversation_id=conversation_id,
                    user_id=user_id,
                    role=ROLE_TOOL,
                    content=result.content,
                    tool_name=result.name,
                    tool_call_id=tc.id,
                )
                all_msgs.append(tool_msg)
                tool_result_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": result.content,
                    }
                )
            # 拼回 Claude 格式 messages：assistant(tool_use) → user(tool_result)
            # ⚠️ 同一回合的多个 tool_result 必须放在**同一条** user 消息里 ——
            #   拆成多条 user 消息同样是畸形会话。
            messages.append({"role": "assistant", "content": assistant_blocks})
            messages.append({"role": "user", "content": tool_result_blocks})
            # 续下一轮
        else:
            # 走完 max_tool_rounds 仍没拿到 end_turn —— 强结（防失控）
            logger.warning(
                "conversation %s hit max_tool_rounds=%d without end_turn",
                conversation_id,
                self._max_tool_rounds,
            )

        # 4.5 安全网：整轮**没有正文** ⇒ 用户看到空白回复（V0.120.3 实测线上成因）
        #   补一次「不带工具」的调用，让模型基于已有工具数据必须给出结论。
        #   失败不抛 —— 宁可正文为空也不要整轮 500。
        if not has_text:
            logger.warning("conversation %s produced no text; final-answer retry", conversation_id)
            try:
                final = await self._llm.ask(
                    system=system,
                    messages=[
                        {
                            "role": "user",
                            "content": self._final_answer_prompt(
                                user_msg=user_msg, all_msgs=all_msgs
                            ),
                        }
                    ],
                    tools=None,
                )
            except LLMError as exc:
                logger.warning("final-answer retry failed for conv=%s: %s", conversation_id, exc)
            else:
                if final.text:
                    total_in_tok += final.input_tokens
                    total_out_tok += final.output_tokens
                    asst_msg = await self._msg.insert(
                        msg_id=str(uuid.uuid4()),
                        conversation_id=conversation_id,
                        user_id=user_id,
                        role=ROLE_ASSISTANT,
                        content=final.text,
                        input_tokens=final.input_tokens,
                        output_tokens=final.output_tokens,
                        latency_ms=int((datetime.utcnow() - start_ts).total_seconds() * 1000),
                    )
                    all_msgs.append(asst_msg)

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
                    conversation_id,
                    user_id=user_id,
                    title=derived,
                )

        return user_msg, all_msgs[1:]  # 跳过 user_msg，只返 assistant+tool

    # ────────────── V0.98 C5 流式 send_message_stream ──────────────

    async def send_message_stream(
        self,
        *,
        conversation_id: str,
        user_id: int,
        user_text: str,
    ):
        """V0.98 C5：流式发送，yield 形如 ``{"event": ..., ...}`` 的 dict。

        与 :meth:`send_message` 行为一致（多轮 + 3 级降级），但 yield 增量
        事件供 SSE endpoint 透传给前端。

        Event types (yield dict shape):
          - ``{"event": "user_saved", "msg_id": "..."}``
          - ``{"event": "text_delta", "delta": "..."}``  (循环)
          - ``{"event": "tool_call_start", "id": "...", "name": "..."}``
          - ``{"event": "tool_call_input_delta", "id": "...", "delta": "..."}``
          - ``{"event": "tool_result", "id": "...", "name": "...", "content": "..."}``
          - ``{"event": "message_stop", "usage": {...}}``
          - ``{"event": "error", "code": "...", "msg": "..."}``  (终态)
        """
        if not user_text or not user_text.strip():
            yield {"event": "error", "code": "empty_input", "msg": "user_text is empty"}
            return

        conv = await self._conv.get(conversation_id, user_id=user_id)
        if conv is None:
            yield {
                "event": "error",
                "code": "conv_not_found",
                "msg": "conversation not found or access denied",
            }
            return

        # 1. 持久化 user message
        sanitized = _sanitize_user_text(user_text, self._user_msg_max)
        user_msg = await self._msg.insert(
            msg_id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            user_id=user_id,
            role=ROLE_USER,
            content=sanitized,
        )
        yield {"event": "user_saved", "msg_id": user_msg.id}

        # 2. 拼历史（最近 50 条）
        history = await self._msg.list_recent(conversation_id, limit=50)
        messages = _to_claude_messages(history)
        system = _build_system_prompt(conv.model)

        # 3. 多轮流式循环（含 3 级降级）
        all_msgs: list[AIMessage] = [user_msg]
        total_in_tok = 0
        total_out_tok = 0
        start_ts = datetime.utcnow()
        final_text = ""
        final_tool_calls: list[dict[str, Any]] = []
        # 本轮是否出现过正文（用来判断要不要走「安全网」补一段结论）
        has_text = False
        # 本轮是否已经因上游错误而中止（中止了就不该再调一次 —— 白等一轮）
        llm_failed = False

        for round_idx in range(self._max_tool_rounds):
            tools = self._tools.schemas()
            inlined = False
            fresh_only = False

            try:
                events = self._llm.ask_stream(
                    system=system,
                    messages=messages,
                    tools=tools,
                )
                async for ev in events:
                    if hasattr(ev, "text"):  # StreamTextDelta
                        final_text += ev.text
                        yield {"event": "text_delta", "delta": ev.text}
                    elif ev.__class__.__name__ == "StreamToolUseStart":
                        final_tool_calls.append({"id": ev.id, "name": ev.name, "input_json": ""})
                        yield {"event": "tool_call_start", "id": ev.id, "name": ev.name}
                    elif ev.__class__.__name__ == "StreamToolUseInputDelta":
                        # 累积 partial_json 到对应 tool_use
                        for tc in final_tool_calls:
                            if not tc.get("input_json_done") and tc.get("id"):
                                tc["input_json"] = (tc.get("input_json") or "") + ev.partial_json
                                yield {
                                    "event": "tool_call_input_delta",
                                    "id": tc["id"],
                                    "delta": ev.partial_json,
                                }
                                break
                    elif ev.__class__.__name__ == "StreamMessageStart":
                        total_in_tok = ev.input_tokens
                    elif ev.__class__.__name__ == "StreamMessageDelta":
                        total_out_tok = ev.output_tokens
                    elif ev.__class__.__name__ == "StreamError":
                        raise LLMError(f"sse error: type={ev.err_type} msg={ev.message[:200]}")
                # 流正常结束
            except LLMError as exc:
                # V0.97.2 hotfix：3 级降级
                if (
                    _is_tool_result_id_mismatch(exc)
                    and _has_tool_result_block(messages)
                    and not inlined
                    and not fresh_only
                ):
                    logger.warning(
                        "stream: tool_result id mismatch (proxy 2013); L1 inlined retry for conv=%s round=%d",
                        conversation_id,
                        round_idx,
                    )
                    inlined = True
                    inlined_messages = _inline_tool_results_as_text(messages)
                    try:
                        events = self._llm.ask_stream(
                            system=system,
                            messages=inlined_messages,
                            tools=None,
                        )
                        async for ev in events:
                            if hasattr(ev, "text"):
                                final_text += ev.text
                                yield {"event": "text_delta", "delta": ev.text}
                            elif ev.__class__.__name__ == "StreamMessageStart":
                                total_in_tok = ev.input_tokens
                            elif ev.__class__.__name__ == "StreamMessageDelta":
                                total_out_tok = ev.output_tokens
                            elif ev.__class__.__name__ == "StreamError":
                                raise LLMError(
                                    f"sse L1 error: type={ev.err_type} msg={ev.message[:200]}"
                                )
                    except LLMError as exc2:
                        if not _is_tool_result_id_mismatch(exc2):
                            yield {"event": "error", "code": "llm_failed", "msg": str(exc2)[:200]}
                            llm_failed = True
                            break
                        # L3：只发 user 原问题
                        logger.warning(
                            "stream: L1 also 2013; L3 fresh-only for conv=%s",
                            conversation_id,
                        )
                        fresh_only = True
                        try:
                            events = self._llm.ask_stream(
                                system=system,
                                messages=[{"role": "user", "content": user_msg.content}],
                                tools=None,
                            )
                            async for ev in events:
                                if hasattr(ev, "text"):
                                    final_text += ev.text
                                    yield {"event": "text_delta", "delta": ev.text}
                                elif ev.__class__.__name__ == "StreamMessageStart":
                                    total_in_tok = ev.input_tokens
                                elif ev.__class__.__name__ == "StreamMessageDelta":
                                    total_out_tok = ev.output_tokens
                                elif ev.__class__.__name__ == "StreamError":
                                    raise LLMError(
                                        f"sse L3 error: type={ev.err_type} msg={ev.message[:200]}"
                                    )
                        except LLMError as exc3:
                            yield {"event": "error", "code": "llm_failed", "msg": str(exc3)[:200]}
                            llm_failed = True
                            break
                else:
                    yield {"event": "error", "code": "llm_failed", "msg": str(exc)[:200]}
                    llm_failed = True
                    break

            # 累积 tool_use 的最终 input（拼 partial_json）
            for tc in final_tool_calls:
                if not tc.get("input_json_done"):
                    tc["input_json_done"] = True
                    try:
                        tc["input"] = json.loads(tc.get("input_json") or "{}")
                    except (json.JSONDecodeError, ValueError):
                        tc["input"] = {}

            # 持久化 assistant 消息
            asst_msg = await self._msg.insert(
                msg_id=str(uuid.uuid4()),
                conversation_id=conversation_id,
                user_id=user_id,
                role=ROLE_ASSISTANT,
                content=final_text,
                tool_name=final_tool_calls[0]["name"] if final_tool_calls else None,
                tool_input=final_tool_calls[0].get("input") if final_tool_calls else None,
                input_tokens=total_in_tok,
                output_tokens=total_out_tok,
                latency_ms=int((datetime.utcnow() - start_ts).total_seconds() * 1000),
            )
            all_msgs.append(asst_msg)

            has_text = has_text or bool(final_text)

            if not final_tool_calls:
                # 终态：end_turn，无 tool
                break

            # 有 tool_use：执行 + 拼回 messages
            #
            # ⚠️ **V0.120.3**：与同步路径同一个真缺陷 —— 必须先回传 **assistant 的
            # tool_use 回合**，否则上游拿到畸形会话（见 ``send_message`` 里的详述）。
            assistant_blocks: list[dict[str, Any]] = []
            if final_text:
                assistant_blocks.append({"type": "text", "text": final_text})
            for tc in final_tool_calls:
                assistant_blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["name"],
                        "input": tc.get("input") or {},
                    }
                )
            tool_result_blocks: list[dict[str, Any]] = []
            for tc in final_tool_calls:
                # 构造 ToolCall 给 tool dispatcher
                from app.services.llm.tools import ToolCall

                tool_call = ToolCall(id=tc["id"], name=tc["name"], input=tc.get("input", {}))
                result = await self._tools.execute(tool_call, user_id=user_id)
                # 持久化 tool 消息
                tool_msg = await self._msg.insert(
                    msg_id=str(uuid.uuid4()),
                    conversation_id=conversation_id,
                    user_id=user_id,
                    role=ROLE_TOOL,
                    content=result.content,
                    tool_name=result.name,
                    tool_call_id=tc["id"],
                )
                all_msgs.append(tool_msg)
                yield {
                    "event": "tool_result",
                    "id": tc["id"],
                    "name": result.name,
                    "content": result.content[:200],  # 流式预览截断
                }
                tool_result_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tc["id"],
                        "content": result.content,
                    }
                )
            # 拼回 Claude 格式 messages：assistant(tool_use) → user(tool_result)
            messages.append({"role": "assistant", "content": assistant_blocks})
            messages.append({"role": "user", "content": tool_result_blocks})

            # 重置 per-round 累加器，进入下一轮
            final_text = ""
            final_tool_calls = []
        else:
            logger.warning(
                "stream: conversation %s hit max_tool_rounds=%d without end_turn",
                conversation_id,
                self._max_tool_rounds,
            )

        # 安全网：整轮**没有正文** ⇒ 用户看到空白回复（V0.120.3 实测线上成因）
        #   补一次「不带工具」的流式调用，让模型基于已有工具数据必须给出结论。
        if not has_text and not llm_failed:
            logger.warning(
                "stream: conversation %s produced no text; final-answer retry", conversation_id
            )
            retry_text = ""
            try:
                events = self._llm.ask_stream(
                    system=system,
                    messages=[
                        {
                            "role": "user",
                            "content": self._final_answer_prompt(
                                user_msg=user_msg, all_msgs=all_msgs
                            ),
                        }
                    ],
                    tools=None,
                )
                async for ev in events:
                    if hasattr(ev, "text"):
                        retry_text += ev.text
                        yield {"event": "text_delta", "delta": ev.text}
                    elif ev.__class__.__name__ == "StreamMessageStart":
                        total_in_tok = ev.input_tokens
                    elif ev.__class__.__name__ == "StreamMessageDelta":
                        total_out_tok = ev.output_tokens
                    elif ev.__class__.__name__ == "StreamError":
                        raise LLMError(
                            f"sse final error: type={ev.err_type} msg={ev.message[:200]}"
                        )
            except LLMError as exc:
                logger.warning(
                    "stream: final-answer retry failed for conv=%s: %s", conversation_id, exc
                )
            else:
                # 落库：否则刷新页面后这段结论就丢了（前端只拿到流里的文本）
                if retry_text:
                    asst_msg = await self._msg.insert(
                        msg_id=str(uuid.uuid4()),
                        conversation_id=conversation_id,
                        user_id=user_id,
                        role=ROLE_ASSISTANT,
                        content=retry_text,
                        latency_ms=int((datetime.utcnow() - start_ts).total_seconds() * 1000),
                    )
                    all_msgs.append(asst_msg)

        # 终态 message_stop
        yield {
            "event": "message_stop",
            "usage": {"input_tokens": total_in_tok, "output_tokens": total_out_tok},
        }

        # 5. 更新会话统计
        await self._conv.bump_stats(
            conversation_id,
            last_message_at=datetime.utcnow(),
            add_input=total_in_tok,
            add_output=total_out_tok,
            add_messages=len(all_msgs),
        )

        # 6. 首次发送时如果 title 为空，自动派生
        if not conv.title and user_msg.content:
            derived = _derive_title(user_msg.content)
            if derived:
                await self._conv.update(
                    conversation_id,
                    user_id=user_id,
                    title=derived,
                )
