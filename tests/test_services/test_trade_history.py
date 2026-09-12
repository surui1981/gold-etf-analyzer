"""交易历史服务测试（P1 #6 交易历史查询页）。

覆盖：
- 空态（无成交）：total=0、汇总全 0、CSV 仍可导出
- 均价法回放：每笔卖出的已实现盈亏与「成交后份额」
- 汇总覆盖**全部匹配行**而非当前页
- 各筛选维度：账本 / 方向 / 持仓 / 关键字 / 日期区间
- 分页与页码钳制
- 数据异常（无持仓却卖出）不崩且不给盈亏
- 软删除持仓的流水被排除
"""

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.position import Position, TradeRecord
from app.repositories.account import AccountRepository
from app.repositories.position import PositionRepository
from app.services.trades import TradeHistoryService


def _service(session: AsyncSession) -> TradeHistoryService:
    return TradeHistoryService(PositionRepository(session))


async def _position(
    session: AsyncSession, *, symbol: str = "518880", account_id: int = 1, deleted: bool = False
) -> Position:
    pos = Position(
        symbol=symbol,
        name="黄金ETF华安",
        quantity=0.0,
        avg_cost=0.0,
        status="open",
        account_id=account_id,
        opened_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    if deleted:
        pos.deleted_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    session.add(pos)
    await session.commit()
    await session.refresh(pos)
    return pos


async def _trade(
    session: AsyncSession,
    position_id: int,
    *,
    side: str,
    qty: float,
    price: float,
    fee: float = 0.0,
    day: int = 1,
) -> TradeRecord:
    tr = TradeRecord(
        position_id=position_id,
        side=side,
        quantity=qty,
        price=price,
        fee=fee,
        traded_at=datetime(2026, 1, day, 10, 0, tzinfo=timezone.utc),
    )
    session.add(tr)
    await session.commit()
    await session.refresh(tr)
    return tr


# ───────────────────────── 空态 ─────────────────────────
async def test_empty_history(db_session: AsyncSession) -> None:
    out = await _service(db_session).query()
    assert out.total == 0
    assert out.items == []
    assert out.page == 1
    assert out.page_count == 1
    assert out.summary.count == 0
    assert out.summary.realized_pnl == 0.0
    assert out.summary.net_amount == 0.0


async def test_empty_export_has_header_and_summary(db_session: AsyncSession) -> None:
    csv_text = await _service(db_session).export_csv()
    assert "交易历史导出" in csv_text
    assert "成交时间" in csv_text
    assert "已实现盈亏(元)" in csv_text
    assert "汇总" in csv_text


# ───────────────────────── 均价法回放 ─────────────────────────
async def test_avg_cost_replay_realized_pnl(db_session: AsyncSession) -> None:
    """买 100@10 + 买 100@12 → 均价 11；卖 100@13（费 1）→ 已实现 +199。"""
    pos = await _position(db_session)
    await _trade(db_session, pos.id, side="buy", qty=100, price=10.0, day=1)
    await _trade(db_session, pos.id, side="buy", qty=100, price=12.0, day=2)
    await _trade(db_session, pos.id, side="sell", qty=100, price=13.0, fee=1.0, day=3)

    out = await _service(db_session).query()
    # 仓库返回倒序：卖出在最前
    sell = out.items[0]
    assert sell.side == "sell"
    assert sell.realized_pnl == 199.0
    assert sell.post_quantity == 100.0
    assert sell.amount == 1300.0

    buys = [i for i in out.items if i.side == "buy"]
    assert all(i.realized_pnl is None for i in buys), "买入不产生已实现盈亏"
    # 买入的 post_quantity 逐步累加（倒序排列：100@12 在后 → 200；100@10 → 100）
    assert sorted(i.post_quantity for i in buys) == [100.0, 200.0]

    assert out.summary.sell_count == 1
    assert out.summary.buy_count == 2
    assert out.summary.realized_pnl == 199.0
    assert out.summary.buy_amount == 2200.0
    assert out.summary.sell_amount == 1300.0
    assert out.summary.net_amount == 900.0
    assert out.summary.total_fee == 1.0


async def test_losing_sell_negative_pnl(db_session: AsyncSession) -> None:
    """卖价低于成本 → 已实现为负（前端应显示绿色）。"""
    pos = await _position(db_session)
    await _trade(db_session, pos.id, side="buy", qty=100, price=10.0, day=1)
    await _trade(db_session, pos.id, side="sell", qty=100, price=9.0, day=2)

    out = await _service(db_session).query(side="sell")
    assert out.items[0].realized_pnl == -100.0
    assert out.summary.realized_pnl == -100.0


async def test_partial_sell_keeps_remaining_quantity(db_session: AsyncSession) -> None:
    """部分减仓：成交后份额留残余，成本单价不变。"""
    pos = await _position(db_session)
    await _trade(db_session, pos.id, side="buy", qty=1000, price=9.0, day=1)
    await _trade(db_session, pos.id, side="sell", qty=400, price=10.0, day=2)

    out = await _service(db_session).query(side="sell")
    sell = out.items[0]
    assert sell.post_quantity == 600.0
    assert sell.realized_pnl == 400.0  # (10 - 9) * 400


async def test_filter_by_side_keeps_replay_context(db_session: AsyncSession) -> None:
    """回归：按方向/日期筛选时，回放仍需完整买入上下文，否则盈亏算不出来。

    只看卖出时若把买入也过滤掉，持仓份额被视为 0，已实现盈亏会退化为 None。
    """
    from datetime import date

    pos = await _position(db_session)
    await _trade(db_session, pos.id, side="buy", qty=100, price=10.0, day=1)
    await _trade(db_session, pos.id, side="sell", qty=100, price=11.0, day=20)

    svc = _service(db_session)
    only_sell = await svc.query(side="sell")
    assert only_sell.total == 1
    assert only_sell.items[0].realized_pnl == 100.0
    assert only_sell.items[0].post_quantity == 0.0

    # 日期区间只覆盖卖出日：盈亏仍能借买入上下文算出
    ranged = await svc.query(start=date(2026, 1, 15), end=date(2026, 1, 25))
    assert ranged.total == 1
    assert ranged.items[0].realized_pnl == 100.0


async def test_sell_without_position_is_safe(db_session: AsyncSession) -> None:
    """脏数据（无持仓却卖出）不应崩溃，也不给出盈亏。"""
    pos = await _position(db_session)
    await _trade(db_session, pos.id, side="sell", qty=100, price=10.0, day=1)

    out = await _service(db_session).query()
    assert out.total == 1
    assert out.items[0].realized_pnl is None
    assert out.items[0].post_quantity == 0.0
    assert out.summary.realized_pnl == 0.0


async def test_soft_deleted_position_trades_excluded(db_session: AsyncSession) -> None:
    alive = await _position(db_session)
    dead = await _position(db_session, deleted=True)
    await _trade(db_session, alive.id, side="buy", qty=100, price=9.0, day=1)
    await _trade(db_session, dead.id, side="buy", qty=100, price=9.0, day=2)

    out = await _service(db_session).query()
    assert out.total == 1
    assert out.items[0].position_id == alive.id


# ───────────────────────── 筛选 ─────────────────────────
async def test_filter_by_account(db_session: AsyncSession) -> None:
    repo = AccountRepository(db_session)
    await repo.ensure_default()
    acc2 = await repo.create(name="家人账户")

    a = await _position(db_session, account_id=1)
    b = await _position(db_session, account_id=acc2.id)
    await _trade(db_session, a.id, side="buy", qty=100, price=9.0, day=1)
    await _trade(db_session, b.id, side="buy", qty=200, price=9.5, day=2)

    svc = _service(db_session)
    assert (await svc.query()).total == 2, "不传账本 = 全部账本"
    only2 = await svc.query(account_id=acc2.id)
    assert only2.total == 1
    assert only2.items[0].account_name == "家人账户"
    assert only2.items[0].quantity == 200


async def test_filter_by_side_position_keyword_and_range(db_session: AsyncSession) -> None:
    pos = await _position(db_session)
    await _trade(db_session, pos.id, side="buy", qty=100, price=9.0, day=1)
    await _trade(db_session, pos.id, side="sell", qty=50, price=10.0, day=10)
    svc = _service(db_session)

    assert (await svc.query(side="buy")).total == 1
    assert (await svc.query(side="sell")).total == 1
    assert (await svc.query(position_id=pos.id)).total == 2
    assert (await svc.query(position_id=999)).total == 0
    assert (await svc.query(symbol="518880")).total == 2
    assert (await svc.query(symbol="999999")).total == 0
    assert (await svc.query(keyword="华安")).total == 2
    assert (await svc.query(keyword="5188")).total == 2
    assert (await svc.query(keyword="不存在")).total == 0

    # 日期区间含边界
    from datetime import date

    assert (await svc.query(start=date(2026, 1, 1), end=date(2026, 1, 1))).total == 1
    assert (await svc.query(start=date(2026, 1, 2))).total == 1
    assert (await svc.query(end=date(2026, 1, 9))).total == 1
    assert (await svc.query(start=date(2026, 1, 1), end=date(2026, 1, 10))).total == 2


# ───────────────────────── 分页与汇总 ─────────────────────────
async def test_pagination_and_summary_covers_all_rows(db_session: AsyncSession) -> None:
    pos = await _position(db_session)
    for day in range(1, 6):
        await _trade(db_session, pos.id, side="buy", qty=100, price=9.0, day=day)

    svc = _service(db_session)
    page1 = await svc.query(page=1, page_size=2)
    assert page1.total == 5
    assert page1.page_count == 3
    assert len(page1.items) == 2
    assert page1.summary.count == 5, "汇总必须覆盖全部匹配行，不是当前页"
    assert page1.summary.buy_amount == 4500.0

    page3 = await svc.query(page=3, page_size=2)
    assert len(page3.items) == 1

    # 越界页码钳到最后一页 / 非法参数兜底
    assert (await svc.query(page=99, page_size=2)).page == 3
    assert (await svc.query(page=0, page_size=0)).page == 1
    assert (await svc.query(page=1, page_size=9999)).page_size == 500


# ───────────────────────── 导出 ─────────────────────────
async def test_export_filters_and_summary_row(db_session: AsyncSession) -> None:
    pos = await _position(db_session)
    await _trade(db_session, pos.id, side="buy", qty=100, price=9.0, fee=5.0, day=1)
    await _trade(db_session, pos.id, side="sell", qty=100, price=10.0, day=2)

    csv_text = await _service(db_session).export_csv(side="sell")
    lines = [ln for ln in csv_text.splitlines() if ln.strip()]
    assert any("卖出" in ln and "100.0" in ln for ln in lines)
    assert not any(ln.startswith("2026-01-01 10:00:00") for ln in lines), "已按 side 过滤"
    assert "买入" not in csv_text.split("# 汇总")[0].replace("买入笔数", "")
    # 汇总行：笔数 1 / 买入 0 / 卖出 1 / 已实现盈亏 95.0
    assert "笔数,买入笔数,卖出笔数" in csv_text
    assert "1,0,1" in csv_text
