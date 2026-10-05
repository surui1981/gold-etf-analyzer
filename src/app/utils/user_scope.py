"""请求级 ``user_id`` 上下文 + 仓储层解析器（V0.75.2 数据隔离）。

为什么单独建这个模块
--------------------
``user_id`` 的 contextvar 原先定义在 :mod:`app.middleware.auth` 里。但**仓储层也要读它**
——如果 ``repositories/position.py`` 反过来 import ``app.middleware.auth``，就形成
「数据层依赖 HTTP 中间件」的反向依赖（且 ``middleware.auth`` 自己 import 了
``repositories.user``，属同一包内的循环风险）。故把上下文抽到本中立模块：
中间件负责 **写**（解析会话 → ``set_user_id``），仓储层负责 **读**
（:func:`current_user_id`）。

两种模式下的语义（关键）
------------------------
- ``AUTH_ENABLED=false``（默认，单用户 / 私有部署）：中间件对每个 ``/api/`` 请求
  显式置 ``LEGACY_USER_ID``，故 :func:`current_user_id` 恒返回 ``1``
  —— 与 V0.74.3 行为**完全一致**，过滤条件恒等价于「不过滤」。
- ``AUTH_ENABLED=true``（多用户）：中间件解析会话后置入真实用户 id；
  未登录请求在中间件层就被 401 拦下，**根本到不了路由**。

⚠ 为什么缺失上下文时「抛错」而不是「回退 1」
--------------------------------------------
多用户模式下若某条调用链绕过了 :class:`~app.middleware.auth.AuthMiddleware`
（例如后台调度器、新的内部调用），静默回退到 ``1`` 会让**匿名或越权调用读到 1 号
用户的数据** —— 这是最坏的一类缺陷：不报错、却泄露数据。仓内已有同类教训
（数据源失败静默 fallback 到 mock，页面看着正常而数据是假的）。故此处**显式抛错**，
让调用链在测试期就暴露出来。确实需要跨用户或系统级读取的场景（调度器写每日快照、
回测读全历史序列），应显式传 ``user_id`` 或改用不按用户隔离的全局表。
"""

from __future__ import annotations

import contextvars

from app.config import get_settings
from app.models.user import LEGACY_USER_ID

# 默认 None = 「匿名（未登录）」。单用户模式下由中间件显式置为 LEGACY_USER_ID。
_user_id_var: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "request_user_id", default=None
)


class MissingUserContextError(RuntimeError):
    """多用户模式下仓储层拿不到 ``user_id``。

    通常意味着该调用链绕过了 ``AuthMiddleware``。若属有意为之（系统级任务），
    请显式传入 ``user_id`` 参数，而不是依赖本解析器的回退。
    """


def get_current_user_id() -> int | None:
    """当前请求的 user_id；``None`` 表示匿名（仅在 AUTH_ENABLED=true 下会出现）。"""
    return _user_id_var.get()


def set_user_id(value: int | None) -> contextvars.Token[int | None]:
    """手动注入 user_id（后台任务 / 调度器 / 测试）。

    与 :func:`reset_user_id` 配对，确保不污染其他协程。
    """
    return _user_id_var.set(value)


def reset_user_id(token: contextvars.Token[int | None]) -> None:
    """还原 :func:`set_user_id` 的设置。"""
    _user_id_var.reset(token)


def current_user_id() -> int:
    """仓储层解析「本次查询属于哪个用户」，**永不返回 None**。

    - 上下文有值 → 直接用（多用户模式下即登录用户；单用户模式下恒为 1）；
    - 上下文为空且 ``AUTH_ENABLED=false`` → 回退 :data:`LEGACY_USER_ID`（单用户语义）；
    - 上下文为空且 ``AUTH_ENABLED=true`` → 抛 :class:`MissingUserContextError`。
    """
    uid = _user_id_var.get()
    if uid is not None:
        return uid
    if get_settings().auth_enabled:
        raise MissingUserContextError(
            "多用户模式下仓储层拿不到 user_id：该调用链可能绕过了 AuthMiddleware；"
            "如属系统级任务，请显式传入 user_id。"
        )
    return LEGACY_USER_ID


def resolve_user_id(user_id: int | None) -> int:
    """``user_id`` 参数为空时取当前用户，非空时原样返回。

    仓储方法统一写成 ``async def list_open(self, user_id: int | None = None, ...)``
    并在函数体首行 ``user_id = resolve_user_id(user_id)`` —— 这样既保留
    「显式指定用户」的能力（测试与系统级调用），又能在默认路径上真正按登录用户过滤。
    """
    return current_user_id() if user_id is None else user_id


__all__ = [
    "MissingUserContextError",
    "current_user_id",
    "get_current_user_id",
    "reset_user_id",
    "resolve_user_id",
    "set_user_id",
]
