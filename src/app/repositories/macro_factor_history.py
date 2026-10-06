"""每日宏观因子历史仓储（V0.79.0 Step E）。

为 ``MacroThresholdCalculator`` 提供：
- 批量 upsert（scheduler 每日 07:00 BJT 触发）；
- 滚动窗口范围查询（计算 252 日 90/10 分位）；
- 单因子样本计数（判定数据是否充足）。

唯一键 ``(target, snapshot_date, factor_key)`` 幂等覆盖。
"""

from datetime import date, timedelta

from sqlalchemy import desc, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.daily_macro_factor import DailyMacroFactor


class MacroFactorHistoryRepository:
    """每日宏观因子历史 CRUD。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_batch(
        self,
        target: str,
        snapshot_date: date,
        factors: list[tuple[str, float, str, str]],
    ) -> int:
        """批量 upsert；返回受影响行数。

        ``factors`` 每条为 ``(factor_key, value, data_date, source)``。
        同日重跑覆盖（commit 1-2 上线初期手工灌数据需要）。
        """
        if not factors:
            return 0
        payload = [
            {
                "target": target,
                "snapshot_date": snapshot_date,
                "factor_key": factor_key,
                "value": value,
                "data_date": data_date,
                "source": source,
            }
            for (factor_key, value, data_date, source) in factors
        ]
        stmt = sqlite_insert(DailyMacroFactor).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=["target", "snapshot_date", "factor_key"],
            set_={
                "value": stmt.excluded.value,
                "data_date": stmt.excluded.data_date,
                "source": stmt.excluded.source,
            },
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return result.rowcount or 0

    async def get_window(
        self,
        target: str,
        factor_key: str,
        days: int = 252,
        *,
        end_date: date | None = None,
    ) -> list[DailyMacroFactor]:
        """取最近 N 个交易日的该因子记录（按 snapshot_date 倒序）。"""
        cutoff = (end_date or date.today()) - timedelta(days=days)
        stmt = (
            select(DailyMacroFactor)
            .where(DailyMacroFactor.target == target)
            .where(DailyMacroFactor.factor_key == factor_key)
            .where(DailyMacroFactor.snapshot_date >= cutoff)
            .order_by(desc(DailyMacroFactor.snapshot_date))
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_samples(
        self,
        target: str,
        factor_key: str,
        days: int = 252,
        *,
        end_date: date | None = None,
    ) -> int:
        """窗口内样本数（判定数据是否充足）。"""
        cutoff = (end_date or date.today()) - timedelta(days=days)
        stmt = (
            select(DailyMacroFactor)
            .where(DailyMacroFactor.target == target)
            .where(DailyMacroFactor.factor_key == factor_key)
            .where(DailyMacroFactor.snapshot_date >= cutoff)
        )
        result = await self._session.execute(stmt)
        return len(result.scalars().all())
