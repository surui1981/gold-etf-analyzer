"""V0.72.0 P3-b · 管理员守卫中间件；V0.82 扩展为 cookie + header 双通道。

写端点（POST/PUT/DELETE/PATCH）必须满足以下任一鉴权：

1. **Header 通道**：``X-Admin-Token`` 头与 ``ADMIN_TOKEN`` env 匹配（脚本 / CI）。
2. **Cookie 通道**（V0.82 新增）：``pm_admin_session`` cookie 值由 ADMIN_TOKEN
   作密钥 HMAC-SHA256 签名，服务端无状态校验（浏览器 / 桌面端）。

**单用户模式豁免**（V0.82 新增）：``AUTH_ENABLED=false`` ⇒ ``get_admin_token``
返回 None ⇒ 所有 admin 校验 skip。单用户 LAN 部署从此免 token 配置。

设计取舍
--------
- **dev 模式无 admin 守卫**（原行为）：``ADMIN_TOKEN`` env 未设 ⇒ skip。
- **单用户模式无 admin 守卫**（V0.82 新增）：``AUTH_ENABLED=false`` ⇒ skip。
  ⚠ 两条独立判断，避免「单用户模式 + ADMIN_TOKEN 已设」导致 LAN 用户被锁。
- **不是 base-http middleware 而是 Depends**：端点级装饰更精细，中间件形式只做兜底日志。
- **不挂在读端点（GET）**：所有 GET 公开。
- **Cookie 无状态**：服务端不存 session 表，HMAC 签名自带时间戳（30 天 TTL）；
  撤销靠客户端 DELETE 端点或 cookie 过期，不支持「主动吊销」。
- **HttpOnly cookie**：XSS 偷不到，但浏览器 devtools 仍可见 —— LAN 部署无 HTTPS
  时 SameSite=Lax 已足够（CSRF 不跨域）。
- **保留 require_admin**：CI / 脚本仍可只走 header 路径；``require_admin_session``
  是新默认，向后兼容。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, status

from app.dependencies import get_admin_token

# V0.82 admin session cookie 名（与 settings.js / auth.js 共享常量命名约定）
ADMIN_SESSION_COOKIE = "pm_admin_session"

# V0.82 admin session TTL（秒）；30 天，过期需重新设置。
ADMIN_SESSION_TTL_SECONDS = 30 * 24 * 60 * 60


def _compare_token(provided: str, expected: str) -> bool:
    """恒定时间字符串比较，避免时序攻击。"""
    return secrets.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


# ─────────────── V0.82 admin session cookie · HMAC 签名 ───────────────


def _b64url_encode(raw: bytes) -> str:
    """bytes → URL-safe base64（无填充）。"""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    """URL-safe base64（容错填充）。"""
    pad = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sign_session(issued_at: int, secret: str) -> str:
    """HMAC-SHA256(secret, str(issued_at)) → URL-safe base64。"""
    mac = hmac.new(secret.encode("utf-8"), str(issued_at).encode("ascii"), hashlib.sha256).digest()
    return _b64url_encode(mac)


def issue_admin_session_cookie_value() -> str:
    """生成新 admin session cookie 值（``{issued_at}.{signature}``）。

    Returns:
        base64url(issued_at) + "." + base64url(HMAC-SHA256)

    Raises:
        RuntimeError: ADMIN_TOKEN 未设置（单用户模式 / dev 模式不应调用）。
    """
    admin_token = get_admin_token()
    if not admin_token:
        raise RuntimeError(
            "ADMIN_TOKEN 未设置；无法签发 admin session（dev / 单用户模式无需 cookie）"
        )
    issued_at = int(time.time())
    return f"{_b64url_encode(str(issued_at).encode('ascii'))}.{_sign_session(issued_at, admin_token)}"


def verify_admin_session_cookie(raw: str | None) -> bool:
    """校验 ``pm_admin_session`` cookie 值；过期或签名错误返回 False。

    无副作用，不抛异常 —— 调用方决定是否鉴权失败。
    """
    if not raw:
        return False
    admin_token = get_admin_token()
    if not admin_token:
        return False  # ADMIN_TOKEN 未设 ⇒ cookie 无意义 ⇒ 视为无效
    parts = raw.split(".", 1)
    if len(parts) != 2:
        return False
    try:
        issued_at = int(_b64url_decode(parts[0]).decode("ascii"))
    except (ValueError, UnicodeDecodeError, base64.binascii.Error):  # type: ignore[attr-defined]
        return False
    # 过期检查（先于签名检查，避免泄露当前时间）
    if time.time() - issued_at > ADMIN_SESSION_TTL_SECONDS:
        return False
    if issued_at > time.time() + 60:
        return False  # 时钟容差 ±60s 防未来时间戳
    expected_sig = _sign_session(issued_at, admin_token)
    return hmac.compare_digest(parts[1], expected_sig)


# ─────────────── Depends（保留旧 + 新增双通道） ───────────────


async def require_admin(
    x_admin_token: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
    admin_token: str | None = Depends(get_admin_token),
) -> None:
    """**仅**校验 ``X-Admin-Token`` 头（保留 V0.72.0 旧语义）。

    单用户模式 / dev 模式无 ADMIN_TOKEN ⇒ skip（``get_admin_token`` 返回 None）。

    Raises:
        HTTPException 401: 缺 token / token 不匹配

    Examples:
        @router.post(\"/positions\", dependencies=[Depends(require_admin)])
        async def create_position(...): ...
    """
    if admin_token is None:
        # dev 模式或单用户模式无 ADMIN_TOKEN → 跳过校验
        return
    if not x_admin_token or not _compare_token(x_admin_token, admin_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="admin token required",
            headers={"WWW-Authenticate": "X-Admin-Token"},
        )


async def require_admin_session(
    x_admin_token: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
    pm_admin_session: Annotated[str | None, Cookie(alias=ADMIN_SESSION_COOKIE)] = None,
    admin_token: str | None = Depends(get_admin_token),
) -> None:
    """V0.82 双通道校验：``X-Admin-Token`` 头 **或** ``pm_admin_session`` cookie。

    任一通道通过即放行（CI / 脚本走 header，浏览器 / 桌面端走 cookie）。

    单用户模式 / dev 模式无 ADMIN_TOKEN ⇒ skip。

    Raises:
        HTTPException 401: 两通道都未通过

    Examples:
        @router.post(\"/positions\", dependencies=[Depends(require_admin_session)])
        async def create_position(...): ...
    """
    if admin_token is None:
        # dev 模式或单用户模式无 ADMIN_TOKEN → 跳过校验
        return
    # 通道 1：X-Admin-Token header
    if x_admin_token and _compare_token(x_admin_token, admin_token):
        return
    # 通道 2：pm_admin_session cookie（HMAC-SHA256 签名校验）
    if verify_admin_session_cookie(pm_admin_session):
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="admin token required",
        headers={"WWW-Authenticate": "X-Admin-Token, " + ADMIN_SESSION_COOKIE},
    )
