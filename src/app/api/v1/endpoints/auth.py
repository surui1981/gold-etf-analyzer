"""认证端点（V0.75.0）：注册 / 登录 / 登出 / 当前用户 / 状态 / 改密。

统一错误契约
------------
所有认证类失败都以 ``HTTPException(status, detail={"code": ..., "message": ...})``
返回，与中间件的 401 / 403 体保持同构：

- ``code`` —— 稳定的机器可读标识（前端据此查 i18n 字典，实现三语错误提示）；
- ``message`` —— 服务端中文兜底文案（字典缺失时直接展示）。

**为什么 detail 用 dict 而不是字符串**：若只给字符串，前端无法区分
「密码太弱」与「账号被锁」，只能提示同一句话；给 ``code`` 后可精确引导
（高亮密码框 / 提示等待时长）。这是本项目内第一次用 dict detail，
与既有 ``detail: str`` 端点并存不冲突（客户端统一按 ``detail`` 字段读取即可）。
"""

from __future__ import annotations

import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.dependencies import (
    get_auth_service,
    get_current_session_id,
    get_db_session,
    get_user_repository,
    require_user,
)
from app.middleware.auth import client_ip
from app.middleware.trace import get_current_trace_id
from app.models.user import User, utcnow
from app.repositories.password_reset import PasswordResetTokenRepository
from app.repositories.telemetry import TelemetryRepository, _event_to_model
from app.repositories.user import SessionRepository, UserRepository
from app.schemas.auth import (
    AuthSessionOut,
    AuthStatusOut,
    ChangePasswordIn,
    ChangePasswordOut,
    ForgotPasswordIn,
    ForgotPasswordOut,
    LoginIn,
    LogoutOut,
    RegisterIn,
    ResetPasswordIn,
    ResetPasswordOut,
    UserOut,
)
from app.services.auth import AuthError, AuthService, IssuedSession
from app.services.notify import NotifierFactory
from app.services.password_reset import InvalidResetTokenError, PasswordResetService
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# 认证类错误的 HTTP 状态映射。用 code → status 而非「异常类 → status」，
# 是为了让新增错误码时只需改这一张表（异常类只负责 code 语义）。
# 422 直接写字面量：Starlette 新旧版本对「不可处理实体」的常量名不同
# （HTTP_422_UNPROCESSABLE_ENTITY 已弃用 → HTTP_422_UNPROCESSABLE_CONTENT），
# 写常量会绑定 starlette 版本并触发 StarletteDeprecationWarning，字面量最稳。
_STATUS_BY_CODE: dict[str, int] = {
    "invalid_credentials": status.HTTP_401_UNAUTHORIZED,
    "login_throttled": status.HTTP_429_TOO_MANY_REQUESTS,
    "registration_disabled": status.HTTP_403_FORBIDDEN,
    "account_disabled": status.HTTP_403_FORBIDDEN,
    "email_taken": status.HTTP_409_CONFLICT,
    "password_weak": 422,
    "email_invalid": 422,
    # V0.75.3找回密码
    "reset_token_invalid": 400,
    "reset_throttled": status.HTTP_429_TOO_MANY_REQUESTS,
}

LOGIN_PAGE = "/static/login.html"
ERROR_HEADERS = {"X-Auth-Required": "1"}


def _http_error(exc: AuthError) -> HTTPException:
    """把服务层业务异常转成 HTTP 异常（保留 code 供前端分支）。"""
    return HTTPException(
        status_code=_STATUS_BY_CODE.get(exc.code, status.HTTP_400_BAD_REQUEST),
        detail={"code": exc.code, "message": exc.message},
        headers=ERROR_HEADERS,
    )


def _set_session_cookie(response: Response, settings: Settings, issued: IssuedSession) -> None:
    """下发会话 cookie。

    ``HttpOnly`` 阻断 XSS 窃取；``SameSite=Strict`` 让跨站请求根本不携带它
    （CSRF 的第一道防线，token 校验是第二道）；``Secure`` 由配置决定
    （本地 http 下置 true 会导致浏览器不回传，故 dev 默认 false）。
    """
    ttl = int((issued.expires_at - utcnow()).total_seconds())
    response.set_cookie(
        key=settings.session_cookie_name,
        value=issued.session_id,
        max_age=max(60, ttl),
        httponly=True,
        samesite="strict",
        secure=bool(settings.session_cookie_secure),
        path="/",
    )


def _clear_session_cookie(response: Response, settings: Settings) -> None:
    """清除会话 cookie（登出）。属性须与下发时一致，否则部分浏览器不覆盖。"""
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        httponly=True,
        samesite="strict",
        secure=bool(settings.session_cookie_secure),
    )


