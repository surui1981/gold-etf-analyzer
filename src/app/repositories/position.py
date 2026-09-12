"""持仓仓储：封装 Position / TradeRecord 的数据访问。"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import case, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import DEFAULT_ACCOUNT_NAME, Account
from app.models.position import Position, TradeRecord


@dataclass(slots=True)
class TradeWithPosition:
    """交易流水 + 所属持仓 + 账本名（交易历史查询页用）。"""

    trade: TradeRecord
    position: Position
    account_name: str


@dataclass(slots=True)
class AccountStats:
    """账本维度的持仓/流水统计（账本列表页展示用）。"""

    position_count: int = 0
    open_count: int = 0
    trade_count: int = 0
    last_traded_at: datetime | None = None


class PositionRepository:
    """数据访问层：交易面所有 SQL 操作集中于此。

    V0.62.0（P1 #6）起所有查询支持 ``account_id`` 过滤：
    - ``account_id=None`` 表示**全部账本**（合并视图，前端「全部账本」选项）；
    - 传入具体 ID 则仅返回该账本的持仓与流水。
    """

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
        account_id: int = 1,
    ) -> Position:
        """开仓：创建持仓并提交。"""
        position = Position(
            symbol=symbol,
            name=name,
            quantity=quantity,
            avg_cost=avg_cost,
            status="open",
            user_id=user_id,
            account_id=account_id,
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

    async def list_open(
        self, user_id: int = 1, account_id: int | None = None
    ) -> list[Position]:
        """当前未平仓且未删除的持仓（按开仓时间升序）。

        Args:
            user_id: 用户 ID
            account_id: 账本过滤；None=全部账本
        """
        stmt = select(Position).where(
            Position.status == "open",
            Position.user_id == user_id,
            Position.deleted_at.is_(None),
        )
        if account_id is not None:
            stmt = stmt.where(Position.account_id == account_id)
        stmt = stmt.order_by(Position.opened_at, Position.id)
        return list((await self._session.execute(stmt)).scalars().all())

    async def get(self, position_id: int) -> Position | None:
        """按 ID 查询持仓（含已软删除的，供撤销恢复使用）。"""
        stmt = select(Position).where(Position.id == position_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_all(
        self, user_id: int = 1, account_id: int | None = None
    ) -> list[Position]:
        """所有未软删除的持仓（**含已平仓**），按开仓时间升序。

        收益曲线与获利分析需要已平仓持仓来核算已实现盈亏，故与
        :meth:`list_open` 区分（后者仅返回持仓中的）。
        """
        stmt = select(Position).where(
            Position.user_id == user_id, Position.deleted_at.is_(None)
        )
        if account_id is not None:
            stmt = stmt.where(Position.account_id == account_id)
        stmt = stmt.order_by(Position.opened_at, Position.id)
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_all_trades(
        self, user_id: int = 1, account_id: int | None = None
    ) -> list[TradeRecord]:
        """所有交易流水（排除已软删除持仓的流水），按成交时间**升序**。

        升序是回放重建收益曲线的前提（均价法成本随买卖顺序变化）。
        """
        stmt = (
            select(TradeRecord)
            .join(Position, TradeRecord.position_id == Position.id)
            .where(Position.user_id == user_id, Position.deleted_at.is_(None))
        )
        if account_id is not None:
            stmt = stmt.where(Position.account_id == account_id)
        stmt = stmt.order_by(TradeRecord.traded_at, TradeRecord.id)
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_trades(self, position_id: int) -> list[TradeRecord]:
        """持仓的交易流水（按时间倒序）。"""
        stmt = (
            select(TradeRecord)
            .where(TradeRecord.position_id == position_id)
            .order_by(desc(TradeRecord.traded_at), desc(TradeRecord.id))
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def query_trades(
        self,
        *,
        user_id: int = 1,
        account_id: int | None = None,
        side: str | None = None,
        position_id: int | None = None,
        symbol: str | None = None,
        keyword: str | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[TradeWithPosition]:
        """多条件查询交易流水（**倒序**，含账本名），供交易历史查询页使用。

        说明：返回**全量匹配行**（不分页），由服务层在内存中完成汇总与分页。
        理由——每笔卖出的已实现盈亏需按均价法逐笔回放（依赖同持仓的完整流水），
        且汇总口径必须覆盖全部匹配行而非当前页；个人账本数据量（千级）下
        一次取回最简单也最不容易出现「汇总与明细对不上」的问题。

        Args:
            account_id: 账本过滤；None=全部账本
            side: buy / sell；None=全部
            position_id: 指定持仓；None=全部持仓
            symbol: 品种代码精确匹配（如 518880）
            keyword: 模糊匹配持仓名称或品种代码
            start: 成交日期下界（含当日）
            end: 成交日期上界（含当日）
        """
        stmt = (
            select(TradeRecord, Position, Account.name)
            .join(Position, TradeRecord.position_id == Position.id)
            .outerjoin(Account, Position.account_id == Account.id)
            .where(Position.user_id == user_id, Position.deleted_at.is_(None))
        )
        if account_id is not None:
            stmt = stmt.where(Position.account_id == account_id)
        if side:
            stmt = stmt.where(TradeRecord.side == side)
        if position_id is not None:
            stmt = stmt.where(TradeRecord.position_id == position_id)
        if symbol:
            stmt = stmt.where(Position.symbol == symbol)
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(or_(Position.name.like(like), Position.symbol.like(like)))
        if start is not None:
            stmt = stmt.where(TradeRecord.traded_at >= datetime.combine(start, time.min))
        if end is not None:
            stmt = stmt.where(
                TradeRecord.traded_at < datetime.combine(end + timedelta(days=1), time.min)
            )
        stmt = stmt.order_by(desc(TradeRecord.traded_at), desc(TradeRecord.id))

        rows = (await self._session.execute(stmt)).all()
        return [
            TradeWithPosition(
                trade=trade,
                position=position,
                account_name=account_name or DEFAULT_ACCOUNT_NAME,
            )
            for trade, position, account_name in rows
        ]

    async def stats_by_account(self, user_id: int = 1) -> dict[int, AccountStats]:
        """按账本聚合持仓数 / 未平仓数 / 流水笔数 / 最近成交时间。

        Returns:
            ``{account_id: AccountStats}``；无数据的账本不出现在结果中
            （调用方用 ``AccountStats()`` 兜底零值）。
        """
        stats: dict[int, AccountStats] = {}

        pos_stmt = (
            select(
                Position.account_id,
                func.count(Position.id),
                # 用 CASE 而非 SQLite 3.32+ 的 iif()，保证老 SQLite 也能跑
                func.sum(case((Position.status == "open", 1), else_=0)),
            )
            .where(Position.user_id == user_id, Position.deleted_at.is_(None))
            .group_by(Position.account_id)
        )
        for account_id, total, opened in (await self._session.execute(pos_stmt)).all():
            stats[int(account_id)] = AccountStats(
                position_count=int(total or 0), open_count=int(opened or 0)
            )

        trade_stmt = (
            select(
                Position.account_id,
                func.count(TradeRecord.id),
                func.max(TradeRecord.traded_at),
            )
            .join(TradeRecord, TradeRecord.position_id == Position.id)
            .where(Position.user_id == user_id, Position.deleted_at.is_(None))
            .group_by(Position.account_id)
        )
        for account_id, count, last_at in (await self._session.execute(trade_stmt)).all():
            item = stats.setdefault(int(account_id), AccountStats())
            item.trade_count = int(count or 0)
            item.last_traded_at = last_at

        return stats

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
