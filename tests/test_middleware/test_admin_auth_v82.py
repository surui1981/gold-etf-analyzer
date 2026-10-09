"""V0.82 admin session cookie + 双通道鉴权测试。

新增覆盖：
1. ``require_admin_session`` 接受 X-Admin-Token header（旧通道）
2. ``require_admin_session`` 接受 ``pm_admin_session`` cookie（新通道）
3. 错误签名 / 过期 cookie 仍 401
4. 单用户模式（AUTH_ENABLED=false）整体豁免
5. ``issue_admin_session_cookie_value`` 与 ``verify_admin_session_cookie`` 往返一致
6. cookie 篡改（改 issued_at）→ 验签失败
"""

from __future__ import annotations

import secrets
import time
from collections.abc import AsyncIterator

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.middleware.admin_auth import (
    ADMIN_SESSION_COOKIE,
    ADMIN_SESSION_TTL_SECONDS,
    issue_admin_session_cookie_value,
    require_admin_session,
    verify_admin_session_cookie,
)

# ───────────────────── fixtures ─────────────────────


@pytest.fixture
def app_with_admin_v82(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FastAPI]:
    """多用户模式 + ADMIN_TOKEN 已设 + require_admin_session 守卫。"""
    token = secrets.token_urlsafe(16)
    monkeypatch.setenv("ADMIN_TOKEN", token)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    app = FastAPI()

    @app.post("/protected", dependencies=[Depends(require_admin_session)])
    async def protected() -> dict[str, str]:
        return {"ok": "true"}

    yield app

    get_settings.cache_clear()  # type: ignore[attr-defined]


@pytest.fixture
def app_single_user_mode(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FastAPI]:
    """V0.82 关键场景：AUTH_ENABLED=false（单用户）+ ADMIN_TOKEN 已设（LAN 默认）。

    行为：admin 鉴权整体豁免（无需任何 token/cookie）。
    """
    token = secrets.token_urlsafe(16)
    monkeypatch.setenv("ADMIN_TOKEN", token)
    monkeypatch.setenv("AUTH_ENABLED", "false")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    app = FastAPI()

    @app.post("/protected", dependencies=[Depends(require_admin_session)])
    async def protected() -> dict[str, str]:
        return {"ok": "true"}

    yield app

    get_settings.cache_clear()  # type: ignore[attr-defined]


# ───────────────────── 双通道鉴权 ─────────────────────


async def test_header_channel_still_works(app_with_admin_v82: FastAPI) -> None:
    """旧通道：X-Admin-Token 头仍可通过（向后兼容）。"""
    expected = get_settings().admin_token
    assert expected is not None

    transport = ASGITransport(app=app_with_admin_v82)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/protected", headers={"X-Admin-Token": expected})
    assert r.status_code == 200


async def test_cookie_channel_passes(app_with_admin_v82: FastAPI) -> None:
    """新通道：pm_admin_session cookie 通过。"""
    cookie_value = issue_admin_session_cookie_value()

    transport = ASGITransport(app=app_with_admin_v82)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/protected", cookies={ADMIN_SESSION_COOKIE: cookie_value})
    assert r.status_code == 200


async def test_dual_channel_either_passes(app_with_admin_v82: FastAPI) -> None:
    """两通道都带 → 也通过（不必冲突）。"""
    expected = get_settings().admin_token
    cookie_value = issue_admin_session_cookie_value()

    transport = ASGITransport(app=app_with_admin_v82)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/protected",
            headers={"X-Admin-Token": expected},
            cookies={ADMIN_SESSION_COOKIE: cookie_value},
        )
    assert r.status_code == 200


async def test_no_auth_returns_401(app_with_admin_v82: FastAPI) -> None:
    """两通道都没带 → 401。"""
    transport = ASGITransport(app=app_with_admin_v82)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/protected")
    assert r.status_code == 401


async def test_wrong_cookie_signature_fails(app_with_admin_v82: FastAPI) -> None:
    """签名错的 cookie → 401。"""
    fake_cookie = "Zm9v.YWJj"  # 任意 base64 但签名错的 payload

    transport = ASGITransport(app=app_with_admin_v82)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/protected", cookies={ADMIN_SESSION_COOKIE: fake_cookie})
    assert r.status_code == 401


