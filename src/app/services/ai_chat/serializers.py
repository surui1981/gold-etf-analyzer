"""AI chat 消息格式转换（ORM ⇄ Claude messages 格式）。"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.models.ai_chat import ROLE_ASSISTANT, ROLE_TOOL, ROLE_USER, AIMessage
from app.utils.protocol_strip import strip_protocol_markup

logger = logging.getLogger(__name__)


def _decode_tool_input(raw: Any) -> dict[str, Any]:
    """ORM 的 ``tool_input`` 列存的是 **JSON 字符串** ⇒ 这里解码成 dict。

    ⚠ 落库侧 ``repositories/ai_chat.py`` 写的是 ``json.dumps(tool_input)``（Text 列），
    而 Anthropic 协议的 ``tool_use.input`` 要的是**对象**。
    解码失败 ⇒ 退化为 ``{}``（工具确实可能无参调用，如 ``get_market_overview``）。
    """
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            logger.warning("history tool_input JSON 反序列化失败 → 用空入参")
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _to_claude_messages(msgs: list[AIMessage]) -> list[dict[str, Any]]:
    """ORM 消息列表 → Claude messages 格式。

    ⚠️ **V0.120.3 修的真缺陷**：原实现里 assistant 的 ``tool_use`` 块**从未重建**，
    tool 消息**整条被跳过** ⇒ 从第 2 轮起，模型看不到任何工具数据
    （它只看到「我调用了工具」这句话，拿不到工具返回的数字）。

    现在按「回合」重建：assistant 消息 + 其后连续的 tool 消息 = 一个回合。

    - 回合里**只有 1 个** tool 消息 ⇒ 用原生 ``tool_use`` / ``tool_result`` 块，
      且 id 严格配对（id 取自 tool 消息的 ``tool_call_id``）。
    - 回合里有**多个** tool 消息 ⇒ DB 只留了**第一个** tool_use（落库简化），
      无法 1:1 配对 ⇒ 退化成纯文本描述。
      ⚠ 宁可退化也不能发「1 个 tool_use 对 N 个 tool_result」的畸形配对 ——
      那正是把上游逼成 400/2013 的形状。
    """
    out: list[dict[str, Any]] = []
    i = 0
    n = len(msgs)
    while i < n:
        m = msgs[i]
        if m.role == ROLE_USER:
            out.append({"role": "user", "content": m.content})
            i += 1
            continue
        if m.role == ROLE_ASSISTANT:
            # 收集属于本回合的 tool 消息（assistant 之后连续的 tool 行）
            j = i + 1
            tools: list[AIMessage] = []
            while j < n and msgs[j].role == ROLE_TOOL:
                tools.append(msgs[j])
                j += 1

            blocks: list[dict[str, Any]] = []
            text = strip_protocol_markup(m.content or "")
            if text:
                blocks.append({"type": "text", "text": text})

            if len(tools) == 1 and tools[0].tool_call_id:
                # 1:1 配对 ⇒ 原生块
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tools[0].tool_call_id,
                        "name": m.tool_name or tools[0].tool_name or "",
                        "input": _decode_tool_input(m.tool_input),
                    }
                )
                out.append({"role": "assistant", "content": blocks})
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tools[0].tool_call_id,
                                "content": tools[0].content or "",
                            }
                        ],
                    }
                )
            elif tools:
                # 一回合多个 tool ⇒ 无法 1:1 配对 ⇒ 纯文本描述（始终是合法协议）
                called = ", ".join(t.tool_name or "?" for t in tools)
                blocks.append({"type": "text", "text": f"[已调用工具] {called}"})
                out.append({"role": "assistant", "content": blocks})
                results = "\n\n".join(
                    f"[工具结果 {t.tool_name or '?'}]:\n{t.content or ''}" for t in tools
                )
                out.append({"role": "user", "content": [{"type": "text", "text": results}]})
            elif blocks:
                out.append({"role": "assistant", "content": blocks})

            i = j
            continue
        # 孤立的 tool 消息（没有配对的 assistant）⇒ 跳过
        i += 1
    return out
