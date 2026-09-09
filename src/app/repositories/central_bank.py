"""央行购金数据 DB 仓储（CRUD）。"""

from datetime import date, datetime

from sqlalchemy import desc, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.central_bank import CentralBankPurchase


class CentralBankPurchaseRepository:
    """央行季度购金记录 CRUD。

    主要查询：按国家 / 按季度范围 / 最新季度 / T12M 合计。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, record: CentralBankPurchase) -> None:
        """单条 upsert（按 country_iso + quarter 唯一约束）。"""
        payload = {
            "country_iso": record.country_iso,
            "country_name": record.country_name,
            "quarter": record.quarter,
            "tonnes_net": record.tonnes_net,
            "source": record.source,
            "data_date": record.data_date,
        }
        stmt = sqlite_insert(CentralBankPurchase).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=["country_iso", "quarter"],
            set_={
                "country_name": stmt.excluded.country_name,
                "tonnes_net": stmt.excluded.tonnes_net,
                "source": stmt.excluded.source,
                "data_date": stmt.excluded.data_date,
            },
        )
        await self._session.execute(stmt)
        await self._session.commit()

    async def upsert_bulk(self, records: list[CentralBankPurchase]) -> int:
        """批量 upsert；返回受影响行数。"""
        if not records:
            return 0
        payload = [
            {
                "country_iso": r.country_iso,
                "country_name": r.country_name,
                "quarter": r.quarter,
                "tonnes_net": r.tonnes_net,
                "source": r.source,
                "data_date": r.data_date,
            }
            for r in records
        ]
        stmt = sqlite_insert(CentralBankPurchase).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=["country_iso", "quarter"],
            set_={
                "country_name": stmt.excluded.country_name,
                "tonnes_net": stmt.excluded.tonnes_net,
                "source": stmt.excluded.source,
                "data_date": stmt.excluded.data_date,
            },
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return result.rowcount or 0

    async def list_all(self) -> list[CentralBankPurchase]:
        """全部记录，按 quarter 倒序 + country_iso 正序。"""
        stmt = (
            select(CentralBankPurchase)
            .order_by(desc(CentralBankPurchase.quarter), CentralBankPurchase.country_iso)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_range(
        self,
        from_quarter: str | None = None,
        to_quarter: str | None = None,
        country_iso: str | None = None,
    ) -> list[CentralBankPurchase]:
        """按 (quarter 范围, country) 过滤；任一参数为 None 视为不过滤。"""
        stmt = select(CentralBankPurchase)
        if from_quarter is not None:
            stmt = stmt.where(CentralBankPurchase.quarter >= from_quarter)
        if to_quarter is not None:
            stmt = stmt.where(CentralBankPurchase.quarter <= to_quarter)
        if country_iso is not None:
            stmt = stmt.where(CentralBankPurchase.country_iso == country_iso)
        stmt = stmt.order_by(
            desc(CentralBankPurchase.quarter),
            CentralBankPurchase.country_iso,
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def latest_quarter(self) -> str | None:
        """最新数据季度（字符串）。"""
        stmt = select(CentralBankPurchase.quarter).order_by(
            desc(CentralBankPurchase.quarter)
        ).limit(1)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return row

    async def t12m_total(self) -> tuple[float, str, str] | None:
        """T12M（最近 4 季度合计）净购金吨数 + 窗口（如 "2025Q3–2026Q2"）。

        Returns:
            (total_tonnes, window_label, latest_quarter) 或 None（库为空）。
        """
        latest = await self.latest_quarter()
        if latest is None:
            return None

        # 推 4 个季度
        from app.repositories.central_bank_data import _previous_quarter

        quarters: list[str] = [latest]
        for _ in range(3):
            quarters.append(_previous_quarter(quarters[-1]))
        quarters.reverse()  # 从旧到新

        stmt = select(CentralBankPurchase.tonnes_net).where(
            CentralBankPurchase.quarter.in_(quarters)
        )
        result = await self._session.execute(stmt)
        total = sum(result.scalars().all())
        window = f"{quarters[0]}–{quarters[-1]}"
        return round(float(total), 1), window, latest

    async def latest_refresh(self) -> datetime | None:
        """最新数据记录的最后更新时间（UTC）。"""
        stmt = (
            select(CentralBankPurchase.updated_at)
            .order_by(desc(CentralBankPurchase.updated_at))
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
