"""交易面服务单元测试：开仓/加仓均价/减仓/清仓/盈亏。

V0.70.0（P2 #8）起新增「按克」开/加/减仓测试。
"""

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.position import PositionRepository
from app.schemas.position import PositionCreate, TradeRequest
from app.services.position import PositionService


class FakeMarket:
    """假行情源：ETF 最新价固定 10.0（V0.61.0 起持仓估值改用 ETF 价）。

    V0.70.0 起新增 ``get_gold_gram_quote``（Au99.99 元/克，固定 990.5）——
    用于「按克开仓」折算测试。
    """

    async def get_gold_quote(self, symbol: str = "XAU"):
        """纽约金价（美元/盎司）——仅供决策与提醒，不参与 ETF 持仓估值。"""
        return type(
            "Q",
            (),
            {"symbol": symbol, "price_usd": 4349.7, "change_pct": 0.5, "updated_at": date.today()},
        )()

    async def get_gold_etf_quote(self, symbol: str = "518880"):
        """518880 ETF 价（元/份）——持仓估值唯一价格源。"""
        return type(
            "Q",
            (),
            {"symbol": symbol, "price_usd": 10.0, "change_pct": 0.5, "updated_at": date.today()},
        )()

    async def get_gold_gram_quote(self, symbol: str = "Au99.99"):
        """Au99.99 元/克——「按克开仓」折算用（V0.70.0）。"""
        return type(
            "Q",
            (),
            {"symbol": symbol, "price_usd": 990.5, "change_pct": 0.35, "updated_at": date.today()},
        )()


class BrokenMarket(FakeMarket):
    """模拟「克价=0」/异常场景的假行情源。"""

    async def get_gold_gram_quote(self, symbol: str = "Au99.99"):
        return type(
            "Q",
            (),
            {"symbol": symbol, "price_usd": 0.0, "change_pct": 0.0, "updated_at": date.today()},
        )()


def _service(session: AsyncSession, market: FakeMarket | None = None) -> PositionService:
    return PositionService(PositionRepository(session), market or FakeMarket())


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


# =========================================================================
# V0.70.0 P2 #8 · 克数持仓（实物金 / 积存金）测试
# =========================================================================


async def test_open_with_grams_converts_to_shares(db_session: AsyncSession) -> None:
    """按克开仓：1000 g × 990.5 / 10.0 = 99050 → 整手 floor = 990 手 = 99000 份。"""
    service = _service(db_session)
    out = await service.open(PositionCreate(symbol="518880", grams=1000.0, price=10.0))
    assert out.quantity == 99000  # 99000 / 100 = 990 手
    assert out.avg_cost == 10.0


async def test_open_grams_persists_grams_held(db_session: AsyncSession) -> None:
    service = _service(db_session)
    out = await service.open(PositionCreate(symbol="518880", grams=1000.0, price=10.0))
    assert out.grams_held == pytest.approx(1000.0, abs=0.001)


async def test_add_trade_grams_increments(db_session: AsyncSession) -> None:
    """按克加仓：原 1000 g + 500 g → 1500 g；份数累加。"""
    service = _service(db_session)
    opened = await service.open(PositionCreate(symbol="518880", grams=1000.0, price=10.0))

    out = await service.add_trade(opened.id, TradeRequest(side="buy", grams=500.0, price=10.5))
    # shares_from_grams 用当前市场价（FakeMarket ETF=10.0）折算：
    # 500 × 990.5 / 10.0 = 49525 → floor → 495 手 = 49500 份
    assert out.quantity == 99000 + 49500
    assert out.grams_held == pytest.approx(1500.0, abs=0.001)


async def test_add_trade_sell_grams_decrements(db_session: AsyncSession) -> None:
    """按克减仓：1000 g 卖出 300 g → 700 g。"""
    service = _service(db_session)
    opened = await service.open(PositionCreate(symbol="518880", grams=1000.0, price=10.0))

    out = await service.add_trade(opened.id, TradeRequest(side="sell", grams=300.0, price=10.5))
    assert out.grams_held == pytest.approx(700.0, abs=0.001)
    # 300 × 990.5 / 10.0 = 29715 → floor → 297 手 = 29700 份
    assert out.quantity == 99000 - 29700


async def test_add_trade_sell_more_grams_than_held_rejected(db_session: AsyncSession) -> None:
    """卖出克数超过当前持有 → ValueError（先校验克数再校验份数）。"""
    service = _service(db_session)
    opened = await service.open(PositionCreate(symbol="518880", grams=1000.0, price=10.0))

    with pytest.raises(ValueError, match="克数"):
        await service.add_trade(opened.id, TradeRequest(side="sell", grams=2000.0, price=10.0))


async def test_open_quantity_xor_grams_both_rejected(db_session: AsyncSession) -> None:
    """quantity 与 grams 同时传入 → ValueError。"""
    service = _service(db_session)
    with pytest.raises(ValueError, match="二选一"):
        await service.open(PositionCreate(symbol="518880", quantity=100, grams=100.0, price=10.0))


async def test_open_neither_rejected(db_session: AsyncSession) -> None:
    """quantity 与 grams 都为空 → ValidationError（Schema 层）。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PositionCreate(symbol="518880", price=10.0)


async def test_summary_quantity_still_works_after_grams_open(
    db_session: AsyncSession,
) -> None:
    """按克开仓后 summary 仍按份统计（克数仅在 PositionOut 暴露）。"""
    service = _service(db_session)
    await service.open(PositionCreate(symbol="518880", grams=1000.0, price=10.0))
    summary = await service.summary()
    assert summary.has_position is True
    assert summary.quantity == 99000


async def test_zero_gram_price_blocks_conversion(db_session: AsyncSession) -> None:
    """克价为 0（数据源异常）→ ValueError；不写入持仓。"""
    service = _service(db_session, BrokenMarket())
    with pytest.raises(ValueError, match="gram_px"):
        await service.open(PositionCreate(symbol="518880", grams=1000.0, price=10.0))


async def test_zero_etf_price_blocks_conversion(db_session: AsyncSession) -> None:
    """ETF 价为 0（数据源异常）→ ValueError。"""

    class ZeroEtf(FakeMarket):
        async def get_gold_etf_quote(self, symbol: str = "518880"):
            return type(
                "Q",
                (),
                {"symbol": symbol, "price_usd": 0.0, "change_pct": 0.0, "updated_at": date.today()},
            )()

    service = _service(db_session, ZeroEtf())
    with pytest.raises(ValueError, match="etf_px"):
        await service.open(PositionCreate(symbol="518880", grams=1000.0, price=10.0))
