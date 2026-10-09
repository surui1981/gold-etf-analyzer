"""认证中间件 + CSRF 防护（V0.75.0 认证骨架）。

两个**纯 ASGI 中间件**（仿 :mod:`app.middleware.trace`，不用 ``BaseHTTPMiddleware``
以免引入额外 asyncio task 导致 ``contextvars`` 丢失）：

1. :class:`AuthMiddleware` —— 解析会话 cookie → 绑定 ``user_id`` 上下文 → 门禁。
2. :class:`CsrfMiddleware` —— 写端点的 double-submit token 校验 + 自动下发 token cookie。

注册顺序（关键）
----------------
``main.py`` 中必须在 ``TraceIdMiddleware`` **之前** ``add_middleware``：

- ``add_middleware`` 是 LIFO（后加的更靠外），
- 因此「先注册 Auth/Csrf」→ 它们成为**内层** → 外层依次是
  ``CORS → RateLimit → TraceId → Auth → Csrf → 路由``。

这样安排的三个好处：① Auth 内层，能拿到 trace_id 写审计日志；
② 401/403 响应仍带 CORS 头（否则前端读不到错误体）；
③ 登录失败会被 per-IP 限速**先拦一道**，暴力破解成本更高。

单用户模式（``AUTH_ENABLED=false``）
-----------------------------------
Auth 中间件**完全短路**：不读 cookie、不查库、不门禁，
``user_id`` 上下文固定为 :data:`LEGACY_USER_ID`；
CSRF 中间件同样完全透传（无「环境凭据」就没有 CSRF 可言）。
两者都不产生任何 DB 写入 —— 这是「行为 100% 兼容 V0.74.3」的实现保证。
"""

from __future__ import annotations

import json
import secrets
from http.cookies import SimpleCookie
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import get_settings
from app.models.user import LEGACY_USER_ID
from app.repositories.db import async_session_factory
from app.repositories.user import SessionRepository, UserRepository
from app.services.auth import AuthService
from app.utils.logger import get_logger
from app.utils.user_scope import get_current_user_id, reset_user_id, set_user_id

logger = get_logger(__name__)

# ============================ user_id 上下文 ============================

# V0.75.2 数据隔离：上下文与解析器已抽到 :mod:`app.utils.user_scope`。
# 原因是**仓储层也要读它** —— 若 repositories 反过来 import 本模块，会形成
# 「数据层 → HTTP 中间件」的反向依赖。本模块只负责**写**（解析会话 → set_user_id），
# 读取统一走 ``user_scope.current_user_id()``。
# 三个函数在此**再导出**，故 `from app.middleware.auth import get_current_user_id`
# 这类既有写法仍然有效。


# ============================ 路径规则 ============================

# 认证关闭时完全透传；开启时这些路径**无需登录**（其余 /api/ 一律 401）。
# 说明：/auth/me 与 /auth/change-password 刻意**不在**此列 —— 它们本就要求已登录。
# /auth/logout 在此列是为了让「已登出后再点退出」返回 200 {revoked:false}
# 而不是 401（单页应用里旧标签页/重复点击很常见，报错反而像功能坏了）。
PUBLIC_API_PATHS: frozenset[str] = frozenset(
    {
        "/api/v1/health",
        "/api/v1/auth/status",
        "/api/v1/auth/login",
        "/api/v1/auth/register",
        "/api/v1/auth/logout",
        # V0.75.3 找回密码：⚠ **必须是公开路径** —— 否则开启认证后，
        # 「忘记密码」会被 401 拦住，让已忘记密码的用户**无法找回密码**（死锁）。
        # 这是「忘记密码」功能的根本前提，不是可选的便利。
        "/api/v1/auth/forgot-password",
        "/api/v1/auth/reset-password",
        # 埋点走 sendBeacon，无法自定义请求头；且内容为匿名前端事件，不含业务数据
        "/api/v1/telemetry/ingest",
    }
)

