"""V0.82 admin-token 端点测试。

覆盖：
- POST 正确 token ⇒ 200 + Set-Cookie
- POST 错 token ⇒ 401
- POST 无 ADMIN_TOKEN 配置 ⇒ 503
- POST 单用户模式 ⇒ 400
- POST 设的 cookie 可被 require_admin_session 接受（端到端）
- DELETE ⇒ Set-Cookie 清空
- cookie 属性：HttpOnly / SameSite=Lax / Path=/
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.endpoints import admin_token as admin_token_module
from app.config import get_settings
from app.middleware.admin_auth import (
    ADMIN_SESSION_COOKIE,
    ADMIN_SESSION_TTL_SECONDS,
    require_admin_session,
)

# ───────────────────── fixtures ─────────────────────


@pytest.fixture
def admin_token_value(monkeypatch: pytest.MonkeyPatch) -> str:
    """注入 ADMIN_TOKEN + AUTH_ENABLED=true，返回 token。"""
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("ADMIN_TOKEN", token)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    return token


@pytest.fixture
def app_admin_token(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FastAPI]:
    """挂 admin_token 端点 + 受守卫端点的最小 app。"""
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("ADMIN_TOKEN", token)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    app = FastAPI()
    app.include_router(admin_token_module.router, prefix="/api/v1")

    @app.post("/protected", dependencies=[Depends(require_admin_session)])
    async def protected() -> dict[str, str]:
        return {"ok": "true"}

    yield app

    get_settings.cache_clear()  # type: ignore[attr-defined]


@pytest.fixture
def app_no_admin_token_env(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FastAPI]:
    """多用户模式 + ADMIN_TOKEN 未设（不应触发，但端点要正确处理）。"""
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    app = FastAPI()
    app.include_router(admin_token_module.router, prefix="/api/v1")

    yield app

    get_settings.cache_clear()  # type: ignore[attr-defined]


@pytest.fixture
def app_single_user(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FastAPI]:
    """单用户模式：AUTH_ENABLED=false，POST 应该 400。"""
    monkeypatch.setenv("AUTH_ENABLED", "false")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    app = FastAPI()
    app.include_router(admin_token_module.router, prefix="/api/v1")

    yield app

    get_settings.cache_clear()  # type: ignore[attr-defined]


# ───────────────────── POST 成功路径 ─────────────────────


async def test_post_correct_token_returns_200_with_cookie(app_admin_token: FastAPI) -> None:
    """正确 token ⇒ 200 + Set-Cookie。"""
    token = get_settings().admin_token
    assert token is not None

    transport = ASGITransport(app=app_admin_token)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/v1/admin-token", json={"token": token})
    assert r.status_code == 200
    body = r.json()
    assert body["expires_in"] > 0
    # Set-Cookie 应包含 admin session cookie
    assert ADMIN_SESSION_COOKIE in r.headers.get("set-cookie", "")


async def test_post_sets_cookie_with_correct_attrs(app_admin_token: FastAPI) -> None:
    """cookie 属性：HttpOnly + SameSite=Lax + Path=/。"""
    token = get_settings().admin_token
    assert token is not None

    transport = ASGITransport(app=app_admin_token)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/v1/admin-token", json={"token": token})
    set_cookie = r.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie
    assert "SameSite=Lax" in set_cookie or "samesite=lax" in set_cookie.lower()
    assert "Path=/" in set_cookie


async def test_post_then_access_protected_endpoint(app_admin_token: FastAPI) -> None:
    """端到端：POST 设 cookie ⇒ 后续请求带 cookie 访问保护端点通过。"""
    token = get_settings().admin_token
    assert token is not None

    transport = ASGITransport(app=app_admin_token)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1) POST token → 拿到 cookie
        r = await client.post("/api/v1/admin-token", json={"token": token})
        assert r.status_code == 200
        cookie_value = r.cookies.get(ADMIN_SESSION_COOKIE)
        assert cookie_value is not None

        # 2) 带 cookie 访问受守卫端点
        r = await client.post("/protected")
        assert r.status_code == 200


# ───────────────────── POST 失败路径 ─────────────────────


async def test_post_wrong_token_returns_401(app_admin_token: FastAPI) -> None:
    """错 token ⇒ 401 + 不下发 cookie。"""
    transport = ASGITransport(app=app_admin_token)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/v1/admin-token", json={"token": "wrong-token"})
    assert r.status_code == 401
    body = r.json()
    assert body["detail"]["code"] == "admin_token_invalid"
    # 失败不应下发 cookie
    assert ADMIN_SESSION_COOKIE not in r.headers.get("set-cookie", "")


async def test_post_empty_token_returns_422(app_admin_token: FastAPI) -> None:
    """空 token ⇒ Pydantic 422 校验失败（min_length=1）。"""
    transport = ASGITransport(app=app_admin_token)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/v1/admin-token", json={"token": ""})
    assert r.status_code == 422


async def test_post_when_admin_token_not_configured(
    app_no_admin_token_env: FastAPI,
) -> None:
    """多用户模式 + ADMIN_TOKEN 未配置 ⇒ 503。"""
    transport = ASGITransport(app=app_no_admin_token_env)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/v1/admin-token", json={"token": "anything"})
    assert r.status_code == 503
    body = r.json()
    assert body["detail"]["code"] == "admin_token_not_configured"


async def test_post_in_single_user_mode_returns_400(app_single_user: FastAPI) -> None:
    """**关键**：单用户模式下 POST 直接 400 —— admin session 无意义。"""
    transport = ASGITransport(app=app_single_user)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/v1/admin-token", json={"token": "anything"})
    assert r.status_code == 400
    body = r.json()
    assert body["detail"]["code"] == "admin_session_disabled"


# ───────────────────── DELETE ─────────────────────


async def test_delete_clears_cookie(app_admin_token: FastAPI) -> None:
    """DELETE ⇒ Set-Cookie 清除该 cookie。"""
    transport = ASGITransport(app=app_admin_token)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.delete("/api/v1/admin-token")
    assert r.status_code == 200
    assert r.json() == {"cleared": True}
    # Set-Cookie 应包含该 cookie 的清空指令（max-age=0 或 expires=过去）
    set_cookie = r.headers.get("set-cookie", "")
    assert ADMIN_SESSION_COOKIE in set_cookie


async def test_delete_works_even_without_prior_set(app_admin_token: FastAPI) -> None:
    """幂等性：未设过 cookie 也能 DELETE（前端无需判断状态）。"""
    transport = ASGITransport(app=app_admin_token)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.delete("/api/v1/admin-token")
    assert r.status_code == 200


# ───────────────────── GET（V0.82 commit 4）─────────────────────


async def test_get_returns_no_session_when_cookie_missing(app_admin_token: FastAPI) -> None:
    """无 cookie ⇒ has_session=false，ttl 仍返回（UI 提示用）。"""
    transport = ASGITransport(app=app_admin_token)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/admin-token")
    assert r.status_code == 200
    body = r.json()
    assert body["has_session"] is False
    assert body["ttl_seconds"] == ADMIN_SESSION_TTL_SECONDS
    assert body["auth_enabled"] is True


async def test_get_returns_session_active_after_set(app_admin_token: FastAPI) -> None:
    """POST 后带 cookie 访问 GET ⇒ has_session=true。"""
    from app.middleware.admin_auth import issue_admin_session_cookie_value

    cookie_val = issue_admin_session_cookie_value()
    transport = ASGITransport(app=app_admin_token)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies={ADMIN_SESSION_COOKIE: cookie_val},
    ) as client:
        r = await client.get("/api/v1/admin-token")
    assert r.status_code == 200
    body = r.json()
    assert body["has_session"] is True
    assert body["auth_enabled"] is True


async def test_get_rejects_invalid_signature(app_admin_token: FastAPI) -> None:
    """带乱填 cookie ⇒ has_session=false（签名不匹配）。"""
    transport = ASGITransport(app=app_admin_token)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies={ADMIN_SESSION_COOKIE: "garbage.invalid"},
    ) as client:
        r = await client.get("/api/v1/admin-token")
    assert r.status_code == 200
    assert r.json()["has_session"] is False


async def test_get_reports_single_user_mode(app_single_user: FastAPI) -> None:
    """单用户模式：auth_enabled=false 透传给前端（提示 UI 不要显示按钮）。"""
    transport = ASGITransport(app=app_single_user)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/admin-token")
    assert r.status_code == 200
    body = r.json()
    assert body["auth_enabled"] is False
    # ADMIN_TOKEN 在单用户模式下 get_admin_token 返回 None ⇒ cookie 必然无效
    assert body["has_session"] is False
