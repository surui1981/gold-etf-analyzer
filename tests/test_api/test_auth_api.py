"""认证 API 集成测试（V0.75.0 认证骨架 · HTTP 层）。

覆盖：
- ``/auth/status`` 匿名可访问，反映 AUTH_ENABLED / allow_registration / user_count
- 注册（首个用户 owner / 自动登录 / cookie 属性 HttpOnly + SameSite=Strict）
- 登录（成功 / 密码错 401 + ``detail.code`` / 弱密码 422 / 重复邮箱 409 / 邮箱非法 422）
- 关闭自助注册时 403；库中无用户时仍可初始化管理员
- ``/auth/me`` 未登录 401、登录后返回本人
- 登出（撤销会话 / 清 cookie / 幂等返回 revoked=false）
- 会话门禁：AUTH_ENABLED=true 时非公开端点匿名一律 401，公开端点放行
- CSRF：写端点缺 ``X-CSRF-Token`` → 403；带正确 token → 通过；豁免端点不需要 token
- **零破坏回归**：AUTH_ENABLED=false（默认）时既有端点行为与 V0.74.3 完全一致
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.config import get_settings
from app.dependencies import get_login_throttle
from app.main import app
from app.services.auth import LoginThrottle

GOOD_PASSWORD = "Gold2026pass"

# 公开端点（匿名可达）
PUBLIC = "/api/v1/health"
# 需登录端点（任意非公开 API）
GATED = "/api/v1/market/health"
# 写端点探针（CSRF 校验用）
WRITE_PROBE = "/api/v1/settings/test-email"


@pytest.fixture
def auth_on(monkeypatch):
    """开启认证（并降 bcrypt cost / 换掉进程级节流器），测试结束自动还原。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "bcrypt_cost", 4)
    monkeypatch.setattr(settings, "session_cookie_secure", False)
    monkeypatch.setattr(settings, "allow_registration", True)

    # 节流器是 lru_cache 单例，跨用例会累积失败计数 → 覆盖为全新实例
    fresh = LoginThrottle(max_attempts=5, window_seconds=900, lockout_seconds=900)
    app.dependency_overrides[get_login_throttle] = lambda: fresh
    try:
        yield settings
    finally:
        app.dependency_overrides.pop(get_login_throttle, None)


async def _register(client: AsyncClient, email: str = "owner@example.com", **extra):
    return await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": GOOD_PASSWORD, **extra},
    )


async def _login(client: AsyncClient, email: str, password: str = GOOD_PASSWORD):
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


def _cookie_header(resp) -> str:
    return "; ".join(resp.headers.get_list("set-cookie"))


# ───────────────────── /auth/status ─────────────────────