# 写端点 CSRF 豁免：① 建立凭据的登录/注册（此前浏览器还没有 csrf cookie）
# ② sendBeacon 埋点（协议上无法设置自定义头）
# ③ V0.75.3 找回密码的两个写端点 ——⚠ 这是**有意的例外**，
# 理由：用户点邮件里的链接时是**全新会话**，浏览器里还没有 csrf cookie，
# 若强制要求 CSRF 双提交，流程会卡在「先访问一次页面拿 cookie」。
# ⚠ 风险评估：这两个端点**天然抗 CSRF** ——
# forgot-password 无论被跨站调用多少次，都只是给受害者发邮件 + 返回恒定响应，
#    不改变任何状态、不返回敏感内容；
# reset-password 需要邮件里那个 43 字符随机 token，攻击者的跨站表单**拿不到它**
#    （除非用户正开着带token 的页面 —— 而那本身需要先拿到 token）。
#    ⇒ 豁免 CSRF 的实际风险接近零，不引入新攻击面。
CSRF_EXEMPT_PATHS: frozenset[str] = PUBLIC_API_PATHS

_WRITE_METHODS: frozenset[str] = frozenset({"POST", "PUT", "PATCH", "DELETE"})

CSRF_HEADER_NAME = "X-CSRF-Token"


def _header_map(scope: Scope) -> dict[str, str]:
    """把 ASGI 的 ``[(bytes, bytes)]`` headers 折成小写键的 dict（后者覆盖前者）。"""
    out: dict[str, str] = {}
    for name, value in scope.get("headers") or []:
        out[name.decode("latin-1").lower()] = value.decode("latin-1")
    return out


def _parse_cookies(scope: Scope) -> dict[str, str]:
    """解析 Cookie 头；解析失败返回空 dict（不抛错，避免畸形请求打出 500）。"""
    raw = _header_map(scope).get("cookie")
    if not raw:
        return {}
    jar = SimpleCookie()
    try:
        jar.load(raw)
    except Exception:  # 畸形 Cookie 头
        return {}
    return {k: v.value for k, v in jar.items()}


def client_ip(scope: Scope, *, trust_proxy: bool = False) -> str | None:
    """取客户端 IP（仅用于**审计展示**与登录节流，不用于安全判定）。

    ``trust_proxy=True`` 时取 ``X-Forwarded-For`` 首跳（nginx 前置场景）。
    ⚠ XFF 可被客户端伪造，故默认关闭；真正的 per-IP 限速由
    :mod:`app.middleware.rate_limit` 按 TCP 连接地址执行。
    """
    headers = _header_map(scope)
    if trust_proxy:
        xff = headers.get("x-forwarded-for")
        if xff:
            first = xff.split(",")[0].strip()
            if first:
                return first[:64]
    client = scope.get("client")
    if client:
        return str(client[0])[:64]
    return None


def _error_body(code: str, message: str) -> bytes:
    """构造与认证端点**同构**的错误体：``{"detail": {"code": ..., "message": ...}}``。

    中间件与端点必须给出同一种形状 —— 前端只写一套解析逻辑
    （``body.detail.code``），否则「401 来自中间件」与「401 来自端点」
    会走两个分支，是极易腐坏的不一致。
    """
    payload = {"detail": {"code": code, "message": message}}
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


# ============================ AuthMiddleware ============================


