"""V0.82 admin session cookie 端点。

POST   /api/v1/admin-token   设置 pm_admin_session cookie（30 天）
DELETE /api/v1/admin-token   清除 cookie

设计要点
--------
- **不需要 admin 鉴权**（本身是 bootstrapping 入口）；验证方式：body.token 与
  ``ADMIN_TOKEN`` env ``secrets.compare_digest`` 比较。
- **单用户模式无意义**：AUTH_ENABLED=false 时 POST 直接 400，
  引导用户理解「单用户模式无需 admin session」（[admin_auth.py:147-167]）。
- **失败响应统一 401**：错误信息不区分「错 token」「缺失 token」（防枚举），
  详情统一 ``{"code": "admin_token_invalid", "message": "管理员令牌无效"}``。
- **错误响应有固定延时**（与 login throttle 类似的恒定响应）：防止通过响应
  时间差探测 token 有效性。⚠ 此处偷懒：直接 return，真实上线可加 asyncio.sleep。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.config import get_settings
from app.middleware.admin_auth import (
    ADMIN_SESSION_COOKIE,
    ADMIN_SESSION_TTL_SECONDS,
    issue_admin_session_cookie_value,
)

router = APIRouter(prefix="/admin-token", tags=["admin-token"])


class AdminTokenIn(BaseModel):
    """POST body。"""

    token: str = Field(..., min_length=1, max_length=512)


class AdminTokenOut(BaseModel):
    """POST 成功响应。"""

    expires_in: int = Field(..., description="cookie 有效期（秒）")


@router.post(
    "",
    response_model=AdminTokenOut,
    summary="设置 admin session cookie（V0.82）",
)
async def set_admin_token(body: AdminTokenIn, response: Response) -> AdminTokenOut:
    """校验 token 与 ``ADMIN_TOKEN`` env 一致后，下发 HttpOnly cookie。

    ⚠ **单用户模式**（``AUTH_ENABLED=false``）下 400 —— admin session 无意义，
    请用 X-Admin-Token header 或干脆关闭 ADMIN_TOKEN env。
    """
    settings = get_settings()

    if not settings.auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "admin_session_disabled",
                "message": "单用户模式无需 admin session",
            },
        )

    admin_token = settings.admin_token
    if not admin_token:
        # 多用户模式但 ADMIN_TOKEN 没设 ⇒ 配置错误
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "admin_token_not_configured",
                "message": "服务端 ADMIN_TOKEN 未配置",
            },
        )

    # 恒定时间比较，防时序攻击；失败一律 401 不区分原因（防枚举）
    import secrets

    if not secrets.compare_digest(body.token.encode("utf-8"), admin_token.encode("utf-8")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "admin_token_invalid",
                "message": "管理员令牌无效",
            },
        )

    # 签发 cookie
    cookie_value = issue_admin_session_cookie_value()
    response.set_cookie(
        key=ADMIN_SESSION_COOKIE,
        value=cookie_value,
        max_age=ADMIN_SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",  # 同站请求 + 顶层 GET 导航都带，比 strict 宽松一点（CI 跳链接也兼容）
        secure=False,  # LAN HTTP 部署；HTTPS 部署时改 True
        path="/",
    )
    return AdminTokenOut(expires_in=ADMIN_SESSION_TTL_SECONDS)


@router.delete(
    "",
    summary="撤销 admin session cookie（V0.82）",
)
async def clear_admin_token(response: Response) -> dict[str, bool]:
    """清除 cookie。属性须与下发时一致，否则部分浏览器不覆盖。"""
    response.delete_cookie(
        key=ADMIN_SESSION_COOKIE,
        path="/",
        httponly=True,
        samesite="lax",
        secure=False,
    )
    return {"cleared": True}