async def test_status_reports_single_user_mode_by_default(client: AsyncClient) -> None:
    """默认（AUTH_ENABLED=false）如实回答「本站不需要登录」。"""
    resp = await client.get("/api/v1/auth/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["auth_enabled"] is False
    assert body["authenticated"] is False
    assert body["user_count"] == 0


async def test_status_anonymous_after_auth_enabled(client: AsyncClient, auth_on) -> None:
    resp = await client.get("/api/v1/auth/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["auth_enabled"] is True
    assert body["allow_registration"] is True
    assert body["authenticated"] is False
    assert body["user_count"] == 0


async def test_status_issues_csrf_cookie_when_auth_enabled(client: AsyncClient, auth_on) -> None:
    """首个 GET 就下发 pm_csrf —— 前端此后所有写请求才有 token 可回填。"""
    resp = await client.get("/api/v1/auth/status")
    assert "pm_csrf=" in _cookie_header(resp)
    assert "HttpOnly" not in _cookie_header(resp)  # double-submit 必须能被 JS 读到
    assert "SameSite=Strict" in _cookie_header(resp)


# ───────────────────── 注册 / 登录 ─────────────────────


async def test_register_creates_owner_and_logs_in(client: AsyncClient, auth_on) -> None:
    resp = await _register(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["email"] == "owner@example.com"
    assert body["user"]["role"] == "owner"  # 首个用户是管理员
    assert body["expires_at"]

    # 已自动登录
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "owner@example.com"


async def test_session_cookie_is_hardened(client: AsyncClient, auth_on) -> None:
    resp = await _register(client)
    raw = _cookie_header(resp)
    assert "pm_session=" in raw
    assert "HttpOnly" in raw
    assert "SameSite=Strict" in raw
    assert "Path=/" in raw
    assert "Secure" not in raw  # dev 配置 session_cookie_secure=False


async def test_session_cookie_secure_flag_follows_config(
    client: AsyncClient, auth_on, monkeypatch
) -> None:
    """生产（HTTPS + nginx）下必须带 Secure。"""
    monkeypatch.setattr(auth_on, "session_cookie_secure", True)
    resp = await _register(client)
    assert "Secure" in _cookie_header(resp)


async def test_second_registered_user_is_member(client: AsyncClient, auth_on) -> None:
    await _register(client, "first@example.com")
    client.cookies.clear()
    resp = await _register(client, "second@example.com")
    assert resp.json()["user"]["role"] == "member"


async def test_login_success(client: AsyncClient, auth_on) -> None:
    await _register(client)
    client.cookies.clear()
    resp = await _login(client, "owner@example.com")
    assert resp.status_code == 200
    assert resp.json()["user"]["email"] == "owner@example.com"
    assert (await client.get("/api/v1/auth/me")).status_code == 200


async def test_login_wrong_password_returns_code(client: AsyncClient, auth_on) -> None:
    await _register(client)
    client.cookies.clear()
    resp = await _login(client, "owner@example.com", "WrongPassword9")
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "invalid_credentials"
    assert resp.headers.get("x-auth-required") == "1"


async def test_login_unknown_account_same_response(client: AsyncClient, auth_on) -> None:
    await _register(client)
    client.cookies.clear()
    resp = await _login(client, "nobody@example.com")
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "invalid_credentials"


async def test_register_weak_password_422(client: AsyncClient, auth_on) -> None:
    resp = await client.post(
        "/api/v1/auth/register", json={"email": "a@example.com", "password": "12345678"}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "password_weak"


async def test_register_invalid_email_422(client: AsyncClient, auth_on) -> None:
    resp = await client.post(
        "/api/v1/auth/register", json={"email": "not-an-email", "password": GOOD_PASSWORD}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "email_invalid"


async def test_register_duplicate_email_409(client: AsyncClient, auth_on) -> None:
    await _register(client, "dup@example.com")
    client.cookies.clear()
    resp = await _register(client, "DUP@example.com")  # 大小写不同仍视为同一账号
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "email_taken"


async def test_register_disabled_403_when_users_exist(
    client: AsyncClient, auth_on, monkeypatch
) -> None:
    await _register(client, "first@example.com")
    client.cookies.clear()
    monkeypatch.setattr(auth_on, "allow_registration", False)
    resp = await _register(client, "second@example.com")
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "registration_disabled"


async def test_first_user_can_still_initialize_when_registration_disabled(
    client: AsyncClient, auth_on, monkeypatch
) -> None:
    """库中无用户时即使关闭自助注册也要能建号，否则永远无人可登录。"""
    monkeypatch.setattr(auth_on, "allow_registration", False)
    resp = await _register(client, "init@example.com")
    assert resp.status_code == 200
    assert resp.json()["user"]["role"] == "owner"


async def test_change_password_keeps_current_session(
    client: AsyncClient, auth_on, monkeypatch
) -> None:
    monkeypatch.setattr(auth_on, "bcrypt_cost", 4)
    await _register(client)
    resp = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": GOOD_PASSWORD, "new_password": "NewGold2026"},
        headers={"X-CSRF-Token": client.cookies.get("pm_csrf")},
    )
    assert resp.status_code == 200
    assert resp.json()["revoked_sessions"] == 0  # 当前会话保留
    assert (await client.get("/api/v1/auth/me")).status_code == 200


# ───────────────────── 登出 ─────────────────────


async def test_logout_revokes_session_and_clears_cookie(client: AsyncClient, auth_on) -> None:
    await _register(client)
    resp = await client.post(
        "/api/v1/auth/logout", headers={"X-CSRF-Token": client.cookies.get("pm_csrf")}
    )
    assert resp.status_code == 200
    assert resp.json()["revoked"] is True
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_logout_is_idempotent_for_stale_tab(client: AsyncClient, auth_on) -> None:
    """已登出后再点退出：返回 200 + revoked=false（而非 401 让人以为坏了）。"""
    await _register(client)
    await client.post(
        "/api/v1/auth/logout", headers={"X-CSRF-Token": client.cookies.get("pm_csrf")}
    )
    again = await client.post(
        "/api/v1/auth/logout", headers={"X-CSRF-Token": client.cookies.get("pm_csrf")}
    )
    assert again.status_code == 200
    assert again.json()["revoked"] is False


# ───────────────────── 会话门禁 ─────────────────────


async def test_anonymous_is_blocked_on_gated_endpoint(client: AsyncClient, auth_on) -> None:
    resp = await client.get(GATED)
    assert resp.status_code == 401
    assert resp.headers.get("x-auth-required") == "1"
    assert resp.json()["detail"]["code"] == "unauthenticated"


async def test_public_endpoint_stays_open(client: AsyncClient, auth_on) -> None:
    assert (await client.get(PUBLIC)).status_code == 200


async def test_login_page_route_available(client: AsyncClient, auth_on) -> None:
    resp = await client.get("/login")
    assert resp.status_code == 307
    assert resp.headers["location"] == "/static/login.html"


async def test_authenticated_user_reaches_gated_endpoint(client: AsyncClient, auth_on) -> None:
    await _register(client)
    # market/health 在测试环境返回 200（行情源降级 mock），关键是不再 401
    resp = await client.get(GATED)
    assert resp.status_code != 401


async def test_me_requires_login(client: AsyncClient, auth_on) -> None:
    assert (await client.get("/api/v1/auth/me")).status_code == 401


# ───────────────────── CSRF ─────────────────────


async def test_write_without_csrf_token_is_rejected(client: AsyncClient, auth_on) -> None:
    await _register(client)
    assert client.cookies.get("pm_csrf")  # 注册响应已下发 token
    resp = await client.post(WRITE_PROBE)
    assert resp.status_code == 403
    assert resp.headers.get("x-csrf-failed") == "1"
    assert resp.json()["detail"]["code"] == "csrf_failed"


async def test_write_with_wrong_csrf_token_is_rejected(client: AsyncClient, auth_on) -> None:
    await _register(client)
    resp = await client.post(WRITE_PROBE, headers={"X-CSRF-Token": "forged-token"})
    assert resp.status_code == 403


async def test_write_with_matching_csrf_token_passes(client: AsyncClient, auth_on) -> None:
    await _register(client)
    resp = await client.post(WRITE_PROBE, headers={"X-CSRF-Token": client.cookies.get("pm_csrf")})
    assert resp.status_code == 200


async def test_csrf_rejected_when_token_cookie_missing(client: AsyncClient, auth_on) -> None:
    """只有会话 cookie、没有 csrf cookie 的请求也必须被拒（不可仅凭会话放行）。"""
    await _register(client)
    client.cookies.delete("pm_csrf")
    resp = await client.post(WRITE_PROBE)
    assert resp.status_code == 403


async def test_telemetry_ingest_is_csrf_exempt(client: AsyncClient, auth_on) -> None:
    """sendBeacon 无法设置自定义头，故埋点端点必须豁免（否则前端埋点全线 403）。"""
    resp = await client.post(
        "/api/v1/telemetry/ingest",
        json={"events": [{"event_type": "page_view", "page": "/static/trend.html"}]},
    )
    assert resp.status_code == 200
    assert resp.json()["accepted"] == 1


async def test_csrf_not_enforced_when_auth_disabled(client: AsyncClient) -> None:
    """单用户模式无环境凭据 → 不应凭空出现 403。"""
    resp = await client.post("/api/v1/telemetry/ingest", json={"events": []})
    assert resp.status_code != 403


# ───────────────────── 零破坏回归（AUTH_ENABLED=false）─────────────────────


async def test_single_user_mode_serves_business_endpoint_without_login(client: AsyncClient) -> None:
    """默认单用户模式：既有业务端点无需登录、无需 CSRF 头。"""
    resp = await client.get("/api/v1/accounts")
    assert resp.status_code == 200


async def test_single_user_mode_write_endpoint_without_csrf(client: AsyncClient) -> None:
    """写端点（测试环境 admin token 为空 → 跳过守卫）在单模式下应正常放行。"""
    resp = await client.post(WRITE_PROBE)
    assert resp.status_code == 200


async def test_single_user_mode_does_not_issue_auth_cookies(client: AsyncClient) -> None:
    resp = await client.get(PUBLIC)
    cookies = _cookie_header(resp)
    assert "pm_session=" not in cookies
    assert "pm_csrf=" not in cookies
