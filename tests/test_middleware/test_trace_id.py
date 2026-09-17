"""V0.67.0 trace_id 中间件测试。

覆盖：
- 自动生成 UUIDv4 hex（32 字符）
- 客户端 X-Request-ID 沿用
- 非法字符清洗（仅允许 alnum + -_.，长度 8-128）
- 响应头回写 X-Request-ID
- contextvars 隔离（HTTP 外默认 /；set/reset 手动管理）
- 非 HTTP 请求（lifespan / websocket）直通不绑 trace_id
- 与现有 /api/v1/health 端点集成（自动模式）
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.middleware.trace import (
    HEADER_NAME,
    TraceIdMiddleware,
    get_current_trace_id,
    reset_trace_id,
    set_trace_id,
)


def _hex32() -> str:
    """生成合法的客户端 trace_id（32 字符 hex）以便断言。"""
    return uuid.uuid4().hex


@pytest.mark.asyncio
async def test_v067_trace_id_auto_generated_when_missing() -> None:
    """客户端不传 X-Request-ID 时，服务端自动生成 32 字符 hex。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/v1/health")
    assert r.status_code == 200
    rid = r.headers.get(HEADER_NAME)
    assert rid is not None
    assert len(rid) == 32
    assert all(c in "0123456789abcdef" for c in rid)


@pytest.mark.asyncio
async def test_v067_trace_id_client_supplied_retained() -> None:
    """合法 X-Request-ID 被服务端原样回传。"""
    supplied = _hex32()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/v1/health", headers={HEADER_NAME: supplied})
    assert r.headers.get(HEADER_NAME) == supplied


@pytest.mark.asyncio
async def test_v067_trace_id_illegal_chars_sanitized() -> None:
    """非法字符（<, >, 空格 等）触发重新生成，不复用客户端污染值。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/v1/health", headers={HEADER_NAME: "evil<script>alert(1)</script>"})
    rid = r.headers.get(HEADER_NAME)
    assert rid is not None
    assert rid != "evil<script>alert(1)</script>"
    assert len(rid) == 32


@pytest.mark.asyncio
async def test_v067_trace_id_too_short_rejected() -> None:
    """长度 < 8 视为非法，重生成（防日志注入 + 兜底短值）。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/v1/health", headers={HEADER_NAME: "abc"})
    rid = r.headers.get(HEADER_NAME)
    assert rid is not None
    assert rid != "abc"
    assert len(rid) == 32


@pytest.mark.asyncio
async def test_v067_trace_id_appears_in_response_header_on_404() -> None:
    """404 响应也带 X-Request-ID（CORS 拦截场景的关键可观测性）。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/v1/does-not-exist")
    assert r.status_code == 404
    assert HEADER_NAME in r.headers


def test_v067_trace_id_contextvar_default_is_dash() -> None:
    """HTTP 请求外（如后台任务 / 单测）默认 trace_id 为 '-'。"""
    assert get_current_trace_id() == "-"


def test_v067_trace_id_contextvar_set_reset() -> None:
    """set_trace_id / reset_trace_id 手动管理后台任务 trace_id。"""
    assert get_current_trace_id() == "-"
    tid = "abc1234567"
    token = set_trace_id(tid)
    try:
        assert get_current_trace_id() == tid
    finally:
        reset_trace_id(token)
    assert get_current_trace_id() == "-"


@pytest.mark.asyncio
async def test_v067_trace_id_middleware_skips_lifespan_scope() -> None:
    """非 HTTP scope（lifespan）应直通，不强制注入 trace_id。"""
    sent_messages: list = []

    async def downstream_app(scope, receive, send):
        # 在 lifespan 阶段，scope['type'] 应保持 'lifespan'
        await send({"type": "lifespan.startup.complete"})

    middleware = TraceIdMiddleware(downstream_app)

    scope = {"type": "lifespan", "headers": []}
    receive_q: asyncio.Queue = asyncio.Queue()
    await receive_q.put({"type": "lifespan.startup"})

    async def receive():
        return await receive_q.get()

    async def send(msg):
        sent_messages.append(msg)

    await middleware(scope, receive, send)
    assert len(sent_messages) == 1
    assert sent_messages[0]["type"] == "lifespan.startup.complete"
    # lifespan 阶段不应该在 headers 里看到 X-Request-ID
    assert all("X-Request-ID" not in str(m) for m in sent_messages)