async def test_expired_cookie_fails(app_with_admin_v82: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    """过期 cookie（issued_at 早于 30 天前）→ 验签失败。"""

    from app.middleware.admin_auth import _b64url_encode, _sign_session

    admin_token = get_settings().admin_token
    assert admin_token is not None

    # 构造 31 天前的 issued_at
    expired_at = int(time.time()) - ADMIN_SESSION_TTL_SECONDS - 86400
    expired_sig = _sign_session(expired_at, admin_token)
    expired_cookie = f"{_b64url_encode(str(expired_at).encode('ascii'))}.{expired_sig}"

    transport = ASGITransport(app=app_with_admin_v82)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/protected", cookies={ADMIN_SESSION_COOKIE: expired_cookie})
    assert r.status_code == 401


async def test_cookie_signed_with_different_secret_fails(
    app_with_admin_v82: FastAPI,
) -> None:
    """用别的 token 签的 cookie（同一 issued_at）→ 验签失败。"""
    fake_admin_token = secrets.token_urlsafe(16)  # 与 app 设的不同

    from app.middleware.admin_auth import _b64url_encode, _sign_session

    issued_at = int(time.time())
    sig = _sign_session(issued_at, fake_admin_token)
    fake_cookie = f"{_b64url_encode(str(issued_at).encode('ascii'))}.{sig}"

    transport = ASGITransport(app=app_with_admin_v82)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/protected", cookies={ADMIN_SESSION_COOKIE: fake_cookie})
    assert r.status_code == 401


# ───────────────────── V0.82 核心：单用户模式豁免 ─────────────────────


async def test_single_user_mode_skips_admin(app_single_user_mode: FastAPI) -> None:
    """**V0.82 核心修复**：AUTH_ENABLED=false ⇒ 写端点无 admin 校验。

    即便 .env.prod 设了 ADMIN_TOKEN，单用户 LAN 部署也不会因为忘了设
    X-Admin-Token 而 401 —— 直接通过。
    """
    transport = ASGITransport(app=app_single_user_mode)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 无 token 无 cookie
        r = await client.post("/protected")
    assert r.status_code == 200


async def test_single_user_mode_get_admin_token_returns_none(
    app_single_user_mode: FastAPI,
) -> None:
    """get_admin_token() 在单用户模式下返回 None。"""
    from app.dependencies import get_admin_token

    assert get_admin_token() is None


# ───────────────────── issue / verify 函数纯单测 ─────────────────────


def test_issue_and_verify_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    """签发 → 校验 → 一致。"""
    monkeypatch.setenv("ADMIN_TOKEN", "test-secret-for-v82")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    cookie_value = issue_admin_session_cookie_value()
    assert verify_admin_session_cookie(cookie_value) is True

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_verify_rejects_empty_or_malformed() -> None:
    """空值 / 格式错误的 cookie → 验签失败（不抛异常）。"""
    assert verify_admin_session_cookie(None) is False
    assert verify_admin_session_cookie("") is False
    assert verify_admin_session_cookie("no-dot-here") is False
    assert verify_admin_session_cookie("only-one-part.") is False
    assert verify_admin_session_cookie(".only-signature") is False


def test_issue_raises_when_no_admin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADMIN_TOKEN 未设时签发 → RuntimeError。"""
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    with pytest.raises(RuntimeError, match="ADMIN_TOKEN 未设置"):
        issue_admin_session_cookie_value()

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_future_timestamp_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """issued_at 超过当前时间 + 60s → 拒绝（防时钟错乱 / 重放未来 token）。"""

    from app.middleware.admin_auth import _b64url_encode, _sign_session

    monkeypatch.setenv("ADMIN_TOKEN", "test-secret")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    admin_token = get_settings().admin_token
    future_ts = int(time.time()) + 3600  # 1 小时后
    sig = _sign_session(future_ts, admin_token)
    future_cookie = f"{_b64url_encode(str(future_ts).encode('ascii'))}.{sig}"

    assert verify_admin_session_cookie(future_cookie) is False

    get_settings.cache_clear()  # type: ignore[attr-defined]
