"""交易面服务：开仓、加/减仓、清仓、持仓估值与盈亏计算。"""

from app.repositories.market_data import DEFAULT_GOLD_ETF_NAME, MarketDataRepository
from app.repositories.position import PositionRepository, utcnow
from app.schemas.position import (
    PositionCreate,
    PositionDeleteOut,
    PositionOut,
    PositionSummary,
    TradeRequest,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


class PositionService:
    """个人交易跟踪：持仓生命周期管理与实时盈亏。"""

    def __init__(
        self,
        repo: PositionRepository,
        market: MarketDataRepository,
    ) -> None:
        self._repo = repo
        self._market = market

    async def open(self, request: PositionCreate) -> PositionOut:
        """开仓：创建持仓 + 买入流水。"""
        position = await self._repo.create_position(
            symbol=request.symbol,
            name=DEFAULT_GOLD_ETF_NAME,
            quantity=request.quantity,
            avg_cost=request.price,
        )
        await self._repo.add_trade(
            position_id=position.id,
            side="buy",
            quantity=request.quantity,
            price=request.price,
            fee=request.fee,
        )
        logger.info("Position opened: id=%s qty=%s @ %s", position.id, request.quantity, request.price)
        return await self._to_out(position)

    async def add_trade(self, position_id: int, request: TradeRequest) -> PositionOut:
        """加仓（buy）或减仓（sell），均价法摊薄成本。"""
        position = await self._repo.get(position_id)
        if position is None or position.status != "open":
            raise ValueError("持仓不存在或已平仓")

        if request.side == "buy":
            total_cost = position.avg_cost * position.quantity + request.price * request.quantity
            position.quantity += request.quantity
            position.avg_cost = round(total_cost / position.quantity, 4)
        else:
            if request.quantity > position.quantity:
                raise ValueError("减仓数量超过当前持仓")
            position.quantity -= request.quantity  # 均价法：成本不变
            if position.quantity == 0:
                position.status = "closed"
                position.closed_at = utcnow()

        await self._repo.save(position)
        await self._repo.add_trade(
            position_id=position_id,
            side=request.side,
            quantity=request.quantity,
            price=request.price,
            fee=request.fee,
        )
        logger.info(
            "Trade %s on position %s: qty=%s @ %s, remaining=%s",
            request.side, position_id, request.quantity, request.price, position.quantity,
        )
        return await self._to_out(position)

    async def close(self, position_id: int) -> PositionOut:
        """清仓：按最新市价全部卖出。"""
        position = await self._repo.get(position_id)
        if position is None or position.status != "open":
            raise ValueError("持仓不存在或已平仓")
        if position.quantity <= 0:
            raise ValueError("持仓数量为空")

        market_price = await self._current_price()
        await self._repo.add_trade(
            position_id=position_id,
            side="sell",
            quantity=position.quantity,
            price=market_price,
        )
        position.quantity = 0.0
        position.status = "closed"
        position.closed_at = utcnow()
        await self._repo.save(position)
        logger.info("Position closed: id=%s @ %s", position_id, market_price)
        return await self._to_out(position)

    async def delete(self, position_id: int) -> PositionDeleteOut:
        """软删除：标记删除而非物理删除，可随时撤销恢复。"""
        position = await self._repo.soft_delete(position_id)
        logger.info("Position soft-deleted: id=%s", position_id)
        return PositionDeleteOut(id=position.id, deleted=True, deleted_at=position.deleted_at)

    async def restore(self, position_id: int) -> PositionDeleteOut:
        """撤销软删除：恢复持仓显示。"""
        position = await self._repo.restore(position_id)
        logger.info("Position restored: id=%s", position_id)
        return PositionDeleteOut(id=position.id, deleted=False, deleted_at=position.deleted_at)

    async def list_positions(self) -> list[PositionOut]:
        """当前所有未平仓持仓（含实时估值）。"""
        positions = await self._repo.list_open()
        results = [await self._to_out(p) for p in positions]
        return results

    async def export_csv(self) -> str:
        """导出当前持仓与交易流水为 CSV 文本（供对账/备份）。"""
        import csv
        import io

        positions = await self._repo.list_open()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["# 持仓导出", "", "", "", "", "", "", "", "", "", ""])
        w.writerow(
            ["id", "symbol", "name", "quantity", "avg_cost", "status",
             "opened_at", "market_price", "market_value", "pnl", "pnl_pct"]
        )
        for p in positions:
            out = await self._to_out(p)
            w.writerow([
                out.id, out.symbol, out.name, out.quantity, out.avg_cost, out.status,
                out.opened_at, out.market_price, out.market_value, out.pnl, out.pnl_pct,
            ])
        w.writerow([])
        w.writerow(["# 交易流水", "", "", "", "", "", ""])
        w.writerow(["id", "position_id", "side", "quantity", "price", "fee", "traded_at"])
        for p in positions:
            trades = await self._repo.list_trades(p.id)
            for t in trades:
                w.writerow([t.id, t.position_id, t.side, t.quantity, t.price, t.fee, t.traded_at])
        return buf.getvalue()

    async def summary(self) -> PositionSummary:
        """持仓摘要：全部未平仓持仓汇总（供决策引擎）。"""
        positions = await self._repo.list_open()
        if not positions:
            return PositionSummary()

        total_qty = sum(p.quantity for p in positions)
        total_cost = sum(p.avg_cost * p.quantity for p in positions)
        weighted_cost = total_cost / total_qty if total_qty else 0.0
        market_price = await self._current_price()
        pnl = (market_price - weighted_cost) * total_qty
        pnl_pct = (market_price - weighted_cost) / weighted_cost * 100 if weighted_cost else 0.0

        return PositionSummary(
            has_position=True,
            quantity=round(total_qty, 2),
            avg_cost=round(weighted_cost, 4),
            pnl=round(pnl, 2),
            pnl_pct=round(pnl_pct, 2),
            position_ratio=0.0,  # 账户本金未知，暂不估算
        )

    async def _current_price(self) -> float:
        """最新市场价（AKShare，失败降级 Mock）。"""
        quote = await self._market.get_gold_quote()
        return quote.price_usd

    async def _to_out(self, position: object) -> PositionOut:
        """ORM → 输出模型，并补充实时估值。"""
        out = PositionOut.model_validate(position)
        market_price = await self._current_price()
        out.market_price = market_price
        out.market_value = round(position.quantity * market_price, 2)
        out.pnl = round((market_price - position.avg_cost) * position.quantity, 2)
        out.pnl_pct = (
            round((market_price - position.avg_cost) / position.avg_cost * 100, 2)
            if position.avg_cost
            else 0.0
        )
        return out
