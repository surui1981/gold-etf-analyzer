"""持仓仓储：封装 Position / TradeRecord 的数据访问。"""

from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.position import Position, TradeRecord


class PositionRepository:
    """数据访问层：交易面所有 SQL 操作集中于此。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_position(
        self,
        *,
        symbol: str,
        name: str,
        quantity: float,
        avg_cost: float,
        user_id: int = 1,
    ) -> Position:
        """开仓：创建持仓并提交。"""
        position = Position(
            symbol=symbol,
            name=name,
            quantity=quantity,
            avg_cost=avg_cost,
            status="open",
            user_id=user_id,
        )
        self._session.add(position)
        await self._session.commit()
        await self._session.refresh(position)
        return position

    async def add_trade(
        self,
        *,
        position_id: int,
        side: str,
        quantity: float,
        price: float,
        fee: float = 0.0,
    ) -> TradeRecord:
        """记录一笔交易流水并提交。"""
        record = TradeRecord(
            position_id=position_id,
            side=side,
            quantity=quantity,
            price=price,
            fee=fee,
        )
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        return record

    async def get(self, position_id: int) -> Position | None:
        """按 ID 查询持仓。"""
        stmt = select(Position).where(Position.id == position_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_open(self, user_id: int = 1) -> list[Position]:
        """当前未平仓持仓（按开仓时间升序）。"""
        stmt = (
            select(Position)
            .where(Position.status == "open", Position.user_id == user_id)
            .order_by(Position.opened_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_trades(self, position_id: int) -> list[TradeRecord]:
        """持仓的交易流水（按时间倒序）。"""
        stmt = (
            select(TradeRecord)
            .where(TradeRecord.position_id == position_id)
            .order_by(desc(TradeRecord.traded_at))
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def save(self, position: Position) -> Position:
        """保存持仓变更（减仓/清仓后提交）。"""
        await self._session.commit()
        await self._session.refresh(position)
        return position


def utcnow() -> datetime:
    """当前 UTC 时间（清仓时间戳用）。"""
    return datetime.now(timezone.utc)
