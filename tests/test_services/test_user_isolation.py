"""V0.75.2 数据隔离：仓储层按 ``user_id`` 隔离的回归测试。

背景（为什么需要这个模块）
--------------------------
``positions.user_id`` / ``accounts.user_id`` 早在 V0.62.0 就存在、库内取值确实是 1，
但仓储方法的默认值是**字面量 1**，且 ID 寻址的方法（``get`` / ``list_trades``）
**完全不按用户过滤** —— 于是「多用户」只是个外壳：任何登录用户都能凭 id
读到、甚至改写他人的持仓与流水。本模块把修复后的语义锁死。

三条核心语义（对应 :mod:`app.utils.user_scope`）
-----------------------------------------------
1. 未开启认证（默认单用户）⇒ 解析结果恒为 ``LEGACY_USER_ID``，行为与旧版**逐字一致**；
2. 开启认证但拿不到上下文 ⇒ **抛错**，而不是静默回退到 1 号用户；
3. 越权访问 ⇒ 表现为「不存在」（``None`` / ``ValueError``），由服务层转 404。
   刻意不用 403：状态码差异本身就泄露「该 id 存在，只是不属于你」。

⚠ 两个易踩的坑（本模块第一版都踩过，留下备查）
---------------------------------------------
- ``user_scope`` 里有两个名字相近的函数，别用错：
  ``get_current_user_id()`` = **读原始上下文**（可为 ``None``）；
  ``current_user_id()`` = **解析器**（单用户模式返回 1；多用户模式无上下文则抛错）。
- **不要用「同步夹具 set + teardown reset」切换身份**：`contextvars` 的 Token
  只能在**创建它的 Context** 里 reset，而 pytest-asyncio 给每个用例单独的
  Context，teardown 必然报 ``ValueError: ... was created in a different Context``。
  故这里用「在同一协程内 set/reset」的上下文管理器 :func:`acting_as`。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from app.config import get_settings
from app.models.user import LEGACY_USER_ID
from app.repositories.account import AccountRepository
from app.repositories.position import PositionRepository
from app.utils.user_scope import (
    MissingUserContextError,
    get_current_user_id,
    reset_user_id,
    resolve_user_id,
    set_user_id,
)


@contextmanager
def acting_as(uid: int | None) -> Iterator[None]:
    """以指定用户身份执行代码块；退出时在**同一 Context** 内还原。

    与 fixtures 的差别很关键：set 与 reset 都发生在调用方的协程里，
    因此 Token 归属的 Context 一致，不会触发 pytest-asyncio 的跨 Context 报错。
    """
    token = set_user_id(uid)
    try:
        yield
    finally:
        reset_user_id(token)


async def _make_position(
    repo: PositionRepository, *, user_id: int, account_id: int = 1, symbol: str = "518880"
):
    """建一笔指定归属的持仓（显式传 user_id，不依赖上下文）。"""
    return await repo.create_position(
        symbol=symbol,
        name="黄金ETF华安",
        quantity=100.0,
        avg_cost=2.5,
        user_id=user_id,
        account_id=account_id,
    )


# ---------------------------------------------------------------- 解析器语义


async def test_single_user_mode_resolves_to_legacy() -> None:
    """默认（AUTH_ENABLED=false）：解析结果恒为 LEGACY_USER_ID ⇒ 行为与旧版一致。"""
    settings = get_settings()
    assert settings.auth_enabled is False, "测试前提：默认应为单用户模式"
    assert get_current_user_id() is None, "无请求上下文时，原始上下文应为 None"
    assert resolve_user_id(None) == LEGACY_USER_ID


async def test_explicit_user_id_wins_over_context() -> None:
    """显式传 user_id 优先于上下文 —— 系统级调用（调度器 / 启动引导）的逃生门。"""
    with acting_as(1):
        assert resolve_user_id(None) == 1
        assert resolve_user_id(9) == 9
    assert get_current_user_id() is None, "退出 acting_as 后必须还原"


async def test_multi_user_without_context_raises() -> None:
    """多用户模式下拿不到上下文必须**抛错**，不得静默回退到 1 号用户。

    静默回退是最坏的一类缺陷：不报错、却把 1 号用户的数据交给匿名或越权调用。
    本仓已有同类教训（数据源失败静默 fallback 到 mock，页面看着正常而数据是假的）。
    """
    settings = get_settings()
    settings.auth_enabled = True
    try:
        assert get_current_user_id() is None
        with pytest.raises(MissingUserContextError):
            resolve_user_id(None)
        # 显式传参不受影响（调度器 / 启动引导走这条路）
        assert resolve_user_id(7) == 7
    finally:
        settings.auth_enabled = False


# ---------------------------------------------------------------- 持仓隔离


async def test_positions_are_isolated_between_users(db_session) -> None:
    """两个用户的持仓列表互不可见；不传 user_id 时走上下文（单用户=1）。"""
    repo = PositionRepository(db_session)
    a = await _make_position(repo, user_id=1)
    b = await _make_position(repo, user_id=2)

    assert {p.id for p in await repo.list_open(user_id=1)} == {a.id}
    assert {p.id for p in await repo.list_open(user_id=2)} == {b.id}
    assert {p.id for p in await repo.list_all(user_id=1)} == {a.id}
    assert {p.id for p in await repo.list_all(user_id=2)} == {b.id}
    # 默认路径（不传参）在单用户模式下解析为 1 号用户
    assert {p.id for p in await repo.list_open()} == {a.id}


async def test_cannot_read_other_users_position_by_id(db_session) -> None:
    """★ 修复前的越权口子：仅凭 position_id 即可读到他人持仓与全部流水。"""
    repo = PositionRepository(db_session)
    a = await _make_position(repo, user_id=1)

    with acting_as(1):
        await repo.add_trade(position_id=a.id, side="buy", quantity=10.0, price=2.6)
        assert (await repo.get(a.id)) is not None, "本人读取不受影响"
        assert len(await repo.list_trades(a.id)) == 1

    with acting_as(2):
        assert await repo.get(a.id) is None, "越权读取应表现为「不存在」"
        assert await repo.list_trades(a.id) == [], "他人持仓的流水不可读"


async def test_cannot_write_other_users_position(db_session) -> None:
    """★ 越权**写**也要拦住：加仓 / 软删除 / 撤销恢复三条路径。"""
    repo = PositionRepository(db_session)
    a = await _make_position(repo, user_id=1)

    with acting_as(1):
        await repo.add_trade(position_id=a.id, side="buy", quantity=10.0, price=2.6)

    with acting_as(2):
        with pytest.raises(ValueError):
            await repo.add_trade(position_id=a.id, side="buy", quantity=10.0, price=2.6)
        with pytest.raises(ValueError):
            await repo.soft_delete(a.id)
        with pytest.raises(ValueError):
            await repo.restore(a.id)

    with acting_as(1):
        assert len(await repo.list_trades(a.id)) == 1, "他人的写入不得落下"
        assert (await repo.get(a.id)).deleted_at is None, "他人的软删除不得生效"


async def test_query_trades_and_stats_are_isolated(db_session) -> None:
    """交易历史查询与账本聚合统计都按用户收敛。"""
    repo = PositionRepository(db_session)
    a = await _make_position(repo, user_id=1, account_id=1)
    b = await _make_position(repo, user_id=2, account_id=2)

    with acting_as(1):
        await repo.add_trade(position_id=a.id, side="buy", quantity=1.0, price=2.5)
    with acting_as(2):
        await repo.add_trade(position_id=b.id, side="buy", quantity=1.0, price=2.5)

    with acting_as(1):
        assert [r.position.id for r in await repo.query_trades()] == [a.id]
        stats = await repo.stats_by_account()
        assert set(stats) == {1}, "1 号用户不应看到 2 号用户账本的统计"
        assert stats[1].position_count == 1

    with acting_as(2):
        assert [r.position.id for r in await repo.query_trades()] == [b.id]
        stats = await repo.stats_by_account()
        assert set(stats) == {2}
        assert stats[2].position_count == 1


# ---------------------------------------------------------------- 账本隔离


async def test_accounts_are_isolated(db_session) -> None:
    """账本列表与按 id 查询都按用户收敛。"""
    repo = AccountRepository(db_session)
    await repo.create(name="甲的账本", user_id=1, is_default=True)
    other = await repo.create(name="乙的账本", user_id=2, is_default=True)
    # 自增首个即 id=1，属甲
    assert (await repo.get(1, user_id=1)) is not None

    with acting_as(2):
        assert [x.name for x in await repo.list()] == ["乙的账本"]
        assert (await repo.get(other.id)) is not None
        assert await repo.get(1) is None, "甲 id=1 的账本对乙不可见"
        assert await repo.get_by_name("甲的账本") is None
        assert (await repo.get_default()).name == "乙的账本"

    with acting_as(1):
        assert [x.name for x in await repo.list()] == ["甲的账本"]
        assert (await repo.get_default()).name == "甲的账本"