async def _track(
    db: AsyncSession,
    *,
    event_type: str,
    payload: dict[str, object],
) -> None:
    """服务端埋点（登录成功 / 失败）。

    **best-effort**：埋点失败绝不影响登录本身（吞掉异常）。
    事件类型须在 ``services.telemetry.ALLOWED_EVENT_TYPES`` 白名单内；
    这里直接走 ``_event_to_model`` 落库，绕开「前端白名单校验」那一层
    （服务端事件天然可信，且 ``sendBeacon`` 的批量语义对单条事件是负担）。
    """
    try:
        repo = TelemetryRepository(db)
        await repo.insert_batch(
            [
                _event_to_model(
                    event_type=event_type,
                    page=LOGIN_PAGE,
                    payload=payload,
                    session_id="-",
                    trace_id=get_current_trace_id(),
                )
            ]
        )
    except Exception:  # 观测数据，不允许影响认证主流程
        pass


@router.get("/status", response_model=AuthStatusOut, summary="认证状态（匿名可访问）")
async def auth_status(
    request: Request,
    users: UserRepository = Depends(get_user_repository),
    settings: Settings = Depends(get_settings),
) -> AuthStatusOut:
    """返回「要不要登录 / 能不能注册 / 我登录了吗 / 有几个用户」。

    前端 ``auth.js`` 在每页加载时调用它：``auth_enabled=true`` 且未登录 →
    跳转登录页；``user_count=0`` → 引导进入「初始化管理员」流程。
    """
    user = getattr(request.state, "user", None)
    try:
        user_count = await users.count()
    except Exception:  # 表缺失等异常不应让登录页打不开
        user_count = 0
    return AuthStatusOut(
        auth_enabled=bool(settings.auth_enabled),
        allow_registration=bool(settings.allow_registration),
        authenticated=user is not None,
        user_count=user_count,
    )


@router.post("/register", response_model=AuthSessionOut, summary="注册（首个用户成为管理员）")
async def register(
    payload: RegisterIn,
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db_session),
) -> AuthSessionOut:
    """注册并**直接登录**（省去「注册成功请再登录一次」的来回）。

    库中无任何用户时，本端点会创建 ``role=owner`` 的初始管理员。
    """
    ip = client_ip(request.scope, trust_proxy=settings.trust_proxy_headers)
    try:
        user = await service.register(
            email=payload.email,
            password=payload.password,
            display_name=payload.display_name,
        )
        _, issued = await service.login(
            email=user.email,
            password=payload.password,
            user_agent=request.headers.get("user-agent"),
            ip=ip,
        )
    except AuthError as exc:
        await _track(
            db, event_type="login_fail", payload={"reason": exc.code, "action": "register"}
        )
        raise _http_error(exc) from exc

    _set_session_cookie(response, settings, issued)
    await _track(db, event_type="login_success", payload={"action": "register", "role": user.role})
    return AuthSessionOut(user=UserOut.model_validate(user), expires_at=issued.expires_at)


@router.post("/login", response_model=AuthSessionOut, summary="登录")
async def login(
    payload: LoginIn,
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db_session),
) -> AuthSessionOut:
    """校验凭据并签发会话 cookie。"""
    ip = client_ip(request.scope, trust_proxy=settings.trust_proxy_headers)
    try:
        user, issued = await service.login(
            email=payload.email,
            password=payload.password,
            user_agent=request.headers.get("user-agent"),
            ip=ip,
        )
    except AuthError as exc:
        await _track(
            db,
            event_type="login_fail",
            payload={"reason": exc.code, "action": "login", "ip": ip or "-"},
        )
        raise _http_error(exc) from exc

    _set_session_cookie(response, settings, issued)
    await _track(db, event_type="login_success", payload={"action": "login", "role": user.role})
    return AuthSessionOut(user=UserOut.model_validate(user), expires_at=issued.expires_at)


@router.post("/logout", response_model=LogoutOut, summary="登出（撤销当前会话）")
async def logout(
    response: Response,
    session_id: str | None = Depends(get_current_session_id),
    service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
) -> LogoutOut:
    """撤销当前会话并清除 cookie。

    **幂等**：已登出 / 会话已过期时返回 ``revoked=false`` 而非报错 ——
    前端重复点「退出」或在两个标签页同时退出是常态。
    """
    revoked = await service.logout(session_id)
    _clear_session_cookie(response, settings)
    return LogoutOut(revoked=revoked)


@router.get("/me", response_model=UserOut, summary="当前登录用户")
async def me(user: User = Depends(require_user)) -> UserOut:
    """返回当前登录用户信息（不含密码哈希）。"""
    return UserOut.model_validate(user)


