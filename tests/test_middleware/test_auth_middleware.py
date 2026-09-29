"""认证 / CSRF 中间件测试（V0.75.0 认证骨架 · ASGI 层）。

中间件不是 FastAPI 路由，无法用 TestClient 直接观测其内部状态，
故这里用**最小 ASGI 内层应用**把 ``scope``、上下文变量与响应头捕获下来断言。

覆盖：
- user_id 上下文（默认 None / set+reset / 单用户模式固定 LEGACY_USER_ID）
- 非 ``/api/`` 路径完全短路（静态资源不查库、不设 user_id）
- AUTH_ENABLED=true 时匿名被 401 拦在路由之前（内层应用**不会**被调用）
- AUTH_ENABLED=true 时携带有效会话 → 内层拿到真实 user_id
- ``client_ip``（XFF 信任开关 / 取首跳 / 无 client 返回 None）
- Cookie 解析（正常 / 畸形 / 缺失）
- CSRF：下发 token cookie / 写端点校验 / 恒定时间比较 / 单用户模式透传
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.middleware.auth import (
    AuthMiddleware,
    CsrfMiddleware,
    client_ip,
    get_current_user_id,
    reset_user_id,
    set_user_id,
)
from app.models.user import LEGACY_USER_ID
from app.repositories.user import SessionRepository, UserRepository
from app.services.auth import AuthService

SESSION_COOKIE = "pm_session"
CSRF_COOKIE = "pm_csrf"

GOOD_PASSWORD = "Gold2026pass"


async def _drain_receive():  # pragma: no cover - 请求体始终为空
    return {"type": "http.request", "body": b"", "more_body": False}


class _Recorder:
    """捕获内层应用的调用与响应消息。"""

    def __init__(self) -> None:
        self.called = False
        self.user_id: int | None = "UNSET"
        self.state: dict | None = None

    def inner(self):
        async def app(scope, receive, send) -> None:
            self.called = True
            self.user_id = get_current_user_id()
            self.state = scope.get("state")
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        return app


def _scope(path: str, *, method: str = "GET", headers: list | None = None, client=None):
    return {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or [])],
        "client": client or ("127.0.0.1", 5000),
        "server": ("test", 80),
        "scheme": "http",
    }


async def _call(mw, scope):
    """跑一遍中间件，返回 (响应头列表, 状态码)。"""
    messages: list[dict] = []

    async def send(message) -> None:
        messages.append(message)

    await mw(scope, _drain_receive, send)
    start = next((m for m in messages if m["type"] == "http.response.start"), None)
    headers = [(k.decode(), v.decode()) for k, v in (start or {}).get("headers", [])]
    return headers, (start or {}).get("status")


# ───────────────────── user_id 上下文 ─────────────────────


def test_user_id_context_default_is_none() -> None:
    assert get_current_user_id() is None


def test_user_id_context_set_and_reset() -> None:
    token = set_user_id(42)
    assert get_current_user_id() == 42
    reset_user_id(token)
    assert get_current_user_id() is None


# ───────────────────── 单用户模式（AUTH_ENABLED=false）─────────────────────


async def test_disabled_mode_sets_legacy_user_id() -> None:
    rec = _Recorder()
    mw = AuthMiddleware(rec.inner())
    _, status = await _call(mw, _scope("/api/v1/health"))

    assert status == 200 and rec.called
    assert rec.user_id == LEGACY_USER_ID  # 业务代码继续以 user_id=1 语义运行
    assert rec.state is not None
    assert rec.state["auth_enabled"] is False
    assert rec.state["user"] is None


async def test_disabled_mode_restores_context_after_request() -> None:
    rec = _Recorder()
    mw = AuthMiddleware(rec.inner())
    await _call(mw, _scope("/api/v1/health"))
    assert get_current_user_id() is None  # 出栈后还原，不污染其他协程


async def test_non_api_path_is_short_circuited() -> None:
    """静态资源路径不该进入认证逻辑（连 user_id 上下文都不碰）。

    判据是**对比**：同一开关下 ``/api/`` 路径会拿到 LEGACY_USER_ID(1)，
    而 ``/static/`` 路径拿到的是上下文变量默认值 None ——
    说明中间件在路径判断处就返回了，没做任何 cookie / DB 工作。
    """
    api_rec = _Recorder()
    await _call(AuthMiddleware(api_rec.inner()), _scope("/api/v1/health"))
    assert api_rec.user_id == LEGACY_USER_ID

    static_rec = _Recorder()
    await _call(AuthMiddleware(static_rec.inner()), _scope("/static/trend.html"))

    assert static_rec.called
    assert static_rec.user_id is None  # 未被设置为 LEGACY
    assert static_rec.state is None  # 也未写入 scope["state"]


# ───────────────────── 多用户模式（AUTH_ENABLED=true）─────────────────────


@pytest.fixture
def auth_on(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "bcrypt_cost", 4)
    return settings


async def test_enabled_mode_blocks_anonymous_before_route(auth_on) -> None:
    """门禁必须在**路由之前**生效：内层应用不应被调用。"""
    rec = _Recorder()
    mw = AuthMiddleware(rec.inner())
    headers, status = await _call(mw, _scope("/api/v1/market/health"))

    assert status == 401
    assert rec.called is False
    assert ("x-auth-required", "1") in headers


async def test_enabled_mode_allows_public_path(auth_on) -> None:
    rec = _Recorder()
    mw = AuthMiddleware(rec.inner())
    _, status = await _call(mw, _scope("/api/v1/health"))

    assert status == 200 and rec.called
    assert rec.user_id is None  # 匿名，且不是 LEGACY
    assert rec.state["auth_enabled"] is True


async def test_enabled_mode_resolves_real_user_from_cookie(db_session, auth_on) -> None:
    svc = AuthService(UserRepository(db_session), SessionRepository(db_session), auth_on)
    user = await svc.register(email="a@example.com", password=GOOD_PASSWORD)
    _, issued = await svc.login(email="a@example.com", password=GOOD_PASSWORD)

    rec = _Recorder()
    mw = AuthMiddleware(rec.inner())
    _, status = await _call(
        mw,
        _scope(
            "/api/v1/market/health", headers=[("cookie", f"{SESSION_COOKIE}={issued.session_id}")]
        ),
    )

    assert status == 200 and rec.called
    assert rec.user_id == user.id
    assert rec.state["user"].id == user.id
    assert rec.state["session_id"] == issued.session_id


async def test_enabled_mode_treats_unknown_session_as_anonymous(db_session, auth_on) -> None:
    rec = _Recorder()
    mw = AuthMiddleware(rec.inner())
    _, status = await _call(
        mw,
        _scope(
            "/api/v1/market/health", headers=[("cookie", f"{SESSION_COOKIE}=forged-session-id")]
        ),
    )
    assert status == 401
    assert rec.called is False


async def test_enabled_mode_ignores_malformed_cookie(db_session, auth_on) -> None:
    """畸形 Cookie 头不应打出 500 —— 解析失败等同「无会话」。"""
    rec = _Recorder()
    mw = AuthMiddleware(rec.inner())
    _, status = await _call(
        mw, _scope("/api/v1/market/health", headers=[("cookie", "=;;;pm_session")])
    )
    assert status == 401


async def test_disabled_mode_ignores_session_cookie(db_session, auth_on, monkeypatch) -> None:
    """关掉开关后，即使浏览器还带着旧会话 cookie 也一律按单用户模式处理。"""
    svc = AuthService(UserRepository(db_session), SessionRepository(db_session), auth_on)
    await svc.register(email="a@example.com", password=GOOD_PASSWORD)
    _, issued = await svc.login(email="a@example.com", password=GOOD_PASSWORD)

    monkeypatch.setattr(auth_on, "auth_enabled", False)
    rec = _Recorder()
    mw = AuthMiddleware(rec.inner())
    await _call(
        mw,
        _scope(
            "/api/v1/market/health", headers=[("cookie", f"{SESSION_COOKIE}={issued.session_id}")]
        ),
    )
    assert rec.user_id == LEGACY_USER_ID


# ───────────────────── client_ip ─────────────────────


def test_client_ip_uses_peer_by_default() -> None:
    assert client_ip(_scope("/x", client=("10.1.2.3", 1234))) == "10.1.2.3"


def test_client_ip_ignores_xff_without_trust() -> None:
    """默认不信任 XFF（可伪造），避免审计/节流被客户端左右。"""
    scope = _scope("/x", headers=[("x-forwarded-for", "1.2.3.4")], client=("10.1.2.3", 1))
    assert client_ip(scope) == "10.1.2.3"
    assert client_ip(scope, trust_proxy=True) == "1.2.3.4"


def test_client_ip_takes_first_xff_hop() -> None:
    scope = _scope("/x", headers=[("x-forwarded-for", "1.2.3.4, 5.6.7.8")], client=("10.1.2.3", 1))
    assert client_ip(scope, trust_proxy=True) == "1.2.3.4"


def test_client_ip_none_when_no_client() -> None:
    scope = _scope("/x")
    scope["client"] = None
    assert client_ip(scope) is None


# ───────────────────── CSRF ─────────────────────


async def test_csrf_passthrough_when_auth_disabled() -> None:
    rec = _Recorder()
    mw = CsrfMiddleware(rec.inner())
    headers, status = await _call(mw, _scope("/api/v1/positions", method="POST"))

    assert status == 200
    assert not any(k == "set-cookie" for k, _ in headers)  # 不下发任何 cookie


async def test_csrf_issued_on_get(auth_on) -> None:
    rec = _Recorder()
    mw = CsrfMiddleware(rec.inner())
    headers, status = await _call(mw, _scope("/api/v1/health"))

    assert status == 200
    cookie = next(v for k, v in headers if k == "set-cookie")
    assert cookie.startswith(f"{CSRF_COOKIE}=")
    assert "SameSite=Strict" in cookie
    assert "HttpOnly" not in cookie  # 必须能被前端读取后回填请求头


async def test_csrf_write_without_header_rejected(auth_on) -> None:
    rec = _Recorder()
    mw = CsrfMiddleware(rec.inner())
    headers, status = await _call(
        mw,
        _scope("/api/v1/positions", method="POST", headers=[("cookie", f"{CSRF_COOKIE}=tok123")]),
    )
    assert status == 403
    assert rec.called is False
    assert ("x-csrf-failed", "1") in headers


async def test_csrf_write_with_matching_header_passes(auth_on) -> None:
    rec = _Recorder()
    mw = CsrfMiddleware(rec.inner())
    _, status = await _call(
        mw,
        _scope(
            "/api/v1/positions",
            method="POST",
            headers=[("cookie", f"{CSRF_COOKIE}=tok123"), ("x-csrf-token", "tok123")],
        ),
    )
    assert status == 200 and rec.called


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_csrf_rejects_all_write_methods(auth_on, method: str) -> None:
    rec = _Recorder()
    mw = CsrfMiddleware(rec.inner())
    _, status = await _call(
        mw,
        _scope("/api/v1/positions", method=method, headers=[("cookie", f"{CSRF_COOKIE}=tok123")]),
    )
    assert status == 403


async def test_csrf_exempt_path_needs_no_header(auth_on) -> None:
    rec = _Recorder()
    mw = CsrfMiddleware(rec.inner())
    _, status = await _call(mw, _scope("/api/v1/telemetry/ingest", method="POST"))
    assert status == 200 and rec.called


async def test_csrf_ignored_for_non_api_path(auth_on) -> None:
    rec = _Recorder()
    mw = CsrfMiddleware(rec.inner())
    _, status = await _call(mw, _scope("/static/trend.html", method="POST"))
    assert status == 200 and rec.called


# ── 中间件装配顺序契约（V0.75.0）──
#
# `add_middleware` 是 **LIFO**：先注册的成为**内层**，`app.user_middleware[0]` 是最外层。
# 顺序错一格就会让「匿名写方法」得到 403（csrf_failed）而不是 401（unauthenticated）
# —— 前端据此判断是否跳登录页，错判会把未登录用户导向「刷新页面重试」的错误提示。
# 这类缺陷在单测里全部通过（每个中间件各自正确），只有端到端才有感知，故在此锁死。


def test_middleware_stack_order() -> None:
    """AuthMiddleware 必须在 CsrfMiddleware **外层**（即后注册）。"""
    from app.main import app

    names = [m.cls.__name__ for m in app.user_middleware]
    assert "AuthMiddleware" in names, f"未装配 AuthMiddleware：{names}"
    assert "CsrfMiddleware" in names, f"未装配 CsrfMiddleware：{names}"
    assert names.index("AuthMiddleware") < names.index("CsrfMiddleware"), (
        "AuthMiddleware 必须在 CsrfMiddleware 外层（后注册者更靠外），"
        f"否则匿名写方法会得到 403 而非 401。当前顺序：{names}"
    )


def test_trace_id_outermost_among_auth_stack() -> None:
    """TraceId 应在 Auth/Csrf 之外，使两者的审计日志都带 trace_id。"""
    from app.main import app

    names = [m.cls.__name__ for m in app.user_middleware]
    assert names.index("TraceIdMiddleware") < names.index("AuthMiddleware")
    assert names.index("TraceIdMiddleware") < names.index("CsrfMiddleware")


def test_cors_outermost() -> None:
    """CORS 必须最外层，否则 401/403 响应不带 CORS 头，前端只看到 "Failed to fetch"。"""
    from app.main import app

    names = [m.cls.__name__ for m in app.user_middleware]
    assert names[0] == "CORSMiddleware", f"最外层不是 CORSMiddleware：{names}"
