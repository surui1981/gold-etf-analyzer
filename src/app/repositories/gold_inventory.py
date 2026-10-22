"""COMEX 黄金库存 DB 仓储（CRUD）。"""

from datetime import date

from sqlalchemy import desc, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.gold_inventory import GoldInventoryDaily


class GoldInventoryRepository:
    """COMEX 黄金库存日频记录 CRUD。

    唯一键是 ``inv_date``（单交易所单序列），所以 upsert 只需一个冲突目标 ——
    与 ``central_bank_purchases`` 的 ``(country_iso, quarter)`` 复合键不同。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_bulk(self, records: list[GoldInventoryDaily]) -> int:
        """按 ``inv_date`` 批量 upsert；返回受影响行数。

        Args:
            records: 待写入的观测。重复日期取后者（调用方已去重）。
        """
        if not records:
            return 0
        # ⚠ Core `insert()` **绕过 ORM 的 Python 侧 default**，只认 server_default。
        # 迁移里 source 是 NOT NULL + server_default，ORM default 只在 `db.add()`
        # 路径生效 —— 于是走 upsert_bulk 且调用方没显式给 source 时会直接
        # IntegrityError。仓储是公开 API，不能指望每个调用方都记得填。
        payload = [
            {
                "inv_date": r.inv_date,
                "tonnes": r.tonnes,
                "ounces": r.ounces,
                "source": r.source or "COMEX",
            }
            for r in records
        ]
        stmt = sqlite_insert(GoldInventoryDaily).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=["inv_date"],
            set_={
                "tonnes": stmt.excluded.tonnes,
                "ounces": stmt.excluded.ounces,
                "source": stmt.excluded.source,
            },
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return result.rowcount or 0

    async def list_since(self, since: date) -> list[GoldInventoryDaily]:
        """``inv_date >= since`` 的记录，按日期**升序**（前端直接画走势）。"""
        stmt = (
            select(GoldInventoryDaily)
            .where(GoldInventoryDaily.inv_date >= since)
            .order_by(GoldInventoryDaily.inv_date)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def latest(self) -> GoldInventoryDaily | None:
        """最新一条观测（按日期倒序取 1）；空表返回 None。"""
        stmt = select(GoldInventoryDaily).order_by(desc(GoldInventoryDaily.inv_date)).limit(1)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def count(self) -> int:
        """总行数（供 scheduler 判「表空要不要回填」）。"""
        from sqlalchemy import func

        stmt = select(func.count()).select_from(GoldInventoryDaily)
        result = await self._session.execute(stmt)
        return int(result.scalar() or 0)