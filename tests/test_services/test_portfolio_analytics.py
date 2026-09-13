"""交易业绩分析服务测试：收益曲线回放 + 获利分析统计（V0.61.0）。

覆盖：
- 无交易 / 无价格序列时的空态（不抛异常，返回空点位）
- 均价法回放的成本、浮动盈亏、收益率符号与量级
- 已实现盈亏（卖出平仓）与胜率、盈亏比、最佳/最差平仓
- 非交易日成交顺延到次一交易日生效
- 数据异常（无持仓却卖出）不产生负成本
"""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.position import Position, TradeRecord
from app.repositories.market_data import GoldKline
from app.repositories.position import PositionRepository
from app.services.portfolio import PortfolioAnalyticsService


class FakeMarket:
    """假行情：ETF 历史价固定 10.0（便于精确断言），可选自定义步长。"""

    def __init__(self, base: float = 10.0, step: float = 0.0, days: int = 120) -> None:
        self._base = base
        self._step = step
        self._days = days

    async def get_gold_history(self, days: int = 60):
        start = date(2026, 1, 1)
        return [
            GoldKline(
                date=start + timedelta(days=i),
                open=self._base + i * self._step,
                close=round(self._base + i * self._step, 3),
                high=self._base + i * self._step,
                low=self._base + i * self._step,
                volume=0.0,
            )
            for i in range(self._days)
        ]


class EmptyMarket:
    """假行情：价格序列为空，用于验证退化路径。"""

    async def get_gold_history(self, days: int = 60):
        return []


def _service(session: AsyncSession, market=None) -> PortfolioAnalyticsService:
    return PortfolioAnalyticsService(PositionRepository(session), market or FakeMarket())


async def _add_position(
    session: AsyncSession,
    *,
    qty: float,
    avg_cost: float,
    status: str = "open",
    opened_at: datetime | None = None,
    closed_at: datetime | None = None,
) -> Position:
    pos = Position(
        symbol="518880",
        name="黄金ETF华安",
        quantity=qty,
        avg_cost=avg_cost,
        status=status,
        opened_at=opened_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
        closed_at=closed_at,
    )
    session.add(pos)
    await session.commit()
    await session.refresh(pos)
    return pos


async def _add_trade(
    session: AsyncSession,
    position_id: int,
    *,
    side: str,
    qty: float,
    price: float,
    fee: float = 0.0,
    at: datetime | None = None,
) -> TradeRecord:
    rec = TradeRecord(
        position_id=position_id,
        side=side,
        quantity=qty,
        price=price,
        fee=fee,
        traded_at=at or datetime(2026, 1, 5, tzinfo=timezone.utc),
    )
    session.add(rec)
    await session.commit()
    await session.refresh(rec)
    return rec


# ───────────────────────── 收益曲线 ─────────────────────────
async def test_equity_curve_empty_without_trades(db_session: AsyncSession) -> None:
    """无交易记录：返回空点位，不抛异常。"""
    out = await _service(db_session).equity_curve(days=90)
    assert out.points == []
    assert out.summary.latest_return_pct == 0


async def test_equity_curve_empty_without_prices(db_session: AsyncSession) -> None:
    """无价格序列（行情全失败）：同样退化为空点位。"""
    pos = await _add_position(db_session, qty=100, avg_cost=8.0)
    await _add_trade(db_session, pos.id, side="buy", qty=100, price=8.0)

    out = await _service(db_session, EmptyMarket()).equity_curve(days=90)
    assert out.points == []


async def test_equity_curve_holding_after_buy(db_session: AsyncSession) -> None:
    """买入后：末端持有份数与成本正确，浮动盈亏与收益率符号为正。"""
    pos = await _add_position(db_session, qty=100, avg_cost=8.0)
    await _add_trade(db_session, pos.id, side="buy", qty=100, price=8.0)

    out = await _service(db_session).equity_curve(days=90)
    assert out.points, "应有每日点位"
    last = out.points[-1]
    assert last.quantity == 100
    assert last.cost == 800.0
    assert last.market_value == 1000.0  # 100 × 10.0
    assert last.unrealized_pnl == 200.0
    assert last.total_pnl == 200.0
    assert last.return_pct == 25.0  # 200 / 800
    assert out.summary.latest_return_pct == 25.0
    assert out.summary.total_invested == 800.0
    assert out.summary.max_return_pct == 25.0


async def test_equity_curve_realized_after_partial_sell(db_session: AsyncSession) -> None:
    """部分卖出：已实现盈亏按均价法计入，剩余成本同步减少。"""
    pos = await _add_position(db_session, qty=100, avg_cost=8.0)
    await _add_trade(db_session, pos.id, side="buy", qty=100, price=8.0,
                     at=datetime(2026, 1, 5, tzinfo=timezone.utc))
    await _add_trade(db_session, pos.id, side="sell", qty=50, price=12.0,
                     at=datetime(2026, 1, 20, tzinfo=timezone.utc))

    out = await _service(db_session).equity_curve(days=90)
    last = out.points[-1]
    assert last.realized_pnl == 200.0      # (12-8)*50
    assert last.quantity == 50
    assert last.cost == 400.0              # 800 - 8*50
    assert last.unrealized_pnl == 100.0    # 50×10 - 400
    assert last.total_pnl == 300.0
    assert last.return_pct == 37.5         # 300 / 800


