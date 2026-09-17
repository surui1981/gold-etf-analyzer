"""trace_id 中间件（V0.67.0 P0 框架基础补齐）。

为每个 HTTP 请求注入一个 ``X-Request-ID``：

- 入站：若客户端已传 ``X-Request-ID``（通常由上游网关 / 浏览器 / SDK 生成）则沿用，
  否则自动生成 UUIDv4（无连字符短格式以减少日志行长度）。
- 进程内：通过 ``contextvars.ContextVar`` 暴露给任意调用栈，
  配合 :func:`app.utils.logger.bind_trace_id` 由日志格式器自动附加。
- 出站：在响应头里回写 ``X-Request-ID``，让客户端 / 上游可以串联。

**为什么不用 ``BaseHTTPMiddleware``**：FastAPI 早期版本的 ``BaseHTTPMiddleware``
会引入一个独立 asyncio task 来运行下游流，可能导致 ``contextvars`` 在某些场景下
丢失（已知问题 starlette#420）。这里改用纯 ASGI 中间件（最简实现），
``contextvars.copy_context()`` 在进入时复制，结束时还原——保证 trace_id
在整条请求链路上唯一可见。

References:
    - https://asgi.readthedocs.io/en/latest/specs/main.html
    - https://docs.python.org/3/library/contextvars.html
"""

from __future__ import annotations

import contextvars
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# 模块级 ContextVar。默认值 "-" 表示「未绑定」，日志格式器据此判断是否附加。
_trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_trace_id", default="-")


def get_current_trace_id() -> str:
    """获取当前请求的 trace_id（中间件外调用默认返回 "-"）。"""
    return _trace_id_var.get()


def set_trace_id(value: str) -> contextvars.Token[str]:
    """手动注入 trace_id（用于后台任务、scheduler 触发等非 HTTP 上下文）。

    与 :func:`reset_trace_id` 配对使用，确保不影响其他协程。
    """
    return _trace_id_var.set(value)


def reset_trace_id(token: contextvars.Token[str]) -> None:
    """还原 :func:`set_trace_id` 的设置。"""
    _trace_id_var.reset(token)


def _new_trace_id() -> str:
    """生成无连字符的 UUIDv4（32 字符），便于日志 grep。"""
    return uuid.uuid4().hex


HEADER_NAME = "X-Request-ID"


class TraceIdMiddleware:
    """纯 ASGI 中间件：注入 trace_id 并在响应头回写。

    Usage::

        app.add_middleware(TraceIdMiddleware)

    必须注册在 ``CORSMiddleware`` **之前**（add_middleware 是 LIFO），
    以保证 CORS 预检失败也能看到 trace_id。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # 只对 HTTP 请求生效（跳过 lifespan / websocket）
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 1) 提取或生成 trace_id
        headers = scope.get("headers") or []
        trace_id: str | None = None
        for name, value in headers:
            if name.lower() == HEADER_NAME.lower().encode():
                raw = value.decode("latin-1", errors="replace").strip()
                # 安全裁剪：限定 8-128 字符且仅允许常见字符，防止日志注入
                if 8 <= len(raw) <= 128 and all(c.isalnum() or c in "-_." for c in raw):
                    trace_id = raw
                break
        if trace_id is None:
            trace_id = _new_trace_id()

        # 2) 绑定到 contextvars（仅当前任务可见）
        token = _trace_id_var.set(trace_id)
        scope.setdefault("extensions", {})["trace_id"] = trace_id

        # 3) 包裹 send 以在响应头里回写
        response_started = False

        async def send_with_trace(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start" and not response_started:
                headers_list = list(message.get("headers") or [])
                headers_list.append((HEADER_NAME.lower().encode(), trace_id.encode("latin-1")))
                message["headers"] = headers_list
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_with_trace)
        finally:
            _trace_id_var.reset(token)


# 便捷别名：用于 app.add_middleware(type=...) 或显式 TraceIdMiddleware(app)
def install(app: ASGIApp) -> TraceIdMiddleware:
    """工厂函数，便于测试与显式依赖注入。"""
    return TraceIdMiddleware(app)


__all__ = [
    "HEADER_NAME",
    "TraceIdMiddleware",
    "get_current_trace_id",
    "install",
    "reset_trace_id",
    "set_trace_id",
]
