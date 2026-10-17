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
    """Anthropic Claude API 异步客户端（兼容任何 Anthropic-协议端点）。"""

    # 默认官方端点；用户可通过 base_url 覆盖为国内代理
    DEFAULT_BASE_URL = "https://api.anthropic.com"
    ANTHROPIC_VERSION = "2023-06-01"
    _RETRY_BACKOFFS: tuple[float, ...] = (2.0, 5.0, 15.0)  # 仅 429/5xx 触发

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "claude-sonnet-4-5",
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        max_tokens: int = 2048,
    ) -> None:
        if not api_key:
            raise ValueError("api_key must not be empty (configure LLM_API_KEY)")
        # 去掉尾部 /，再拼 /v1/messages
        self._base_url = base_url.rstrip("/")
        self._endpoint = f"{self._base_url}/v1/messages"
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
                        self._endpoint, json=body, headers=headers,
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

    # ────────────── V0.98 C5 流式 ──────────────

    async def ask_stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
    ):
        """V0.98 C5：流式调用，yield StreamEvent 事件。

        Anthropic SSE 协议（与官方一致，国内代理如 miniMax 走 OpenAI 风格但
        暴露 Anthropic 兼容 SSE，所以这套解析是普适的）：

        ```
        event: message_start
        data: {"type":"message_start","message":{...}}

        event: content_block_start
        data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}

        event: content_block_delta
        data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"你"}}

        event: content_block_stop
        data: {"type":"content_block_stop","index":0}

        event: message_delta
        data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},...}

        event: message_stop
        data: {"type":"message_stop"}
        ```

        Yields:
            StreamEvent 子类（按 type 标签）：MessageStart / TextDelta /
            ToolUseStart / ToolUseInputDelta / MessageDelta / MessageStop /
            Error / Ping。
        """
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": self.ANTHROPIC_VERSION,
            "content-type": "application/json",
            "accept": "text/event-stream",
        }
        body: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens if max_tokens is not None else self._max_tokens,
            "system": system,
            "messages": messages,
            "stream": True,
        }
        if tools:
            body["tools"] = tools

        # 重试用非流式入口（流式 + 重试很复杂，先简单实现；失败抛 LLMError）
        last_exc: Exception | None = None
        for attempt, backoff in enumerate((0.0,) + self._RETRY_BACKOFFS):
            if backoff:
                await asyncio.sleep(backoff)
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    async with client.stream(
                        "POST", self._endpoint, json=body, headers=headers,
                    ) as resp:
                        if resp.status_code in (429, 500, 502, 503, 504, 529):
                            await resp.aread()
                            last_exc = LLMRetryable(resp.status_code, resp.text)
                            continue
                        if 400 <= resp.status_code < 500:
                            await resp.aread()
                            raise LLMError(
                                f"client error {resp.status_code}: {resp.text[:200]}"
                            )
                        resp.raise_for_status()
                        # 进入流式 yield
                        async for ev in self._iter_sse(resp):
                            yield ev
                        return
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                continue

        raise LLMError(f"upstream exhausted: {last_exc}")

    @staticmethod
    async def _iter_sse(resp: httpx.Response):
        """从 Anthropic SSE 响应里逐事件 yield StreamEvent。"""
        current_event: str = ""
        current_data: list[str] = []
        tool_block_ids: dict[int, str] = {}  # index → tool_use_id
        async for raw_line in resp.aiter_lines():
            if not raw_line:
                # 空行 = 一个 SSE 事件结束
                if current_data:
                    data_str = "\n".join(current_data)
                    try:
                        payload = json.loads(data_str)
                    except json.JSONDecodeError:
                        current_event, current_data = "", []
                        continue
                    ev_type = payload.get("type", current_event or "unknown")
                    yielded = _parse_sse_event(ev_type, payload, tool_block_ids)
                    if yielded is not None:
                        yield yielded
                current_event, current_data = "", []
                continue
            if raw_line.startswith(":"):
                # 注释行（ping 等），跳过
                continue
            if raw_line.startswith("event:"):
                current_event = raw_line[6:].strip()
            elif raw_line.startswith("data:"):
                current_data.append(raw_line[5:].lstrip())
        # 流末尾如果还有未提交的事件，flush
        if current_data:
            try:
                payload = json.loads("\n".join(current_data))
                ev_type = payload.get("type", current_event or "unknown")
                yielded = _parse_sse_event(ev_type, payload, tool_block_ids)
                if yielded is not None:
                    yield yielded
            except json.JSONDecodeError:
                pass


def _parse_sse_event(
    ev_type: str, payload: dict[str, Any],
    tool_block_ids: dict[int, str],
):
    """把单个 SSE payload 解析成 StreamEvent。返回 None = 跳过。"""
    if ev_type == "ping":
        return StreamPing()
    if ev_type == "message_start":
        msg = payload.get("message") or {}
        usage = msg.get("usage") or {}
        return StreamMessageStart(
            input_tokens=int(usage.get("input_tokens") or 0),
            model=msg.get("model", ""),
        )
    if ev_type == "content_block_start":
        block = payload.get("content_block") or {}
        index = int(payload.get("index", 0))
        btype = block.get("type")
        if btype == "tool_use":
            tid = block.get("id", "")
            tool_block_ids[index] = tid
            return StreamToolUseStart(
                index=index, id=tid, name=block.get("name", ""),
            )
        # text block start 不显式 yield（text_delta 即可）
        return None
    if ev_type == "content_block_delta":
        delta = payload.get("delta") or {}
        dtype = delta.get("type")
        index = int(payload.get("index", 0))
        if dtype == "text_delta":
            return StreamTextDelta(index=index, text=delta.get("text", ""))
        if dtype == "input_json_delta":
            return StreamToolUseInputDelta(
                index=index,
                partial_json=delta.get("partial_json", ""),
            )
        return None
    if ev_type == "content_block_stop":
        return None  # 不显式 yield（由 message_stop 收尾）
    if ev_type == "message_delta":
        delta = payload.get("delta") or {}
        usage = payload.get("usage") or {}
        return StreamMessageDelta(
            stop_reason=delta.get("stop_reason", ""),
            output_tokens=int(usage.get("output_tokens") or 0),
        )
    if ev_type == "message_stop":
        return StreamMessageStop()
    if ev_type == "error":
        err = payload.get("error") or {}
        return StreamError(
            err_type=err.get("type", "unknown"),
            message=err.get("message", ""),
        )
    return None  # 未知事件类型


# ────────────── V0.98 C5 流式事件 dataclass ──────────────


@dataclass
class StreamEvent:
    """SSE 事件基类。"""


@dataclass
class StreamPing(StreamEvent):
    pass


@dataclass
class StreamMessageStart(StreamEvent):
    input_tokens: int = 0
    model: str = ""


@dataclass
class StreamTextDelta(StreamEvent):
    index: int = 0
    text: str = ""


@dataclass
class StreamToolUseStart(StreamEvent):
    index: int = 0
    id: str = ""
    name: str = ""


@dataclass
class StreamToolUseInputDelta(StreamEvent):
    index: int = 0
    partial_json: str = ""


@dataclass
class StreamMessageDelta(StreamEvent):
    stop_reason: str = ""
    output_tokens: int = 0


@dataclass
class StreamMessageStop(StreamEvent):
    pass


@dataclass
class StreamError(StreamEvent):
    err_type: str = ""
    message: str = ""