async def test_equity_curve_non_trading_day_rolls_forward(db_session: AsyncSession) -> None:
    """非交易日成交：顺延到其后的首个交易日生效，不会丢失。"""
    pos = await _add_position(db_session, qty=100, avg_cost=8.0)
    # 2026-01-03 是周六；价格序列只有 01-01、01-02、01-04（跳过周末由 FakeMarket 决定）
    await _add_trade(db_session, pos.id, side="buy", qty=100, price=8.0,
                     at=datetime(2026, 1, 3, tzinfo=timezone.utc))

    out = await _service(db_session).equity_curve(days=90)
    last = out.points[-1]
    assert last.quantity == 100, "非交易日成交应顺延生效而非丢失"
    assert out.summary.total_invested == 800.0


async def test_equity_curve_sell_without_holding_ignored(db_session: AsyncSession) -> None:
    """数据异常（无持仓却卖出）：跳过该笔，不产生负持仓/负成本。"""
    pos = await _add_position(db_session, qty=0, avg_cost=0.0)
    await _add_trade(db_session, pos.id, side="sell", qty=50, price=12.0)

    out = await _service(db_session).equity_curve(days=90)
    last = out.points[-1]
    assert last.quantity == 0
    assert last.cost == 0.0
    assert last.realized_pnl == 0.0


# ───────────────────────── 获利分析 ─────────────────────────
async def test_performance_empty(db_session: AsyncSession) -> None:
    """无交易无持仓：返回空态与引导文案。"""
    out = await _service(db_session).performance()
    assert out.total_pnl == 0
    assert out.closed_trades == 0
    assert "暂无交易记录" in out.summary


async def test_performance_winning_trade(db_session: AsyncSession) -> None:
    """盈利平仓：胜率 100%，盈亏比无亏损记录时为 None。"""
    # 持仓记录反映「买 100 卖 50」后的真实状态：剩 50 份、成本 8.0
    pos = await _add_position(db_session, qty=50, avg_cost=8.0)
    await _add_trade(db_session, pos.id, side="buy", qty=100, price=8.0,
                     at=datetime(2026, 1, 5, tzinfo=timezone.utc))
    await _add_trade(db_session, pos.id, side="sell", qty=50, price=12.0,
                     at=datetime(2026, 1, 20, tzinfo=timezone.utc))

    out = await _service(db_session).performance()
    assert out.realized_pnl == 200.0
    assert out.closed_trades == 1
    assert out.win_trades == 1
    assert out.loss_trades == 0
    assert out.win_rate == 100.0
    assert out.profit_factor is None
    assert out.best_trade_pnl == 200.0
    assert out.buy_count == 1 and out.sell_count == 1
    assert out.unrealized_pnl == 100.0     # 剩余 50 份 @10.0，成本 400
    assert out.total_pnl == 300.0
    assert out.total_return_pct == 37.5


async def test_performance_losing_trade_and_profit_factor(db_session: AsyncSession) -> None:
    """一胜一负：胜率 50%，盈亏比 = 总盈利 / |总亏损|。"""
    # 两笔卖出已清空持仓 → 持仓记录为 closed 且数量归零
    pos = await _add_position(
        db_session, qty=0, avg_cost=8.0, status="closed",
        closed_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
    )
    await _add_trade(db_session, pos.id, side="buy", qty=200, price=8.0,
                     at=datetime(2026, 1, 5, tzinfo=timezone.utc))
    await _add_trade(db_session, pos.id, side="sell", qty=100, price=12.0,
                     at=datetime(2026, 1, 10, tzinfo=timezone.utc))   # +400
    await _add_trade(db_session, pos.id, side="sell", qty=100, price=6.0,
                     at=datetime(2026, 1, 15, tzinfo=timezone.utc))   # -200

    out = await _service(db_session).performance()
    assert out.closed_trades == 2
    assert out.win_trades == 1 and out.loss_trades == 1
    assert out.win_rate == 50.0
    assert out.gross_profit == 400.0
    assert out.gross_loss == -200.0
    assert out.profit_factor == 2.0
    assert out.best_trade_pnl == 400.0
    assert out.worst_trade_pnl == -200.0
    assert out.avg_trade_pnl == 100.0
    assert out.open_positions == 0
    assert out.closed_positions == 1


