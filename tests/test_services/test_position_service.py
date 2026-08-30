"""交易面服务单元测试：开仓/加仓均价/减仓/清仓/盈亏。"""

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.position import PositionRepository
from app.schemas.position import PositionCreate, TradeRequest
from app.services.position import PositionService


class FakeMarket:
    """假行情源：固定最新价 10.0。"""

    async def get_gold_quote(self, symbol: str = "XAU"):
        return type("Q", (), {"symbol": symbol, "price_usd": 10.0, "change_pct": 0.5, "updated_at": date.today()})()


def _service(session: AsyncSession) -> PositionService:
    return PositionService(PositionRepository(session), FakeMarket())


async def test_open_position(db_session: AsyncSession) -> None:
    service = _service(db_session)
    out = await service.open(PositionCreate(symbol="518880", quantity=100, price=9.0, fee=1.0))

    assert out.quantity == 100
    assert out.avg_cost == 9.0
    assert out.status == "open"
    assert out.market_price == 10.0
    assert out.pnl == 100.0  # (10-9)*100


async def test_add_trade_averages_cost(db_session: AsyncSession) -> None:
    service = _service(db_session)
    opened = await service.open(PositionCreate(symbol="518880", quantity=100, price=9.0))

    # 加仓 100 份 @10.0 → 均价 (9*100+10*100)/200 = 9.5
    out = await service.add_trade(opened.id, TradeRequest(side="buy", quantity=100, price=10.0))
    assert out.quantity == 200
    assert out.avg_cost == 9.5

    # 减仓 50 份 → 均价不变
    out = await service.add_trade(opened.id, TradeRequest(side="sell", quantity=50, price=10.5))
    assert out.quantity == 150
    assert out.avg_cost == 9.5


async def test_sell_more_than_held_rejected(db_session: AsyncSession) -> None:
    service = _service(db_session)
    opened = await service.open(PositionCreate(symbol="518880", quantity=100, price=9.0))

    try:
        await service.add_trade(opened.id, TradeRequest(side="sell", quantity=200, price=10.0))
    except ValueError:
        return
    raise AssertionError("expected ValueError")


async def test_close_position(db_session: AsyncSession) -> None:
    service = _service(db_session)
    opened = await service.open(PositionCreate(symbol="518880", quantity=100, price=9.0))

    closed = await service.close(opened.id)
    assert closed.quantity == 0
    assert closed.status == "closed"
    # 已平仓：剩余持仓 0，浮动盈亏归零（兑现盈亏记录在交易流水中）
    assert closed.pnl == 0.0


async def test_summary(db_session: AsyncSession) -> None:
    service = _service(db_session)
    summary = await service.summary()
    assert summary.has_position is False

    await service.open(PositionCreate(symbol="518880", quantity=100, price=9.0))
    summary = await service.summary()
    assert summary.has_position is True
    assert summary.quantity == 100
    assert summary.avg_cost == 9.0
    assert summary.pnl == 100.0
    assert summary.pnl_pct == pytest.approx(100 / 9, abs=0.01)  # (10-9)/9 保留两位
