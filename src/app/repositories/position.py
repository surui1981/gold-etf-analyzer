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

    async def list_open(self, user_id: int = 1) -> list[Position]:
        """当前未平仓且未删除的持仓（按开仓时间升序）。"""
        stmt = (
            select(Position)
            .where(
                Position.status == "open",
                Position.user_id == user_id,
                Position.deleted_at.is_(None),
            )
            .order_by(Position.opened_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get(self, position_id: int) -> Position | None:
        """按 ID 查询持仓（含已软删除的，供撤销恢复使用）。"""
        stmt = select(Position).where(Position.id == position_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_all(self, user_id: int = 1) -> list[Position]:
        """所有未软删除的持仓（**含已平仓**），按开仓时间升序。

        收益曲线与获利分析需要已平仓持仓来核算已实现盈亏，故与
        :meth:`list_open` 区分（后者仅返回持仓中的）。
        """
        stmt = (
            select(Position)
            .where(Position.user_id == user_id, Position.deleted_at.is_(None))
            .order_by(Position.opened_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_all_trades(self, user_id: int = 1) -> list[TradeRecord]:
        """所有交易流水（排除已软删除持仓的流水），按成交时间**升序**。

        升序是回放重建收益曲线的前提（均价法成本随买卖顺序变化）。
        """
        stmt = (
            select(TradeRecord)
            .join(Position, TradeRecord.position_id == Position.id)
            .where(Position.user_id == user_id, Position.deleted_at.is_(None))
            .order_by(TradeRecord.traded_at)
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

    async def soft_delete(self, position_id: int) -> Position:
        """软删除：标记 deleted_at，数据不丢失，可撤销。"""
        position = await self.get(position_id)
        if position is None:
            raise ValueError("持仓不存在")
        position.deleted_at = utcnow()
        await self._session.commit()
        await self._session.refresh(position)
        return position

    async def restore(self, position_id: int) -> Position:
        """撤销软删除：清除 deleted_at，恢复显示。"""
        position = await self.get(position_id)
        if position is None:
            raise ValueError("持仓不存在")
        position.deleted_at = None
        await self._session.commit()
        await self._session.refresh(position)
        return position

    async def save(self, position: Position) -> Position:
        """保存持仓变更（减仓/清仓后提交）。"""
        await self._session.commit()
        await self._session.refresh(position)
        return position


def utcnow() -> datetime:
    """当前 UTC 时间（清仓时间戳用）。"""
    return datetime.now(timezone.utc)