# ───────── 成交日晚于价格序列末日（行情 T-1 滞后 / 周末录入）─────────
# FakeMarket 价格序列为 2026-01-01 起连续 120 天 → 末日 2026-04-30。
# 回归背景（2026-09-13 验证发现）：此前 `bisect_left` 找不到归属交易日就直接
# 跳过该笔交易，导致同一响应里 sell_count=2 而 closed_trades=0、
# 累计投入本金 0.00 元，持仓页与业绩页对不上。
async def test_equity_curve_trade_after_last_price_date_kept(
    db_session: AsyncSession,
) -> None:
    """成交日晚于价格序列末日：归入最后一个可得交易日，不得丢弃。"""
    pos = await _add_position(db_session, qty=100, avg_cost=8.0)
    await _add_trade(db_session, pos.id, side="buy", qty=100, price=8.0,
                     at=datetime(2026, 5, 10, tzinfo=timezone.utc))

    out = await _service(db_session).equity_curve(days=90)
    last = out.points[-1]
    assert last.quantity == 100, "行情未覆盖的成交应归入最后交易日而非丢失"
    assert last.cost == 800.0
    assert out.summary.total_invested == 800.0, "累计投入本金不应为 0"


async def test_performance_trade_after_last_price_date_not_zero(
    db_session: AsyncSession,
) -> None:
    """成交日晚于价格序列末日：已实现盈亏与平仓笔数仍须统计（口径自洽）。"""
    pos = await _add_position(db_session, qty=50, avg_cost=8.0)
    await _add_trade(db_session, pos.id, side="buy", qty=100, price=8.0,
                     at=datetime(2026, 1, 5, tzinfo=timezone.utc))
    # 2026-05-10 晚于价格序列末日 2026-04-30
    await _add_trade(db_session, pos.id, side="sell", qty=50, price=12.0,
                     at=datetime(2026, 5, 10, tzinfo=timezone.utc))

    out = await _service(db_session).performance()
    assert out.realized_pnl == 200.0, "卖出已实现盈亏不得因行情滞后而归零"
    assert out.closed_trades == 1
    assert out.win_trades == 1
    assert out.win_rate == 100.0
    assert out.total_invested == 800.0
    # 口径自洽：卖出笔数必须等于纳入回放的平仓笔数
    assert out.sell_count == out.closed_trades, (
        f"sell_count={out.sell_count} 与 closed_trades={out.closed_trades} 不一致"
    )


async def test_performance_holding_days_and_soft_deleted(db_session: AsyncSession) -> None:
    """平均持仓天数按开仓→平仓计算；软删除持仓不参与统计。"""
    opened = datetime(2026, 1, 1, tzinfo=timezone.utc)
    closed = datetime(2026, 1, 11, tzinfo=timezone.utc)
    pos = await _add_position(
        db_session, qty=100, avg_cost=8.0, status="closed",
        opened_at=opened, closed_at=closed,
    )
    await _add_trade(db_session, pos.id, side="buy", qty=100, price=8.0, at=opened)
    await _add_trade(db_session, pos.id, side="sell", qty=100, price=9.0, at=closed)

    # 另一笔被软删除的持仓：不应计入
    deleted = await _add_position(db_session, qty=100, avg_cost=5.0)
    deleted.deleted_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    await db_session.commit()

    out = await _service(db_session).performance()
    assert out.closed_trades == 1
    assert out.avg_holding_days == 10.0
    assert out.buy_count == 1, "软删除持仓的流水应被排除"


# ─────────────────── 手续费口径与跨面板一致性 ───────────────────
async def test_fee_kept_out_of_cost_but_counted_in_invested(
    db_session: AsyncSession,
) -> None:
    """手续费不进摊薄成本（与 PositionService.add_trade 同口径），但计入累计投入本金。

    回归背景：回放曾把 fee 加进 ``cost``，而持仓摊薄成本不含 fee，
    导致同一页面上「收益曲线」比「获利分析」多亏一份手续费，
    出现两个不同的收益率（-4.29% vs -4.25%），损害客户可信度。
    """
    pos = await _add_position(db_session, qty=100, avg_cost=8.0)
    await _add_trade(db_session, pos.id, side="buy", qty=100, price=8.0, fee=5.0)

    out = await _service(db_session).equity_curve(days=90)
    last = out.points[-1]
    assert last.cost == 800.0, "成本不含手续费（与持仓摊薄成本口径一致）"
    assert out.summary.total_invested == 805.0, "累计投入本金含手续费"
    # 市值 100 × 10.0 = 1000；浮盈 = 1000 - 800 = 200
    assert last.unrealized_pnl == 200.0


async def test_equity_curve_and_performance_returns_agree(
    db_session: AsyncSession,
) -> None:
    """同一持仓下，收益曲线末端收益率与获利分析总收益率必须一致。"""
    pos = await _add_position(db_session, qty=100, avg_cost=9.0)
    await _add_trade(db_session, pos.id, side="buy", qty=100, price=9.0, fee=5.0)

    svc = _service(db_session)
    curve = await svc.equity_curve(days=90)
    perf = await svc.performance()

    assert curve.summary.latest_return_pct == perf.total_return_pct
    assert curve.summary.total_pnl == perf.total_pnl
    assert curve.summary.total_invested == perf.total_invested