class AuthMiddleware:
    """会话解析 + 未登录门禁。

    仅对 ``/api/`` 路径生效 —— 静态资源与 HTML 页面**不查库**，
    保证「登录后浏览 12 个页面」不会因认证引入额外 DB 往返；
    页面级门禁由前端 :file:`static/auth.js` 依据 ``/auth/status`` 处理。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not str(scope.get("path", "")).startswith("/api/"):
            await self.app(scope, receive, send)
            return

        # V0.82 测试隔离修复：每请求重新取 settings。
        # 原先在 __init__ 缓存 self._settings，但测试用 get_settings.cache_clear()
        # 会换出新对象，中间件仍持有旧对象 → 测试互相污染
        # （admin_token_endpoint → auth_api 链路 12 fail）。
        path = str(scope["path"])
        state: dict[str, Any] = scope.setdefault("state", {})
        settings = get_settings()

        # ── 单用户模式：完全短路，不读 cookie / 不查库 ──
        if not settings.auth_enabled:
            state["auth_enabled"] = False
            state["user"] = None
            state["session_id"] = None
            token = set_user_id(LEGACY_USER_ID)
            try:
                await self.app(scope, receive, send)
            finally:
                reset_user_id(token)
            return

        # ── 多用户模式：解析会话 ──
        session_id = _parse_cookies(scope).get(settings.session_cookie_name)
        user = None
        if session_id:
            try:
                async with async_session_factory() as db:
                    service = AuthService(UserRepository(db), SessionRepository(db), settings)
                    user = await service.authenticate(session_id)
            except Exception:  # 认证故障降级为「匿名」，由门禁决定是否 401
                logger.exception("auth middleware: 会话校验异常，降级为匿名")

        state["auth_enabled"] = True
        state["user"] = user
        state["session_id"] = session_id if user else None

        if user is None and path not in PUBLIC_API_PATHS:
            await _send_unauthorized(send)
            return

        token = set_user_id(user.id if user else None)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_user_id(token)


async def _send_unauthorized(send: Send) -> None:
    """返回 401，并带 ``X-Auth-Required`` 供前端识别「是认证问题」而非普通错误。"""
    body = _error_body("unauthenticated", "请先登录")
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
                (b"x-auth-required", b"1"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


# ============================ CsrfMiddleware ============================


class CsrfMiddleware:
    """double-submit token 校验 + 自动下发 token cookie。

    工作方式：

    - **下发**：``AUTH_ENABLED=true`` 时，任意 ``/api/`` 响应若未带 token cookie，
      中间件补一个 ``Set-Cookie``（非 HttpOnly，前端 JS 需读取后回填请求头）。
    - **校验**：写方法（POST/PUT/PATCH/DELETE）在 ``/api/`` 下且不在
      :data:`CSRF_EXEMPT_PATHS` 内，要求请求头 ``X-CSRF-Token`` 与 cookie
      **恒定时间相等**，否则 403。

    为什么 cookie 要非 HttpOnly：double-submit 模式必须让同源 JS 读到 token；
    token 本身不是凭据（真正的凭据是 HttpOnly 的会话 cookie），
    且异源脚本受同源策略限制读不到它，因此不能伪造请求头。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not str(scope.get("path", "")).startswith("/api/"):
            await self.app(scope, receive, send)
            return

        # V0.82 测试隔离修复：每请求重新取 settings（见 AuthMiddleware 同款注释）
        settings = get_settings()
        if not settings.auth_enabled:
            # 单用户模式：无环境凭据 → 无 CSRF 面；完全不介入（也不下发 cookie）
            await self.app(scope, receive, send)
            return

        path = str(scope["path"])
        cookies = _parse_cookies(scope)
        cookie_token = cookies.get(settings.csrf_cookie_name)
        method = str(scope.get("method", "GET")).upper()

        if method in _WRITE_METHODS and path not in CSRF_EXEMPT_PATHS:
            header_token = _header_map(scope).get(CSRF_HEADER_NAME.lower(), "")
            if not cookie_token or not _constant_time_eq(header_token, cookie_token):
                await _send_csrf_rejected(send)
                return

        # 下发 / 续期 token cookie（GET 与写请求都补，确保首个 GET 之后即可写）
        if not cookie_token:
            cookie_token = secrets.token_urlsafe(24)
            set_cookie = _build_csrf_cookie(settings, cookie_token)

            async def send_with_cookie(message: Message) -> None:
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers") or [])
                    headers.append((b"set-cookie", set_cookie.encode("latin-1")))
                    message["headers"] = headers
                await send(message)

            await self.app(scope, receive, send_with_cookie)
            return

        await self.app(scope, receive, send)


def _build_csrf_cookie(settings: Any, token: str) -> str:
    """构造 CSRF token cookie（非 HttpOnly；SameSite=Strict 阻断跨站携带）。"""
    parts = [
        f"{settings.csrf_cookie_name}={token}",
        "Path=/",
        "SameSite=Strict",
    ]
    if settings.session_cookie_secure:
        parts.append("Secure")
    return "; ".join(parts)


def _constant_time_eq(a: str, b: str) -> bool:
    """恒定时间比较，避免 token 逐字节猜测。"""
    return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


async def _send_csrf_rejected(send: Send) -> None:
    """CSRF 校验失败：403 + ``X-CSRF-Failed`` 头（前端据此提示「页面已过期，请刷新」）。"""
    body = _error_body("csrf_failed", "CSRF 校验失败，请刷新页面后重试")
    await send(
        {
            "type": "http.response.start",
            "status": 403,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
                (b"x-csrf-failed", b"1"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


__all__ = [
    "CSRF_EXEMPT_PATHS",
    "CSRF_HEADER_NAME",
    "PUBLIC_API_PATHS",
    "AuthMiddleware",
    "CsrfMiddleware",
    "client_ip",
    "get_current_user_id",
    "reset_user_id",
    "set_user_id",
]
