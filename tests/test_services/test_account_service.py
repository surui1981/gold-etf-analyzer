"""账本服务测试（P1 #6 单用户多账本）。

覆盖：
- 默认账本的三种保障路径（无账本 / 有账本无默认 / 已有默认）与幂等
- ``resolve`` 的兜底（None → 默认）与非法 ID 拒绝
- 新建 / 改名（重名冲突）/ 设为默认（清除旧默认）/ 禁止取消唯一默认
- 归档守卫（默认账本、仍有未平仓持仓）与恢复（重名冲突）
- 清单统计（持仓数 / 未平仓数 / 流水数）与归档过滤
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.position import Position, TradeRecord
from app.repositories.account import AccountRepository
from app.repositories.position import PositionRepository
from app.schemas.account import AccountCreate, AccountUpdate
from app.services.account import AccountService


def _service(session: AsyncSession) -> AccountService:
    return AccountService(AccountRepository(session), PositionRepository(session))


async def _add_position(
    session: AsyncSession, *, account_id: int = 1, qty: float = 100.0, status: str = "open"
) -> Position:
    pos = Position(
        symbol="518880",
        name="黄金ETF华安",
        quantity=qty,
        avg_cost=9.0,
        status=status,
        account_id=account_id,
        opened_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    session.add(pos)
    await session.commit()
    await session.refresh(pos)
    return pos


async def _add_trade(session: AsyncSession, position_id: int, side: str = "buy") -> TradeRecord:
    tr = TradeRecord(
        position_id=position_id,
        side=side,
        quantity=100.0,
        price=9.0,
        fee=0.0,
        traded_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    session.add(tr)
    await session.commit()
    await session.refresh(tr)
    return tr


# ───────────────────────── 默认账本 ─────────────────────────
async def test_ensure_default_creates_id_one(db_session: AsyncSession) -> None:
    """空库：建立 id=1 的「默认账户」，承接 positions.account_id 默认值。"""
    account = await _service(db_session).ensure_default()
    assert account.id == 1
    assert account.is_default is True
    assert account.name == "默认账户"


async def test_ensure_default_idempotent(db_session: AsyncSession) -> None:
    """重复调用不产生新账本。"""
    svc = _service(db_session)
    first = await svc.ensure_default()
    second = await svc.ensure_default()
    assert first.id == second.id
    assert (await svc.list()).total == 1


async def test_ensure_default_marks_first_when_none_flagged(db_session: AsyncSession) -> None:
    """已有账本但都未标记默认 → 把第一个设为默认。"""
    repo = AccountRepository(db_session)
    a1 = await repo.create(name="账本甲", is_default=False)
    await repo.create(name="账本乙", is_default=False)

    default = await _service(db_session).ensure_default()
    assert default.id == a1.id
    assert default.is_default is True


async def test_ensure_default_reuses_existing_id_one(db_session: AsyncSession) -> None:
    """老库升级路径：accounts 已有 id=1（未标默认）→ 直接标记为默认。"""
    repo = AccountRepository(db_session)
    await repo.create(name="历史账本", user_id=1, is_default=False, sort_order=0, account_id=1)
    default = await _service(db_session).ensure_default()
    assert default.id == 1
    assert default.is_default is True


# ───────────────────────── resolve ─────────────────────────
async def test_resolve_none_returns_default(db_session: AsyncSession) -> None:
    svc = _service(db_session)
    assert await svc.resolve(None) == 1


async def test_resolve_explicit_and_unknown(db_session: AsyncSession) -> None:
    svc = _service(db_session)
    created = await svc.create(AccountCreate(name="家人账户"))
    assert await svc.resolve(created.id) == created.id
    with pytest.raises(ValueError, match="账本不存在"):
        await svc.resolve(999)


# ───────────────────────── 新建 / 修改 ─────────────────────────
async def test_create_and_duplicate_name(db_session: AsyncSession) -> None:
    svc = _service(db_session)
    out = await svc.create(AccountCreate(name="主账户", note="自有资金"))
    assert out.name == "主账户"
    assert out.note == "自有资金"
    assert out.sort_order == 10  # 默认账本 0 → 新账本 +10

    with pytest.raises(ValueError, match="同名账本已存在"):
        await svc.create(AccountCreate(name="主账户"))


async def test_create_can_become_default_and_clears_previous(db_session: AsyncSession) -> None:
    """is_default=True 建账本 → 旧默认账本自动取消标记。"""
    svc = _service(db_session)
    await svc.ensure_default()
    out = await svc.create(AccountCreate(name="新主账户", is_default=True))

    listed = {a.name: a.is_default for a in (await svc.list()).items}
    assert listed["新主账户"] is True
    assert listed["默认账户"] is False
    # 解析 None 现在落到新默认账本
    assert await svc.resolve(None) == out.id


async def test_update_rename_and_conflict(db_session: AsyncSession) -> None:
    svc = _service(db_session)
    await svc.ensure_default()
    a = await svc.create(AccountCreate(name="甲账本"))
    b = await svc.create(AccountCreate(name="乙账本"))

    renamed = await svc.update(a.id, AccountUpdate(name="甲账本（改）", note="新备注"))
    assert renamed.name == "甲账本（改）"
    assert renamed.note == "新备注"

    with pytest.raises(ValueError, match="同名账本已存在"):
        await svc.update(b.id, AccountUpdate(name="甲账本（改）"))

    with pytest.raises(ValueError, match="账本不存在"):
        await svc.update(999, AccountUpdate(name="x"))


async def test_update_set_default_and_guard(db_session: AsyncSession) -> None:
    svc = _service(db_session)
    default = await svc.ensure_default()
    a = await svc.create(AccountCreate(name="甲账本"))

    await svc.update(a.id, AccountUpdate(is_default=True))
    listed = {x.name: x.is_default for x in (await svc.list()).items}
    assert listed["甲账本"] is True
    assert listed["默认账户"] is False

    # 唯一默认账本不允许被取消标记
    with pytest.raises(ValueError, match="至少需保留一个默认账本"):
        await svc.update(a.id, AccountUpdate(is_default=False))
    assert default.id != a.id


# ───────────────────────── 归档 / 恢复 ─────────────────────────
async def test_archive_rejects_default(db_session: AsyncSession) -> None:
    svc = _service(db_session)
    default = await svc.ensure_default()
    with pytest.raises(ValueError, match="默认账本不可归档"):
        await svc.archive(default.id)


async def test_archive_rejects_open_positions(db_session: AsyncSession) -> None:
    """仍有未平仓持仓的账本不允许归档（避免数据"消失"）。"""
    svc = _service(db_session)
    await svc.ensure_default()
    a = await svc.create(AccountCreate(name="甲账本"))
    await _add_position(db_session, account_id=a.id, status="open")

    with pytest.raises(ValueError, match="未平仓持仓"):
        await svc.archive(a.id)


async def test_archive_and_restore_roundtrip(db_session: AsyncSession) -> None:
    """已平仓 → 可归档；归档后默认列表不含，含归档列表可见；恢复后回归。"""
    svc = _service(db_session)
    await svc.ensure_default()
    a = await svc.create(AccountCreate(name="甲账本"))
    await _add_position(db_session, account_id=a.id, qty=0.0, status="closed")

    out = await svc.archive(a.id)
    assert out.archived is True
    assert out.archived_at is not None

    names = [x.name for x in (await svc.list()).items]
    assert "甲账本" not in names
    names_all = [x.name for x in (await svc.list(include_archived=True)).items]
    assert "甲账本" in names_all

    # 归档账本仍可解析（交易历史页需要按归档账本筛选）
    assert await svc.resolve(a.id) == a.id

    back = await svc.restore(a.id)
    assert back.archived is False
    assert "甲账本" in [x.name for x in (await svc.list()).items]


async def test_restore_guards(db_session: AsyncSession) -> None:
    svc = _service(db_session)
    await svc.ensure_default()
    a = await svc.create(AccountCreate(name="甲账本"))

    with pytest.raises(ValueError, match="未归档"):
        await svc.restore(a.id)

    await svc.archive(a.id)
    # 归档期间新建同名账本 → 恢复应被拒绝（否则出现两个同名）
    await svc.create(AccountCreate(name="甲账本"))
    with pytest.raises(ValueError, match="同名在用账本"):
        await svc.restore(a.id)


# ───────────────────────── 清单与统计 ─────────────────────────
async def test_list_stats(db_session: AsyncSession) -> None:
    """统计口径：持仓总数 / 未平仓数 / 流水笔数。"""
    svc = _service(db_session)
    await svc.ensure_default()

    open_pos = await _add_position(db_session, account_id=1, status="open")
    closed_pos = await _add_position(db_session, account_id=1, qty=0.0, status="closed")
    await _add_trade(db_session, open_pos.id)
    await _add_trade(db_session, closed_pos.id, side="sell")

    item = (await svc.list()).items[0]
    assert item.stats.position_count == 2
    assert item.stats.open_count == 1
    assert item.stats.trade_count == 2
    assert item.stats.last_traded_at is not None


async def test_list_auto_ensures_default(db_session: AsyncSession) -> None:
    """清单接口自愈：空库也能拿到默认账本（前端入口不应为空）。"""
    out = await _service(db_session).list()
    assert out.total == 1
    assert out.items[0].is_default is True


async def test_list_orders_default_first(db_session: AsyncSession) -> None:
    """默认账本置顶，其余按 sort_order。"""
    svc = _service(db_session)
    await svc.ensure_default()
    a = await svc.create(AccountCreate(name="甲账本"))
    await svc.update(a.id, AccountUpdate(sort_order=5))

    items = (await svc.list()).items
    assert items[0].is_default is True
    assert items[0].name == "默认账户"


async def test_get_unknown_account(db_session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="账本不存在"):
        await _service(db_session).get(999)


async def test_archived_account_name_can_be_reused(db_session: AsyncSession) -> None:
    """归档账本不占用名称：可新建同名账本。"""
    svc = _service(db_session)
    await svc.ensure_default()
    a = await svc.create(AccountCreate(name="实验账本"))
    await svc.archive(a.id)

    again = await svc.create(AccountCreate(name="实验账本"))
    assert again.name == "实验账本"
    assert again.id != a.id


async def test_account_repr(db_session: AsyncSession) -> None:
    """__repr__ 覆盖（默认 / 启用 / 已归档三态）。"""
    repo = AccountRepository(db_session)
    default = await repo.ensure_default()
    assert "默认" in repr(default)

    plain = Account(name="甲", is_default=False)
    assert "启用" in repr(plain)

    archived = Account(name="乙", is_default=False)
    archived.archived_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert "已归档" in repr(archived)
