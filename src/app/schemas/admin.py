"""用户管理端点的请求/响应模型（V0.75.3）。

⚠⚠ ``UserAdminOut`` **绝不含 ``password_hash``** —— 与 ``schemas/auth.py`` 的
``UserOut`` 同样的纪律。任何「把ORM 对象直接序列化」的写法都会漏出哈希，
故此处显式声明字段而非用 ``model_config`` 自动转换。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

__all__ = [
    "SetActiveIn",
    "UserAdminOut",
    "UserListOut",
    "UserPasswordResetIn",
    "UserPasswordResetOut",
]


class UserAdminOut(BaseModel):
    """用户管理视图（**不含密码哈希**）。"""

    id: int = Field(..., description="用户 id")
    email: str = Field(..., description="邮箱")
    display_name: str = Field(default="", description="展示名")
    role: str = Field(..., description="角色 owner / member")
    is_active: bool = Field(..., description="False = 已禁用（登录被拒）")
    created_at: datetime | None = Field(default=None, description="创建时间")
    last_login_at: datetime | None = Field(default=None, description="最近登录时间")
    # ⚠ 用于前端把「我自己」标出来并**禁用操作按钮** ——
    # 但真正的防护在服务端（禁止操作自己），前端只是提示。
    is_self: bool = Field(default=False, description="是否为当前登录用户本人")


class UserListOut(BaseModel):
    """用户列表响应。"""

    users: list[UserAdminOut] = Field(..., description="全部用户（按 id 升序）")
    total: int = Field(..., description="用户总数")
    owner_count: int = Field(..., description="启用中的所有者数量（供前端警示）")


class UserPasswordResetIn(BaseModel):
    """所有者重置某用户密码的请求体。"""

    new_password: str = Field(..., min_length=1, max_length=72, description="新密码")


class UserPasswordResetOut(BaseModel):
    """重置密码结果。"""

    ok: bool = Field(..., description="是否成功")
    sessions_revoked: int = Field(..., description="被撤销的会话数")


class SetActiveIn(BaseModel):
    """启用/ 禁用请求体。"""

    is_active: bool = Field(..., description="True=启用，False=禁用（软删除）")
