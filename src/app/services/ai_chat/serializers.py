"""AI chat 消息格式转换（ORM ⇄ Claude messages 格式）。"""

from __future__ import annotations

from typing import Any

from app.models.ai_chat import ROLE_ASSISTANT, ROLE_TOOL, ROLE_USER, AIMessage


def _to_claude_messages(msgs: list[AIMessage]) -> list[dict[str, Any]]:
    """ORM 消息列表 → Claude messages 格式。"""
    out: list[dict[str, Any]] = []
    for m in msgs:
        if m.role == ROLE_USER:
            out.append({"role": "user", "content": m.content})
        elif m.role == ROLE_ASSISTANT:
            blocks: list[dict[str, Any]] = []
            if m.content:
                blocks.append({"type": "text", "text": m.content})
            if m.tool_name and m.tool_call_id is None:
                # 旧记录可能没存 tool_call_id；跳过 tool 重建（不影响对话）
                pass
            if blocks:
                out.append({"role": "assistant", "content": blocks})
        elif m.role == ROLE_TOOL:
            # 跳过 tool 消息：上轮 assistant tool_use 已在 asst_msg.content 里
            # 本轮 LLM 调用时我们 append 新 tool_result，新一轮 OK
            pass
    return out
