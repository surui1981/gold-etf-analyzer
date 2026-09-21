"""V0.72.0 P3-b：admin 守卫中间件测试。"""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.middleware.admin_auth import require_admin

# ───────────────────── 临时 app fixture ─────────────────────


@pytest.fixture
def app_with_admin(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FastAPI]:
    """构建一个带 ``require_admin`` 装饰的最小 app；env 注入 ADMIN_TOKEN。"""
    token = secrets.token_urlsafe(16)
    monkeypatch.setenv("ADMIN_TOKEN", token)
    get_settings.cache_clear()  # type: ignore[attr-defined]

    app = FastAPI()

    @app.post("/protected", dependencies=[Depends(require_admin)])
    async def protected() -> dict[str, str]:
        return {"ok": "true"}

    @app.get("/public")
    async def public() -> dict[str, str]:
        return {"ok": "true"}

    yield app

    get_settings.cache_clear()  # type: ignore[attr-defined]


@pytest.fixture
def app_dev_mode() -> AsyncIterator[FastAPI]:
    """dev 模式：无 ADMIN_TOKEN env，写端点无守卫。"""
    import os

    prev = os.environ.pop("ADMIN_TOKEN", None)
    get_settings.cache_clear()  # type: ignore[attr-defined]

    app = FastAPI()

    @app.post("/protected", dependencies=[Depends(require_admin)])
    async def protected() -> dict[str, str]:
        return {"ok": "true"}

    yield app

    if prev is not None:
        os.environ["ADMIN_TOKEN"] = prev
    get_settings.cache_clear()  # type: ignore[attr-defined]


# ───────────────────── 守卫行为测试 ─────────────────────


async def test_missing_token_returns_401(app_with_admin: FastAPI) -> None:
    """无 X-Admin-Token 头 → 401。"""
    transport = ASGITransport(app=app_with_admin)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/protected")
    assert r.status_code == 401
    assert "admin token required" in r.text


async def test_wrong_token_returns_401(app_with_admin: FastAPI) -> None:
    """错 X-Admin-Token 头 → 401。"""
    transport = ASGITransport(app=app_with_admin)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/protected", headers={"X-Admin-Token": "wrong-token"})
    assert r.status_code == 401


async def test_correct_token_returns_200(app_with_admin: FastAPI) -> None:
    """正确 X-Admin-Token 头 → 200。"""
    # 读 fixture 设的 ADMIN_TOKEN
    expected = get_settings().admin_token
    assert expected is not None

    transport = ASGITransport(app=app_with_admin)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/protected", headers={"X-Admin-Token": expected})
    assert r.status_code == 200
    assert r.json() == {"ok": "true"}


async def test_get_endpoint_bypasses_guard(app_with_admin: FastAPI) -> None:
    """GET 端点不需要 token。"""
    transport = ASGITransport(app=app_with_admin)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/public")
    assert r.status_code == 200


async def test_dev_mode_no_token_required(app_dev_mode: FastAPI) -> None:
    """无 ADMIN_TOKEN env 时 dev 模式：写端点无需 token。"""
    transport = ASGITransport(app=app_dev_mode)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/protected")
    assert r.status_code == 200
