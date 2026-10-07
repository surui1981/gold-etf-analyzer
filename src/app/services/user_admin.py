"""用户管理编排服务（V0.75.3 · roadmaps §5.2 第 3 项）。

由**所有者**（``role == ROLE_OWNER``）驱动：列用户 / 改密 / 启用禁用 / 软删除。

⚠⚠ 本模块最重要的两条规则，都由**用户决策**拍定，不要擅自改动：

1. **禁止所有者停用/ 删除自己**
   ---------------------------------------------------------------
   唯一管理员把自己禁用后：登录被拒 ⇒ 会话作废 ⇒ **没有任何界面能恢复他**，
   而「找回密码」也救不了**已禁用**的账号（见
   :meth:`app.services.password_reset.PasswordResetService.request_reset`
   对禁用账号不发 token）⇒ **全员失锁且只能进数据库改**。
   ⚠ 这条规则在**禁用**与**删除**两条路径上都要生效，且前置校验不可绕过
   （不能只在前端禁用按钮 —— 那是 UI 层的假防护，直接打API 就破了）。

2. **软删除：数据保留在原 user_id 下，不改写**
   ---------------------------------------------------------------
   删除 = ``is_active=False`` + 撤销其全部会话；**不动**任何业务数据
   （持仓 / 打分 / 分析记录 / 推送订阅仍挂在原 ``user_id``）。
   ⚠ 刻意**不**把数据改写给 ``LEGACY_USER_ID``：那会让下一个数据隔离生效的
   用户「看到」被删用户的黄金持仓与研判记录（误归属，且不可分辨来源）。
   代价是留下**孤儿数据**（无用户能正常访问）—— 这是可接受的，
   因为将来若支持「恢复用户」，全部数据立即可用。

另：**不能删除最后一个所有者**。与第1 条同源 ——
库里只剩一个 owner 时删掉他，等同于全员失锁。
"""

from __future__ import annotations

import logging

from app.config import Settings, get_settings
from app.models.user import ROLE_OWNER, User, utcnow
from app.repositories.user import SessionRepository, UserRepository
from app.services.auth import AuthService, validate_password_strength

logger = logging.getLogger(__name__)