@router.post("/change-password", response_model=ChangePasswordOut, summary="修改密码")
async def change_password(
    payload: ChangePasswordIn,
    user: User = Depends(require_user),
    session_id: str | None = Depends(get_current_session_id),
    service: AuthService = Depends(get_auth_service),
) -> ChangePasswordOut:
    """改密并踢出其他设备（当前设备保持登录）。

    「保留当前设备」是刻意的：若把当前会话也撤销，用户点完确定就被弹回登录页，
    体感像「改密失败」。其余会话全撤，才能让「密码泄露后改密」真正止血。
    """
    try:
        revoked = await service.change_password(
            user,
            current_password=payload.current_password,
            new_password=payload.new_password,
            keep_session_id=session_id,
        )
    except AuthError as exc:
        raise _http_error(exc) from exc
    return ChangePasswordOut(revoked_sessions=revoked)


# ─────────────── V0.75.3 找回密码 ───────────────

# 找回密码的**邮件申请限流**：滑动窗口 + 锁定。
# ⚠ 为什么必须单独限流：登录限流防的是「撞密码」，而这里防的是
# **邮件炸弹** —— 攻击者可用同一 IP 连续申请，把受害者邮箱变成垃圾邮件收件箱。
# ⚠ 限流失败**也返回 accepted=True**（不泄露，且限流本身不该让攻击者
# 知道「你已被限流」）；只在服务端日志里记录。
_RESET_THROTTLE_MAX = 5  # 每窗口最多申请次数
_RESET_THROTTLE_WINDOW_S = 600  # 窗口 10 分钟
_reset_hits: dict[str, list[float]] = {}
_reset_lock: threading.Lock = threading.Lock()


def _reset_throttled(key: str) -> bool:
    """滑动窗口判定；命中则登记一次。仅进程内（与 ``LoginThrottle`` 同级别）。"""
    now = time.monotonic()
    with _reset_lock:
        hits = [t for t in _reset_hits.get(key, []) if now - t < _RESET_THROTTLE_WINDOW_S]
        if len(hits) >= _RESET_THROTTLE_MAX:
            _reset_hits[key] = hits
            return True
        hits.append(now)
        _reset_hits[key] = hits
        return False


@router.post(
    "/forgot-password",
    response_model=ForgotPasswordOut,
    summary="申请重置密码（匿名可访问；响应恒定，不泄露账号存在性）",
)
async def forgot_password(
    payload: ForgotPasswordIn,
    request: Request,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_db_session),
) -> ForgotPasswordOut:
    """签发重置 token 并（尽力）发邮件。

    ⚠⚠ **响应恒定**：无论邮箱是否存在、是否被禁用、SMTP 是否可用，
    都返回同一个结构与同一段文案。若这里改成「该邮箱不存在」，
    就等于开放了「哪些邮箱在本系统注册过」的枚举接口。

    ⚠ 限流命中也返回同一结构（否则攻击者能反推自己是否被限流）。
    """
    ip = client_ip(request.scope) or "unknown"
    if _reset_throttled(ip):
        logger.info("forgot-password: 命中邮件限流 ip=%s", ip)
        return ForgotPasswordOut(accepted=True, message="如该邮箱已注册，我们已发送重置邮件")

    users = UserRepository(session)
    svc = PasswordResetService(
        users,
        SessionRepository(session),
        PasswordResetTokenRepository(session),
        settings=settings,
    )
    # ⚠ 直接复用 NotifierFactory —— 它已封装「SMTP_HOST 缺失→ None」的判定，
    # 另写一份配置解析必然与notify 的行为漂移。
    notifier = NotifierFactory.create("email")
    await svc.request_reset(
        email=payload.email,
        smtp_notifier=notifier,
        request_ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
    # ⚠ 无论实际投递结果如何，对外都是同一句
    return ForgotPasswordOut(accepted=True, message="如该邮箱已注册，我们已发送重置邮件")


@router.post(
    "/reset-password",
    response_model=ResetPasswordOut,
    summary="用 token 设置新密码（匿名可访问）",
)
async def reset_password(
    payload: ResetPasswordIn,
    session: AsyncSession = Depends(get_db_session),
) -> ResetPasswordOut:
    """用邮件里的 token 设置新密码，并踢出该用户全部会话。

    ⚠ 三类失败（token 不存在 / 已用 / 已过期）**一律 400 +同一 code** ——
    区分它们等于告诉攻击者「这个 token 曾经有效」。
    """
    users = UserRepository(session)
    svc = PasswordResetService(
        users,
        SessionRepository(session),
        PasswordResetTokenRepository(session),
    )
    try:
        revoked = await svc.reset_password(token=payload.token, new_password=payload.new_password)
    except InvalidResetTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "reset_token_invalid", "message": str(exc)},
            headers=ERROR_HEADERS,
        ) from exc
    except AuthError as exc:
        # 密码策略不通过（弱密码）
        raise _http_error(exc) from exc
    return ResetPasswordOut(reset=True, sessions_revoked=revoked)
