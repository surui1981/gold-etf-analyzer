"""Anthropic Claude API 客户端（V0.97.0）

设计要点
--------
- **httpx 直调**（不引 anthropic SDK）：与项目 pyproject 保持精简，
  复用 ``services/notify.py:ServerChanNotifier`` 的 asyncio + 退避模式
- **重试退避表** ``_RETRY_BACKOFFS = (2.0, 5.0, 15.0)``：仅对 429 / 5xx
  重试，4xx（除 429）直接抛错
- **30s 默认 timeout**：太长会让前端等不及；太短会卡复杂问题
- **失败不抛详细错**（避免 LLM 内部错误信息泄露到日志）—— 截断 200 字符
- **token 计数返回**：response.usage.input_tokens / output_tokens
  透传给 service 层做 cost cap

⚠ API key 走 :class:`app.config.Settings` 注入；模块不读 env（便于测试注入）
⚠ 不传 IP / cookie / session_id 到 system（V0.97.0 PII 防护 D15）
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

# ────────────── 异常 ──────────────


class LLMError(Exception):
    """LLM 调用最终失败（重试用尽 / 不可重试 4xx）。"""


class LLMRetryable(Exception):
    """LLM 调用可重试失败（429 / 5xx / 网络异常）。"""

    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body[:200]  # 截断
        super().__init__(f"retryable: status={status} body={body[:200]}")


# ────────────── 响应数据结构 ──────────────


@dataclass
class ToolUseBlock:
    """Claude tool_use content block。"""

    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ClaudeResponse:
    """单次 LLM 调用的解析结果。"""

    text: str = ""  # 文本回复（多个 text block 拼起来）
    tool_calls: list[ToolUseBlock] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ""  # end_turn / tool_use / max_tokens


# ────────────── Client ──────────────


class ClaudeClient:
    """Anthropic Claude API 异步客户端。"""

    ENDPOINT = "https://api.anthropic.com/v1/messages"
    ANTHROPIC_VERSION = "2023-06-01"
    _RETRY_BACKOFFS: tuple[float, ...] = (2.0, 5.0, 15.0)  # 仅 429/5xx 触发

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "claude-sonnet-4-5",
        timeout: float = 30.0,
        max_tokens: int = 2048,
    ) -> None:
        if not api_key:
            raise ValueError("api_key must not be empty (configure LLM_API_KEY)")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._max_tokens = max_tokens

    async def ask(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
    ) -> ClaudeResponse:
        """单次 LLM 调用（含重试）。

        Args:
            system: system prompt（已组装好）。
            messages: Claude messages 格式 ``[{"role": ..., "content": ...}, ...]``。
            tools: Claude tool schema 列表（与 ``ToolDispatcher.schemas()`` 配合）。
            max_tokens: 覆盖默认 max_tokens（V0.97.0 暂未使用，预留）。

        Returns:
            :class:`ClaudeResponse`。

        Raises:
            LLMError: 4xx（除 429）/ 重试用尽 / timeout。
        """
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": self.ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        body: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens if max_tokens is not None else self._max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            body["tools"] = tools

        last_exc: Exception | None = None
        for attempt, backoff in enumerate((0.0,) + self._RETRY_BACKOFFS):
            if backoff:
                await asyncio.sleep(backoff)
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(
                        self.ENDPOINT, json=body, headers=headers,
                    )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                continue
            if resp.status_code in (429, 500, 502, 503, 504, 529):
                last_exc = LLMRetryable(resp.status_code, resp.text)
                continue
            if 400 <= resp.status_code < 500:
                # 不可重试：4xx 业务错误
                raise LLMError(f"client error {resp.status_code}: {resp.text[:200]}")
            if resp.status_code >= 500:
                last_exc = LLMRetryable(resp.status_code, resp.text)
                continue
            resp.raise_for_status()
            return self._parse(resp.json())

        raise LLMError(f"upstream exhausted: {last_exc}")

    @staticmethod
    def _parse(payload: dict[str, Any]) -> ClaudeResponse:
        """解析 Claude 响应 JSON → ClaudeResponse。"""
        content = payload.get("content") or []
        text_parts: list[str] = []
        tool_calls: list[ToolUseBlock] = []
        for block in content:
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text", ""))
            elif btype == "tool_use":
                tool_calls.append(
                    ToolUseBlock(
                        id=block.get("id", ""),
                        name=block.get("name", ""),
                        input=block.get("input") or {},
                    )
                )

        usage = payload.get("usage") or {}
        return ClaudeResponse(
            text="\n".join(p for p in text_parts if p),
            tool_calls=tool_calls,
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            stop_reason=payload.get("stop_reason", ""),
        )
