"""用户管理端点（V0.75.3）：列用户 / 改密 / 启用禁用 / 软删除。

⚠ 鉴权：全部走 :func:`app.dependencies.require_owner`（**角色**鉴权），
**不是** :func:`app.middleware.admin_auth.require_admin`（服务级 token 鉴权）
—— 后者回答「这个调用方能否写」，前者回答「**登录的这个人**能否管别人」。
用户管理必须知道操作者是谁，否则无法实现「禁止操作自己」这类防自锁规则。
详见 :func:`app.dependencies.require_owner` 的 docstring。

⚠ **所有防自锁校验都在服务端**（:mod:`app.services.user_admin`）。
前端禁用按钮只是提示 —— 直接打 API 能绕过后者，绕不过前者。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db_session, require_owner
from app.models.user import ROLE_OWNER, User
from app.repositories.user import SessionRepository, UserRepository
from app.schemas.admin import (
    SetActiveIn,
    UserAdminOut,
    UserListOut,
    UserPasswordResetIn,
    UserPasswordResetOut,
)
from app.services.auth import AuthError
from app.services.user_admin import UserAdminService, UserManagementError
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/admin/users", tags=["admin"])

# 业务错误 → HTTP 状态映射。
# ⚠「不能操作自己 / 最后一个所有者」用 **409 Conflict** 而非 400：
# 400 表示「请求格式错」，而这里是「请求格式正确但当前状态不允许」，
# 前端据此可以提示用户换个人操作，而不是笼统地说「参数错误」。
_STATUS_BY_CODE: dict[str, int] = {
    "user_not_found": status.HTTP_404_NOT_FOUND,
    "cannot_disable_self": status.HTTP_409_CONFLICT,
    "cannot_delete_self": status.HTTP_409_CONFLICT,
    "cannot_reset_own_password": status.HTTP_409_CONFLICT,
    "last_owner_guard": status.HTTP_409_CONFLICT,
}


def _svc(session: AsyncSession) -> UserAdminService:
    users = UserRepository(session)
    return UserAdminService(users, SessionRepository(session))


def _http_error(exc: UserManagementError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS_BY_CODE.get(exc.code, status.HTTP_400_BAD_REQUEST),
        detail={"code": exc.code, "message": exc.message},
    )


def _to_out(user: User, *, actor_id: int) -> UserAdminOut:
    """ORM → 响应模型。

    ⚠ **显式逐字段映射**，不用 ``model_config`` 自动转换 ——
    自动转换会把 ``password_hash`` 一并带出去（ORM 上它是普通属性）。
    """
    return UserAdminOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name or "",
        role=user.role,
        is_active=bool(user.is_active),
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        is_self=(user.id == actor_id),
    )


@router.get("", response_model=UserListOut, summary="用户列表（仅所有者）")
async def list_users(
    actor: User = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> UserListOut:
    """列出全部用户。

    ⚠ 响应带 ``is_self`` 标记，供前端把「我自己」标出并禁用操作按钮
    —— 但**防护仍在服务端**，前端只是提示。
    """
    svc = _svc(session)
    users = await svc.list_users()
    return UserListOut(
        users=[_to_out(u, actor_id=actor.id) for u in users],
        total=len(users),
        owner_count=sum(1 for u in users if u.role == ROLE_OWNER and u.is_active),
    )


@router.post(
    "/{user_id}/reset-password",
    response_model=UserPasswordResetOut,
    summary="重置某用户密码（仅所有者；不能对自己用）",
)
async def admin_reset_password(
    user_id: int,
    payload: UserPasswordResetIn,
    actor: User = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> UserPasswordResetOut:
    """重置目标用户密码并撤销其全部会话。

    ⚠ 不能对自己用这个端点（``409``）—— 自助改密请用
    ``POST /auth/change-password``（那条路径会验证当前密码并保留当前设备）。
    """
    svc = _svc(session)
    try:
        revoked = await svc.reset_password(
            actor=actor, user_id=user_id, new_password=payload.new_password
        )
    except UserManagementError as exc:
        raise _http_error(exc) from exc
    except AuthError as exc:
        # 密码策略不通过
        raise HTTPException(
            status_code=422, detail={"code": exc.code, "message": exc.message}
        ) from exc
    return UserPasswordResetOut(ok=True, sessions_revoked=revoked)


@router.post(
    "/{user_id}/set-active",
    response_model=UserPasswordResetOut,
    summary="启用/禁用用户（仅所有者；不能停用自己）",
)
async def admin_set_active(
    user_id: int,
    payload: SetActiveIn,
    actor: User = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> UserPasswordResetOut:
    """启用 / 禁用（软删除）用户。

    ⚠ 「禁用」与「删除」是**同一条路径**（``is_active=False`` + 撤销全部会话），
    **业务数据保留在原 user_id 下不改写**。理由见
    :mod:`app.services.user_admin` 的模块 docstring。
    """
    svc = _svc(session)
    try:
        revoked = await svc.set_active(actor=actor, user_id=user_id, is_active=payload.is_active)
    except UserManagementError as exc:
        raise _http_error(exc) from exc
    return UserPasswordResetOut(ok=True, sessions_revoked=revoked)


@router.delete(
    "/{user_id}",
    response_model=UserPasswordResetOut,
    summary="软删除用户（仅所有者；不能删除自己）",
)
async def admin_delete_user(
    user_id: int,
    request: Request,
    actor: User = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> UserPasswordResetOut:
    """软删除：禁用 + 撤销全部会话，**数据保留**。

    ⚠ ``DELETE`` 语义在此**不是**「抹掉」而是「停用」——
    可恢复（把 ``is_active`` 置回 True 即可，数据原样还在）。
    这一点已在服务层 docstring 与本函数摘要里写明，避免调用方误以为数据已丢。
    """
    svc = _svc(session)
    try:
        revoked = await svc.soft_delete(actor=actor, user_id=user_id)
    except UserManagementError as exc:
        raise _http_error(exc) from exc
    return UserPasswordResetOut(ok=True, sessions_revoked=revoked)
