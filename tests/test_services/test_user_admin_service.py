"""V0.75.3 用户管理：防自锁与软删除语义的服务层测试。

本模块锁死**三条用户明确拍定的规则**（改代码前先确认是否还成立）：

1. **禁止所有者停用/ 删除自己** —— 否则唯一管理员把自己锁掉后：
   登录被拒 + 会话作废 + 找回密码也救不了**已禁用**账号 ⇒ 全员失锁、
   只能进数据库改。
2. **不能停用/删除最后一个启用中的所有者** —— 与第 1 条同源的另一场景：
   owner 想停用一个闲置的另一个 owner，而那已是最后一个。
3. **软删除：业务数据保留在原 user_id 下，不改写** —— 改写给
   ``LEGACY_USER_ID`` 会让下一个数据隔离生效的用户「看到」被删用户的持仓，
   属误归属且不可分辨来源。

另：不能用管理端点改自己的密码（自助改密走 ``/auth/change-password``，
那条路径会验证当前密码并保留当前设备）。

⚠ 为什么放服务层而不是只测 API 层：前两条规则的价值**全在服务层**，
端点只做转发。若只测端点，将来有人把校验挪到端点层，测试仍会通过。
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.config import Settings
from app.models.user import ROLE_MEMBER, ROLE_OWNER
from app.repositories.user import SessionRepository, UserRepository
from app.services.auth import AuthService, PasswordPolicyError
from app.services.user_admin import UserAdminService, UserManagementError

GOOD_PW = "Passw0rd!x"
NEW_PW = "NewPassw0rd!x"


@pytest.fixture
def repos(db_session):
    """(UserRepository, SessionRepository, AuthService) —— 三者共用同一 session。"""
    users = UserRepository(db_session)
    sessions = SessionRepository(db_session)
    return users, sessions


@pytest.fixture
def svc(repos) -> UserAdminService:
    _users, sessions = repos
    return UserAdminService(_users, sessions, settings=Settings())


async def mk_user(users: UserRepository, *, email: str, role: str = ROLE_MEMBER):
    """建一个用户；密码哈希走真实的 ``AuthService``（bcrypt），而非伪造字符串。

    ⚠ 用真实哈希是有意的：若这里塞个假哈希，将来「改密后旧密码失效」
    这类断言会因为校验永远失败而**恒真** —— 变成永不失败的假测试。
    """
    auth = AuthService(users, _NullSessionRepo())
    return await users.create(
        email=email, password_hash=auth.hash_password(GOOD_PW), role=role, display_name=""
    )


class _NullSessionRepo:
    """``AuthService`` 构造需要一个 session 仓储，但建用户时用不到它。"""

    async def create(self, **_kwargs):  # pragma: no cover - 不应被调用
        raise AssertionError("建用户路径不应触碰 session 仓储")


# ─────────────── 规则 1：禁止操作自己 ───────────────


async def test_cannot_disable_self(repos, svc) -> None:
    """★ 所有者不能停用自己 —— 否则可能全员失锁。"""
    users, _sessions = repos
    owner = await mk_user(users, email="owner@example.com", role=ROLE_OWNER)
    with pytest.raises(UserManagementError) as ei:
        await svc.set_active(actor=owner, user_id=owner.id, is_active=False)
    assert ei.value.code == "cannot_disable_self"


async def test_cannot_delete_self(repos, svc) -> None:
    """★ 所有者不能删除自己。"""
    users, _sessions = repos
    owner = await mk_user(users, email="owner@example.com", role=ROLE_OWNER)
    with pytest.raises(UserManagementError) as ei:
        await svc.soft_delete(actor=owner, user_id=owner.id)
    assert ei.value.code == "cannot_delete_self"


async def test_cannot_reset_own_password_via_admin(repos, svc) -> None:
    """★ 不能用管理端点改自己的密码（会绕开「保留当前设备」的语义）。"""
    users, _sessions = repos
    owner = await mk_user(users, email="owner@example.com", role=ROLE_OWNER)
    with pytest.raises(UserManagementError) as ei:
        await svc.reset_password(actor=owner, user_id=owner.id, new_password=NEW_PW)
    assert ei.value.code == "cannot_reset_own_password"


# ─────────────── 规则 2：最后一个启用中的所有者 ───────────────


async def test_can_disable_other_owner_when_one_remains(repos, svc) -> None:
    """★ 有一个 owner 兜底时，可以停用另一个 owner。"""
    users, _sessions = repos
    a = await mk_user(users, email="a@example.com", role=ROLE_OWNER)
    b = await mk_user(users, email="b@example.com", role=ROLE_OWNER)
    await svc.set_active(actor=a, user_id=b.id, is_active=False)
    row = await users.get_by_id(b.id)
    assert row is not None and row.is_active is False


async def test_last_owner_guard_blocks_disabling_only_enabled_owner(repos, svc) -> None:
    """★★ 停用/删除「最后一个启用中的 owner」⇒ 拒绝。

    构造出「owner 是唯一启用中的 owner」，再用 **member** 身份发起删除。
    ⚠ 断言必须是**精确的** ``last_owner_guard`` —— 若写成
    ``code in ("last_owner_guard", "cannot_delete_self")`` 那种容错，
    则「last_owner 这条规则其实没生效、只是被另一条规则挡住」也会通过，
    等于把这道防线改成不可证伪。
    """
    users, _sessions = repos
    owner = await mk_user(users, email="owner@example.com", role=ROLE_OWNER)
    member = await mk_user(users, email="m@example.com", role=ROLE_MEMBER)

    with pytest.raises(UserManagementError) as ei:
        await svc.soft_delete(actor=member, user_id=owner.id)
    assert ei.value.code == "last_owner_guard"
    # ⚠ 且 owner 必须仍是启用状态（没被真删掉）
    row = await users.get_by_id(owner.id)
    assert row is not None and row.is_active is True


async def test_last_owner_guard_also_applies_to_disable(repos, svc) -> None:
    """★ 同一条规则也要拦「停用」路径 —— 不只是删除路径。

    ⚠ 两条路径共用 ``_guard_last_owner``，但**测试要分别覆盖**：
    只测删除会漏掉「停用分支忘了调 guard」这种回归。
    """
    users, _sessions = repos
    owner = await mk_user(users, email="owner@example.com", role=ROLE_OWNER)
    member = await mk_user(users, email="m@example.com", role=ROLE_MEMBER)

    with pytest.raises(UserManagementError) as ei:
        await svc.set_active(actor=member, user_id=owner.id, is_active=False)
    assert ei.value.code == "last_owner_guard"


async def test_last_owner_guard_message_mentions_owner(repos, svc) -> None:
    """★ 「最后一个所有者」的错误文案要说清原因，便于用户理解。"""
    users, _sessions = repos
    owner = await mk_user(users, email="owner@example.com", role=ROLE_OWNER)
    member = await mk_user(users, email="m@example.com", role=ROLE_MEMBER)
    with pytest.raises(UserManagementError) as ei:
        await svc.soft_delete(actor=member, user_id=owner.id)
    assert "所有者" in ei.value.message


# ─────────────── 规则 3：软删除数据保留 ───────────────


async def test_soft_delete_keeps_row_and_revokes_sessions(repos, svc) -> None:
    """★★ 软删除：用户行仍在（``is_active=False``）+ 全部会话被撤销。"""
    users, sessions = repos
    owner = await mk_user(users, email="owner@example.com", role=ROLE_OWNER)
    target = await mk_user(users, email="t@example.com", role=ROLE_MEMBER)
    await sessions.create(user_id=target.id, expires_at=datetime(2099, 1, 1), session_id="s1")

    revoked = await svc.soft_delete(actor=owner, user_id=target.id)

    assert revoked == 1, "目标用户的会话应被全部撤销"
    row = await users.get_by_id(target.id)
    assert row is not None, "用户行应保留（软删除，不是抹掉）"
    assert row.is_active is False
    assert row.id == target.id, "⚠ user_id 不应被改写 —— 数据仍归属原 user_id"


async def test_disabled_user_can_be_reenabled_with_data_intact(repos, svc) -> None:
    """★禁用可逆 ⇒ 恢复后数据原样还在（这是保留数据换来的好处）。"""
    users, _sessions = repos
    owner = await mk_user(users, email="owner@example.com", role=ROLE_OWNER)
    target = await mk_user(users, email="t@example.com", role=ROLE_MEMBER)

    await svc.set_active(actor=owner, user_id=target.id, is_active=False)
    await svc.set_active(actor=owner, user_id=target.id, is_active=True)

    row = await users.get_by_id(target.id)
    assert row is not None and row.is_active is True
    assert row.email == "t@example.com"


# ─────────────── 改密 ───────────────


async def test_admin_reset_password_works_and_revokes_sessions(repos, svc) -> None:
    """★ 所有者可重置他人密码 + 撤销其全部会话。"""
    users, sessions = repos
    owner = await mk_user(users, email="owner@example.com", role=ROLE_OWNER)
    target = await mk_user(users, email="t@example.com", role=ROLE_MEMBER)
    await sessions.create(user_id=target.id, expires_at=datetime(2099, 1, 1), session_id="s1")

    revoked = await svc.reset_password(actor=owner, user_id=target.id, new_password=NEW_PW)

    assert revoked == 1
    au = AuthService(users, sessions)
    row = await users.get_by_id(target.id)
    assert row is not None
    assert au.verify_password(NEW_PW, row.password_hash), "新密码应生效"
    assert not au.verify_password(GOOD_PW, row.password_hash), "旧密码应失效"


async def test_admin_reset_password_rejects_weak(repos, svc) -> None:
    """★ 弱密码被策略拒绝（与登录页共用同一套策略）。"""
    users, _sessions = repos
    owner = await mk_user(users, email="owner@example.com", role=ROLE_OWNER)
    target = await mk_user(users, email="t@example.com", role=ROLE_MEMBER)
    with pytest.raises(PasswordPolicyError):
        await svc.reset_password(actor=owner, user_id=target.id, new_password="short")


# ─────────────── 查询 ───────────────


async def test_get_user_missing_raises(repos, svc) -> None:
    """目标不存在 ⇒ ``user_not_found``。"""
    users, _sessions = repos
    await mk_user(users, email="owner@example.com", role=ROLE_OWNER)
    owner = await users.get_by_email("owner@example.com")
    assert owner is not None
    with pytest.raises(UserManagementError) as ei:
        await svc.get_user(99999)
    assert ei.value.code == "user_not_found"


async def test_list_users_returns_all_sorted(repos, svc) -> None:
    users, _sessions = repos
    await mk_user(users, email="a@example.com")
    await mk_user(users, email="b@example.com")
    all_users = await svc.list_users()
    assert len(all_users) == 2
    assert [u.id for u in all_users] == sorted(u.id for u in all_users)
