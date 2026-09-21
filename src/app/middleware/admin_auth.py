"""V0.72.0 P3-b：管理员守卫中间件。

写端点（POST/PUT/DELETE/PATCH）必须带 ``X-Admin-Token`` 头且与 ``ADMIN_TOKEN`` 环境变量
``secrets.compare_digest`` 匹配。无 ``ADMIN_TOKEN`` env 时 **skip 校验**（dev 友好）。

设计取舍
--------
- **dev 模式无 admin 守卫**：避免本地开发时频繁贴 token 干扰体验。生产部署（``APP_ENV=prod``）
  由运维确保 ``.env.prod`` 必含 ``ADMIN_TOKEN``，否则 main.py 启动期 warning（不强制 fail，
  留给运维按需检查）。
- **不是 base-http middleware 而是 Depends**：在端点级别用 ``Depends(require_admin)``
  装饰更精细的端点。中间件形式（粗粒度）只做兜底日志。
- **不挂在读端点（GET）**：所有 GET 公开（趋势页、新闻等只读）；写端点（positions / accounts /
  backtest / settings / push/subscribe 等）才需要守卫。
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.dependencies import get_admin_token


def _compare_token(provided: str, expected: str) -> bool:
    """恒定时间字符串比较，避免时序攻击。"""
    return secrets.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


async def require_admin(
    x_admin_token: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
    admin_token: str | None = Depends(get_admin_token),
) -> None:
    """写端点 Depends：要求 ``X-Admin-Token`` 头与 ``ADMIN_TOKEN`` env 匹配。

    Args:
        x_admin_token: 客户端请求头中的 token
        admin_token: 由依赖注入工厂传入的 ``settings.admin_token``（None 时 skip）

    Raises:
        HTTPException 401: 缺 token / token 不匹配

    Examples:
        @router.post(\"/positions\", dependencies=[Depends(require_admin)])
        async def create_position(...): ...
    """
    if admin_token is None:
        # dev 模式无 ADMIN_TOKEN → 跳过校验
        return
    if not x_admin_token or not _compare_token(x_admin_token, admin_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="admin token required",
            headers={"WWW-Authenticate": "X-Admin-Token"},
        )
