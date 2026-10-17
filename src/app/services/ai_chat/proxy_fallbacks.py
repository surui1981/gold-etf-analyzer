"""AI chat 代理 fallback（miniMax 2013 tool_result id mismatch 三级降级）。"""

from __future__ import annotations

import json
from typing import Any

from app.services.llm.claude import LLMError


def _is_tool_result_id_mismatch(exc: LLMError) -> bool:
    """检测 miniMax 代理的 tool_result id 不匹配错误。

    miniMax 代理报：
    ``client error 400: {"type":"error","error":{"type":"invalid_request_error",
    "message":"invalid params, tool result's tool id(call-...) not found (2013)"}}``

    错误码 2013 是 OpenAI 风格；此代理用 OpenAI 风格内部追踪 tool_use_id，
    但暴露 Anthropic-兼容 API → 跨 round id 匹配失败。
    """
    msg = str(exc)
    return "tool result" in msg and "not found" in msg


def _has_tool_result_block(messages: list[dict[str, Any]]) -> bool:
    """messages 列表最后一条 user 消息是否含 ``tool_result`` block。"""
    if not messages:
        return False
    last = messages[-1]
    if last.get("role") != "user":
        return False
    content = last.get("content")
    if not isinstance(content, list):
        return False
    return any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    )


def _inline_tool_results_as_text(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把最后一条 user 消息的 ``tool_result`` blocks 转成纯文本，便于代理理解。

    V0.97.1 增强：同时把上一条 assistant 消息的 ``tool_use`` 块也转成文本。
    原因：miniMax 代理在重试时仍可能因"消息里出现 tool_use 但找不到 tool_result"
    报 2013。彻底平铺 = 整条对话没有 tool_use/tool_result 块，代理无歧义。

    转换前：
        assistant: [{type: "tool_use", id: "call_abc", name: "get_market_overview", input: {}}]
        user:      [{type: "tool_result", tool_use_id: "call_abc", content: "..."}]
    转换后：
        assistant: [{type: "text", text: "[Called get_market_overview with {}]"}]
        user:      "[tool:call_abcdef returned]:\n..."

    返回新列表（不修改入参）。
    """
    if not messages:
        return messages
    new_messages = list(messages)
    last = dict(new_messages[-1])
    if last.get("role") != "user":
        return new_messages
    content = last.get("content")
    if not isinstance(content, list):
        return new_messages
    new_content: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_result":
            tool_use_id = block.get("tool_use_id", "unknown")
            inner = block.get("content", "")
            label = f"tool:{tool_use_id[:16]}"
            new_content.append(f"[{label} returned]:\n{inner}")
        elif isinstance(block, dict) and block.get("type") == "text":
            new_content.append(block.get("text", ""))
        elif isinstance(block, str):
            new_content.append(block)
    if new_content:
        last["content"] = "\n\n".join(new_content)
    new_messages[-1] = last

    # V0.97.1 增强：上一条 assistant 的 tool_use 块也转成纯文本
    if len(new_messages) >= 2:
        prev = new_messages[-2]
        if isinstance(prev, dict) and prev.get("role") == "assistant":
            new_prev = dict(prev)
            prev_content = new_prev.get("content")
            if isinstance(prev_content, list):
                new_prev_content: list[Any] = []
                for block in prev_content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        name = block.get("name", "tool")
                        inp = block.get("input", {})
                        # tool_use 块带走的语义：调用了哪个 tool + 用了什么参数
                        new_prev_content.append({
                            "type": "text",
                            "text": f"[Called {name} with {json.dumps(inp, ensure_ascii=False)}]",
                        })
                    elif isinstance(block, dict) and block.get("type") == "text":
                        new_prev_content.append(block)
                    elif isinstance(block, str):
                        new_prev_content.append({"type": "text", "text": block})
                new_prev["content"] = new_prev_content
                new_messages[-2] = new_prev
    return new_messages
