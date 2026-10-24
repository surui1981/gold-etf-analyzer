"""``api/v1/endpoints/admin.py`` 用户管理端点层集成测试（V0.88.0 维护线）。

目标覆盖率：47% → **80%+**。

策略：
- ``get_current_user`` 通过 ``app.dependency_overrides`` 直接注入 fake owner
  user —— 绕开「注册 + 登录 + CSRF」链路，专注验证端点层逻辑（与 test_user_admin_service
  服务层测试分工）。
- ``_http_error`` + ``_to_out`` 是纯函数，单独覆盖错误码表全分支。
- 端点 4 个 happy/error path 用真实 ``UserAdminService`` + in-memory SQLite。
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.api.v1.endpoints import admin as admin_ep
from app.dependencies import get_current_user
from app.main import app
from app.models.user import ROLE_OWNER, User

# ──────────────── 共享 fixture：注入 fake owner ────────────────


@pytest.fixture
async def fake_owner(db_session) -> User:
    """构造一个真实的 owner User（DB 写入 + 返回实例）。"""
    user = User(
        email="owner@example.com",
        password_hash="hashed-not-used",
        role=ROLE_OWNER,
        is_active=True,
        display_name="Owner",
        created_at=datetime(2026, 1, 1),
        last_login_at=datetime(2026, 1, 1),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def fake_other_user(db_session) -> User:
    """构造一个 member User（用于「禁止操作自己」与 happy path 区分）。"""
    user = User(
        email="other@example.com",
        password_hash="hashed-not-used",
        role="member",
        is_active=True,
        display_name="Other",
        created_at=datetime(2026, 1, 1),
        last_login_at=datetime(2026, 1, 1),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def as_owner(fake_owner: User):
    """override ``get_current_user`` → fake_owner；admin 端点会把它当 owner。"""
    app.dependency_overrides[get_current_user] = lambda: fake_owner
    try:
        yield fake_owner
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# ──────────────── 纯函数：_http_error 错误码表全分支 ────────────────


class TestHttpErrorMapping:
    """``_http_error`` 把业务错误映射到 HTTP status 的全分支。"""

    def _exc(self, code: str, message: str):
        """构造 UserManagementError。"""
        from app.services.user_admin import UserManagementError

        return UserManagementError(code, message)

    @pytest.mark.parametrize(
        "code,expected_status",
        [
            ("user_not_found", 404),
            ("cannot_disable_self", 409),
            ("cannot_delete_self", 409),
            ("cannot_reset_own_password", 409),
            ("last_owner_guard", 409),
        ],
    )
    def test_known_codes_mapped(self, code: str, expected_status: int) -> None:
        """已知 5 类错误码 → 404 / 409。"""
        exc = self._exc(code, "msg")
        http = admin_ep._http_error(exc)
        assert isinstance(http, HTTPException)
        assert http.status_code == expected_status
        assert http.detail["code"] == code
        assert http.detail["message"] == "msg"

    def test_unknown_code_falls_back_to_400(self) -> None:
        """未知 code → 400（兜底）；保留业务错误信息但不映射冲突语义。"""
        exc = self._exc("mystery_code", "未知错误")
        http = admin_ep._http_error(exc)
        assert http.status_code == 400
        assert http.detail["code"] == "mystery_code"


# ──────────────── 纯函数：_to_out ORM → 响应模型 ────────────────


class TestToOut:
    """``_to_out`` 显式字段映射（含 ``is_self`` 标记）。"""

    def test_to_out_is_self_true(self) -> None:
        """``actor.id == user.id`` → ``is_self=True``。"""
        user = User(
            id=1,
            email="x@x",
            password_hash="h",
            role=ROLE_OWNER,
            is_active=True,
            display_name="X",
            created_at=datetime(2026, 1, 1),
            last_login_at=None,
        )
        out = admin_ep._to_out(user, actor_id=1)
        assert out.is_self is True
        assert out.id == 1
        assert out.email == "x@x"
        assert out.display_name == "X"
        assert out.role == ROLE_OWNER
        assert out.is_active is True
        assert out.last_login_at is None

    def test_to_out_is_self_false(self) -> None:
        """``actor.id != user.id`` → ``is_self=False``。"""
        user = User(
            id=2,
            email="y@x",
            password_hash="h",
            role="member",
            is_active=True,
            display_name="Y",
            created_at=datetime(2026, 1, 1),
            last_login_at=datetime(2026, 2, 1),
        )
        out = admin_ep._to_out(user, actor_id=1)
        assert out.is_self is False
        assert out.role == "member"

    def test_to_out_missing_display_name_default(self) -> None:
        """``display_name`` 为 None 时显示空串（响应模型约束）。"""
        user = User(
            id=1,
            email="x@x",
            password_hash="h",
            role=ROLE_OWNER,
            is_active=True,
            display_name=None,
            created_at=datetime(2026, 1, 1),
            last_login_at=None,
        )
        out = admin_ep._to_out(user, actor_id=1)
        assert out.display_name == ""

    def test_to_out_does_not_leak_password_hash(self) -> None:
        """``_to_out`` 必须不输出 ``password_hash``（安全护栏）。"""
        user = User(
            id=1,
            email="x@x",
            password_hash="SECRET_HASH",
            role=ROLE_OWNER,
            is_active=True,
            display_name="X",
            created_at=datetime(2026, 1, 1),
            last_login_at=None,
        )
        out = admin_ep._to_out(user, actor_id=1)
        dumped = out.model_dump()
        assert "password_hash" not in dumped
        assert "SECRET_HASH" not in str(dumped)


# ──────────────── 端点集成：list_users ────────────────


class TestListUsersEndpoint:
    """``GET /api/v1/admin/users`` 列出全部用户 + is_self 标记 + owner_count。"""

    async def test_empty_db(self, client: AsyncClient, as_owner: User) -> None:
        """空 DB：返回空列表 + total=0 + owner_count=0。"""
        # 但本测试场景有 fake_owner（fixture 自动插入）→ DB 里至少有 1 个 owner
        resp = await client.get("/api/v1/admin/users")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert body["owner_count"] >= 1
        # fake_owner 自己的 is_self=True
        owner_items = [u for u in body["users"] if u["email"] == "owner@example.com"]
        assert owner_items[0]["is_self"] is True

    async def test_lists_other_user_with_is_self_false(
        self, client: AsyncClient, as_owner: User, fake_other_user: User
    ) -> None:
        """含其他用户时：列表含 owner + member；member 的 is_self=False。"""
        resp = await client.get("/api/v1/admin/users")
        assert resp.status_code == 200
        body = resp.json()
        emails = [u["email"] for u in body["users"]]
        assert "owner@example.com" in emails
        assert "other@example.com" in emails

        member = next(u for u in body["users"] if u["email"] == "other@example.com")
        assert member["is_self"] is False
        assert member["role"] == "member"

    async def test_anonymous_in_single_user_mode_falls_back_to_legacy_user(
        self, client: AsyncClient, fake_owner: User
    ) -> None:
        """单用户模式（``auth_enabled=false``，本仓库默认）→ 匿名访问**不 401**。

        V0.97.0 起 ``require_user`` 有**单用户回退**：中间件在单用户模式下不解析
        会话（``request.state.user`` 恒为 None），此时 ``require_user`` 直接读
        LEGACY_USER（id=1）并当作已登录用户返回 —— 供 LAN 单用户部署直接访问
        需要登录的端点。本用例里 ``fake_owner`` 恰好是库里第一条用户 ⇒ id=1。

        ⚠ 这条断言以前写成「匿名访问应被拒（401/403）」，**与实际行为相反** ——
        它是 V0.116.1 修的 CI 预存红之一。
        **多用户模式下的 401 由下一条用例单独覆盖**，两种模式不要混在一条断言里。
        """
        resp = await client.get("/api/v1/admin/users")
        assert resp.status_code == 200, (
            f"单用户模式匿名访问应回退到 LEGACY_USER，实际 {resp.status_code}: {resp.text}"
        )
        # 不只看 200：确认**回退身份**真的生效（回退到的就是 owner 本人）
        body = resp.json()
        me = next(u for u in body["users"] if u["email"] == "owner@example.com")
        assert me["is_self"] is True, "回退身份应是 LEGACY_USER 本人"

    async def test_anonymous_in_multi_user_mode_returns_401(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """多用户模式（``auth_enabled=true``）→ 匿名访问必须 401。

        单用户回退**只在** ``auth_enabled=false`` 时生效；一旦开启鉴权，
        必须恢复「未登录 = 401」的语义。

        ⚠ 这里只替换 ``app.dependencies.get_settings``（依赖层看到的开关），
        **不动中间件**（中间件读的是 ``app.config.get_settings``）——
        于是 401 来自 ``require_user`` 本身，正好验证「回退被 auth_enabled 门控」，
        而不是被中间件提前挡掉。
        """
        from app.config import get_settings as real_get_settings

        multi_user = real_get_settings().model_copy(update={"auth_enabled": True})
        monkeypatch.setattr("app.dependencies.get_settings", lambda: multi_user)

        resp = await client.get("/api/v1/admin/users")
        assert resp.status_code == 401, (
            f"多用户模式匿名访问应 401，实际 {resp.status_code}: {resp.text}"
        )


# ──────────────── 端点集成：admin_reset_password ────────────────


class TestAdminResetPasswordEndpoint:
    """``POST /api/v1/admin/users/{id}/reset-password``。"""

    async def test_cannot_reset_own_password_returns_409(
        self, client: AsyncClient, as_owner: User
    ) -> None:
        """不能改自己密码 → 409 + code=cannot_reset_own_password。"""
        resp = await client.post(
            f"/api/v1/admin/users/{as_owner.id}/reset-password",
            json={"new_password": "NewPassw0rd!x"},
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "cannot_reset_own_password"

    async def test_user_not_found_returns_404(self, client: AsyncClient, as_owner: User) -> None:
        """目标用户不存在 → 404 + code=user_not_found。"""
        resp = await client.post(
            "/api/v1/admin/users/99999/reset-password",
            json={"new_password": "NewPassw0rd!x"},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "user_not_found"


# ──────────────── 端点集成：admin_set_active ────────────────


class TestAdminSetActiveEndpoint:
    """``POST /api/v1/admin/users/{id}/set-active``。"""

    async def test_cannot_disable_self_returns_409(
        self, client: AsyncClient, as_owner: User
    ) -> None:
        """不能停用自己 → 409 + code=cannot_disable_self。"""
        resp = await client.post(
            f"/api/v1/admin/users/{as_owner.id}/set-active",
            json={"is_active": False},
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "cannot_disable_self"

    async def test_user_not_found_returns_404(self, client: AsyncClient, as_owner: User) -> None:
        """目标用户不存在 → 404。"""
        resp = await client.post(
            "/api/v1/admin/users/99999/set-active",
            json={"is_active": False},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "user_not_found"


# ──────────────── 端点集成：admin_delete_user ────────────────


class TestAdminDeleteUserEndpoint:
    """``DELETE /api/v1/admin/users/{id}``（软删除）。"""

    async def test_cannot_delete_self_returns_409(
        self, client: AsyncClient, as_owner: User
    ) -> None:
        """不能删除自己 → 409 + code=cannot_delete_self。"""
        resp = await client.delete(f"/api/v1/admin/users/{as_owner.id}")
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "cannot_delete_self"

    async def test_user_not_found_returns_404(self, client: AsyncClient, as_owner: User) -> None:
        """目标用户不存在 → 404。"""
        resp = await client.delete("/api/v1/admin/users/99999")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "user_not_found"
