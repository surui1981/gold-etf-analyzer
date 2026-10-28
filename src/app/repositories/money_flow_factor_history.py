"""资金流因子历史仓储（V0.120.0）。

为滚动分位计算器提供：
- 批量 upsert（scheduler 每日 07:00 BJT 触发）；
- **按观测日**取滚动窗口（周频 728 天 / 月频 1826 天，见因子规则的 ``window_days``）；
- 单因子样本计数（判定数据是否充足）；
- 每个因子最近一条落库记录（「末次落库」降级层）。

唯一键 ``(target, snapshot_date, factor_key)`` 幂等覆盖，其中 ``snapshot_date``
是**因子自身的观测日**（不是采集日）—— 这是本表与 ``daily_macro_factors``
最关键的差异，详见 ``models/daily_money_flow_factor.py`` 的模块 docstring。
"""

from datetime import date, timedelta

from sqlalchemy import and_, delete, desc, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.daily_money_flow_factor import DailyMoneyFlowFactor


class MoneyFlowFactorHistoryRepository:
    """资金流因子历史 CRUD。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_batch(
        self,
        target: str,
        rows: list[tuple[date, str, float, str, str]],
    ) -> int:
        """批量 upsert（跨多个观测日）；返回受影响行数。

        ``rows`` 每条为 ``(snapshot_date, factor_key, value, data_date, source)``，
        其中 ``snapshot_date`` 是**因子自身的观测日**。
        同一观测日重跑覆盖（幂等）。
        """
        if not rows:
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
            for (snapshot_date, factor_key, value, data_date, source) in rows
        ]
        stmt = sqlite_insert(DailyMoneyFlowFactor).values(payload)
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
    ) -> list[DailyMoneyFlowFactor]:
        """取最近 ``days`` **日历天**内该因子的观测记录（按观测日倒序）。

        窗口用日历天而非行数：周频 / 月频因子的观测日不连续，
        「最近 60 条」对月频因子来说只有 5 年，语义会随节奏漂移。
        """
        cutoff = (end_date or date.today()) - timedelta(days=days)
        stmt = (
            select(DailyMoneyFlowFactor)
            .where(DailyMoneyFlowFactor.target == target)
            .where(DailyMoneyFlowFactor.factor_key == factor_key)
            .where(DailyMoneyFlowFactor.snapshot_date >= cutoff)
            .where(DailyMoneyFlowFactor.snapshot_date <= (end_date or date.today()))
            .order_by(desc(DailyMoneyFlowFactor.snapshot_date))
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
            select(DailyMoneyFlowFactor)
            .where(DailyMoneyFlowFactor.target == target)
            .where(DailyMoneyFlowFactor.factor_key == factor_key)
            .where(DailyMoneyFlowFactor.snapshot_date >= cutoff)
        )
        result = await self._session.execute(stmt)
        return len(result.scalars().all())

    async def delete_factor(self, target: str, factor_key: str) -> int:
        """删掉某因子的全部历史行；返回删除行数。

        ⚠️ 只在**观测口径变了**时用（例如 V0.120.0 把 ``gold_etf_flow``
        的窗口末日从「最新交易日」改成「ISO 周末日」、``cn_margin_flow``
        从「当月至今」改成「已过完的月末」）——
        旧网格的行不会被新网格的 upsert 覆盖（``snapshot_date`` 不同），
        两张网格会并存 ⇒ 同一周/月被重复计入滚动分位窗口。
        删完必须重新回填，否则该因子会退回「末次落库」降级层。
        """
        stmt = delete(DailyMoneyFlowFactor).where(
            DailyMoneyFlowFactor.target == target,
            DailyMoneyFlowFactor.factor_key == factor_key,
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return result.rowcount or 0

    async def get_latest_per_factor(
        self, target: str = "default"
    ) -> dict[str, DailyMoneyFlowFactor]:
        """每个因子**最近一条**落库记录（factor_key → 行）。

        「末次已知真值」的来源：上游源挂掉时用它顶上，而不是内置静态常量。
        源标识带 ``末次落库`` 前缀 ⇒ 前端挂降级 chip，且**不再落表**
        （旧读数不能被记成今天的观测）。
        """
        sub = (
            select(
                DailyMoneyFlowFactor.factor_key,
                func.max(DailyMoneyFlowFactor.snapshot_date).label("max_date"),
            )
            .where(DailyMoneyFlowFactor.target == target)
            .group_by(DailyMoneyFlowFactor.factor_key)
            .subquery()
        )
        stmt = (
            select(DailyMoneyFlowFactor)
            .join(
                sub,
                and_(
                    DailyMoneyFlowFactor.factor_key == sub.c.factor_key,
                    DailyMoneyFlowFactor.snapshot_date == sub.c.max_date,
                ),
            )
            .where(DailyMoneyFlowFactor.target == target)
        )
        result = await self._session.execute(stmt)
        return {row.factor_key: row for row in result.scalars().all()}
