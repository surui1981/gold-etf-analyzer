"""认证 Schema（V0.75.0）。

约定：**入参宽松 + 服务层裁决**。Schema 只做「形状 + 长度」这一层防御
（拦住明显畸形请求，避免把超长串送进 bcrypt），
邮箱格式、密码强度、锁定等**业务判定一律在 :mod:`app.services.auth`**，
保证 HTTP 层与后台任务共用同一套规则。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# 与服务层常量保持一致的长度上限（此处只做「不至于打爆内存」的兜底）
EMAIL_MAX = 255
PASSWORD_MAX = 200
DISPLAY_NAME_MAX = 64


class RegisterIn(BaseModel):
    """注册请求。"""

    email: str = Field(..., min_length=3, max_length=EMAIL_MAX, description="登录邮箱")
    password: str = Field(
        ..., min_length=1, max_length=PASSWORD_MAX, description="密码（策略由服务层校验）"
    )
    display_name: str = Field(default="", max_length=DISPLAY_NAME_MAX, description="展示名")


class LoginIn(BaseModel):
    """登录请求。"""

    email: str = Field(..., min_length=1, max_length=EMAIL_MAX, description="登录邮箱")
    password: str = Field(..., min_length=1, max_length=PASSWORD_MAX, description="密码")


class ChangePasswordIn(BaseModel):
    """改密请求。"""

    current_password: str = Field(
        ..., min_length=1, max_length=PASSWORD_MAX, description="当前密码"
    )
    new_password: str = Field(..., min_length=1, max_length=PASSWORD_MAX, description="新密码")


class UserOut(BaseModel):
    """用户公开信息（**绝不含 password_hash**）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str = ""
    role: str = "member"
    created_at: datetime | None = None
    last_login_at: datetime | None = None


class AuthStatusOut(BaseModel):
    """认证总开关状态（前端据此决定是否跳登录页）。

    即使匿名也可访问 —— 它不泄露任何用户信息，只回答「本站要不要登录」。
    """

    auth_enabled: bool = Field(..., description="是否启用登录（AUTH_ENABLED）")
    allow_registration: bool = Field(..., description="是否允许自助注册")
    authenticated: bool = Field(..., description="当前请求是否已登录")
    user_count: int = Field(
        default=0, description="已注册用户数（0 = 尚未初始化，首个注册者成为管理员）"
    )


class AuthSessionOut(BaseModel):
    """登录 / 注册成功后的返回体。"""

    user: UserOut
    expires_at: datetime = Field(..., description="会话绝对过期时间（UTC）")


class LogoutOut(BaseModel):
    """登出结果。"""

    revoked: bool = Field(..., description="是否确实撤销了一个会话")


class ChangePasswordOut(BaseModel):
    """改密结果。"""

    revoked_sessions: int = Field(..., description="被踢下线的其他设备会话数")


__all__ = [
    "AuthSessionOut",
    "AuthStatusOut",
    "ChangePasswordIn",
    "ChangePasswordOut",
    "LoginIn",
    "LogoutOut",
    "RegisterIn",
    "UserOut",
]