class UserManagementError(Exception):
    """用户管理业务错误（携带机器可读 code 供前端分支）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class UserAdminService:
    """用户管理编排（列/ 改密 / 启用禁用 / 软删除）。"""

    def __init__(
        self,
        users: UserRepository,
        sessions: SessionRepository,
        auth: AuthService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._users = users
        self._sessions = sessions
        self._settings = settings or get_settings()
        # ⚠ 复用 AuthService 的 bcrypt cost 与密码策略 ——
        # 另写一套必然出现「管理页设的密码强度与登录页不一致」，
        # 而那种不一致通常表现为「管理员能设一个弱密码」。
        self._auth = auth or AuthService(users, sessions, settings=self._settings)

    # ─────────────── 查询 ───────────────

    async def list_users(self) -> list[User]:
        """全部用户（按 id 升序）。

        ⚠ 返回的是 ORM 对象，**序列化时必须排除 ``password_hash``**
        （由 ``schemas/admin.py`` 的 ``UserAdminOut`` 负责，勿直接返回 dict）。
        """
        return await self._users.list_all()

    async def get_user(self, user_id: int) -> User:
        """按 id 取用户，不存在抛 :class:`UserManagementError`。

        ⚠ 越权语义：普通成员调用这些端点会在鉴权层被拦（403），
        所以「用户不存在」只需如实报404。
        """
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise UserManagementError("user_not_found", "用户不存在")
        return user

    # ─────────────── 改密 ───────────────

    async def reset_password(self, *, actor: User, user_id: int, new_password: str) -> int:
        """所有者重置某用户的密码，**并撤销其全部会话**。

        ⚠ 撤销全部会话（含目标当前设备）：管理员改密通常意味着
        「这个人可能不该再能访问了」。

        Args:
            actor: 发起操作的所有者
            user_id: 目标用户 id
            new_password: 新密码（须过策略）

        Returns:
            被撤销的会话数

        Raises:
            UserManagementError: 目标不存在
            PasswordPolicyError: 新密码不满足策略
        """
        # ⚠ **禁止对自己用这个端点改密** —— 那属于「用管理功能改自己的密码」，
        # 会绕过 :meth:`AuthService.change_password` 的
        # 「验证当前密码 + 保留当前设备」语义，且撤销自己全部会话后
        # 页面立刻失去登录态，用户会以为「系统出故障了」。
        # 自助改密请用 ``POST /auth/change-password``。
        if user_id == actor.id:
            raise UserManagementError(
                "cannot_reset_own_password",
                "不能通过用户管理修改自己的密码，请使用「修改密码」功能",
            )
        target = await self.get_user(user_id)
        validate_password_strength(new_password)
        await self._users.update_password_hash(target, self._auth.hash_password(new_password))
        revoked = await self._sessions.revoke_all_for_user(target.id, utcnow())
        logger.info(
            "user admin: 重置密码 actor=%s target=%s 撤销会话数=%s", actor.id, target.id, revoked
        )
        return revoked

    # ─────────────── 启用 / 禁用 ───────────────

    async def set_active(self, *, actor: User, user_id: int, is_active: bool) -> int:
        """启用 / 禁用用户。

        ⚠ 禁用与删除在这里**是同一条路径**（``is_active=False``），
        「删除」只是 UI 上更重的措辞 + 不可逆意图。共用一条路径可避免
        两套逻辑漂移。

        Args:
            actor: 发起操作的所有者
            user_id: 目标用户 id
            is_active: True=启用，False=禁用

        Returns:
            被撤销的会话数（启用时为 0）

        Raises:
            UserManagementError: 目标是自己 / 目标是最后一个启用的所有者
        """
        if user_id == actor.id:
            raise UserManagementError(
                "cannot_disable_self", "不能停用自己的账号（会导致无人可管理系统）"
            )
        target = await self.get_user(user_id)

        if not is_active and target.role == ROLE_OWNER:
            await self._guard_last_owner(target, action="停用")

        await self._users.set_active(target, is_active=is_active)
        revoked = 0
        if not is_active:
            revoked = await self._sessions.revoke_all_for_user(target.id, utcnow())
        logger.info(
            "user admin: actor=%s 将 target=%s 置is_active=%s（撤销会话数=%s）",
            actor.id,
            target.id,
            is_active,
            revoked,
        )
        return revoked

    async def soft_delete(self, *, actor: User, user_id: int) -> int:
        """软删除用户（禁用 + 撤销全部会话），**业务数据保留在原 user_id 下**。

        See module docstring for why data is NOT rewritten to LEGACY_USER_ID.
        """
        if user_id == actor.id:
            raise UserManagementError(
                "cannot_delete_self", "不能删除自己的账号（会导致无人可管理系统）"
            )
        target = await self.get_user(user_id)
        if target.role == ROLE_OWNER:
            await self._guard_last_owner(target, action="删除")

        await self._users.set_active(target, is_active=False)
        revoked = await self._sessions.revoke_all_for_user(target.id, utcnow())
        logger.info(
            "user admin: 软删除 target=%s by actor=%s（数据保留在 user_id=%s，撤销会话数=%s）",
            target.id,
            actor.id,
            target.id,
            revoked,
        )
        return revoked

    async def _guard_last_owner(self, target: User, *, action: str) -> None:
        """阻止「停用/删除最后一个启用中的所有者」。

        ⚠ 与「不能操作自己」是**两条不同的规则**，都要生效：
        前者防「自己锁自己」，后者防「把最后一个 owner 弄掉之后没人能恢复」。
        典型场景：owner 想停用一个闲置的另一个 owner，而那已是最后一个。
        """
        others = [
            u
            for u in await self._users.list_all()
            if u.role == ROLE_OWNER and u.is_active and u.id != target.id
        ]
        if not others:
            raise UserManagementError(
                "last_owner_guard",
                f"系统至少需要保留一个启用中的所有者，无法{action}最后一个",
            )
