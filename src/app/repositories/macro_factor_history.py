"""每日宏观因子历史仓储（V0.79.0 Step E）。

为 ``MacroThresholdCalculator`` 提供：
- 批量 upsert（scheduler 每日 07:00 BJT 触发）；
- 滚动窗口范围查询（计算 252 日 90/10 分位）；
- 单因子样本计数（判定数据是否充足）。

唯一键 ``(target, snapshot_date, factor_key)`` 幂等覆盖。

⚠ **V0.124.0：``upsert_many`` 改为分块写**。
SQLite 单条语句的绑定变量上限是 ``SQLITE_LIMIT_VARIABLE_NUMBER``
（本机实测 **32766**），而每行要绑 **6** 个变量 ⇒ 一次最多约 **5 461** 行。
V0.124.0 的深回填一次要写 **2 万行**（12 万个绑定变量）⇒ 单语句必然
`sqlite3.OperationalError: too many SQL variables` ⇒ **整批回滚、零行落库**
（实测：抛错时表里一行都没多，不是「写了一半」）。
⇒ 现在按 ``UPSERT_CHUNK_SIZE`` 行一批切块，语义不变（仍然按同一唯一键幂等覆盖），
只是多了几次 commit —— 部分失败时重跑即可补齐（幂等）。
"""

from datetime import date, timedelta

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.daily_macro_factor import DailyMacroFactor
from app.repositories.upsert import (
    affected_row_count,
    build_upsert,
    session_dialect_name,
)

#: 单条 upsert 语句最多写入多少行。
#: 6 个绑定变量/行 ⇒ 1000 行 = 6000 变量，离 SQLite 的 32766 上限有 5 倍余量，
#: 也远低于老版本 SQLite 的 999 上限（兼容旧 libsqlite3）。
UPSERT_CHUNK_SIZE = 1000


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
        stmt = build_upsert(
            self._session,
            DailyMacroFactor.__table__,
            payload,
            index_elements=["target", "snapshot_date", "factor_key"],
            update_columns=["value", "data_date", "source"],
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return affected_row_count(
            result,
            dialect=session_dialect_name(self._session),
            expected_rows=len(payload),
        )

    async def upsert_many(
        self,
        target: str,
        rows: list[tuple[date, str, float, str, str]],
    ) -> int:
        """批量 upsert **跨多个日期** 的记录；返回受影响行数。

        V0.118.0 新增（历史回填用）。``upsert_batch`` 一次只写一个 ``snapshot_date``，
        回填 252 个交易日要调 252 次 —— 那是 252 次 commit，慢到不可接受。

        ``rows`` 每条为 ``(snapshot_date, factor_key, value, data_date, source)``。
        同样按 ``(target, snapshot_date, factor_key)`` 幂等覆盖。

        ⚠ **V0.124.0**：按 ``UPSERT_CHUNK_SIZE`` **分块**写 —— 一次 ``INSERT``
        带 N 行会绑 6N 个变量，超过 SQLite 的上限就会整批失败（见模块 docstring）。
        """
        if not rows:
            return 0
        written = 0
        for start in range(0, len(rows), UPSERT_CHUNK_SIZE):
            chunk = rows[start : start + UPSERT_CHUNK_SIZE]
            payload = [
                {
                    "target": target,
                    "snapshot_date": snapshot_date,
                    "factor_key": factor_key,
                    "value": value,
                    "data_date": data_date,
                    "source": source,
                }
                for (snapshot_date, factor_key, value, data_date, source) in chunk
            ]
            stmt = build_upsert(
                self._session,
                DailyMacroFactor.__table__,
                payload,
                index_elements=["target", "snapshot_date", "factor_key"],
                update_columns=["value", "data_date", "source"],
            )
            result = await self._session.execute(stmt)
            await self._session.commit()
            written += affected_row_count(
                result,
                dialect=session_dialect_name(self._session),
                expected_rows=len(payload),
            )
        return written

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

    async def get_latest_per_factor(self, target: str = "default") -> dict[str, DailyMacroFactor]:
        """每个因子**最近一条**落库记录（factor_key → 行）。

        V0.118.1 新增：作为宏观因子「上次成功落库的真实读数」的来源。

        **为什么需要它**：V0.118.0 给 8 个因子都接上了自动实时源，但兜底层仍是
        ``STATIC_REF`` 里 2026-08-28 的内置常量（dxy 96.5 / vix 18.5）。上游源一挂
        （DNS 故障、限流、网络抖动），宏观面就静默退回两个半月前的常量 —— 而库里
        明明存着前几轮抓到的真实读数。历史表就是这个「末次已知真值」的现成来源。

        取 ``snapshot_date`` 最大的那条：那是最近一次**真的观测到**该读数的时点。
        """
        sub = (
            select(
                DailyMacroFactor.factor_key,
                func.max(DailyMacroFactor.snapshot_date).label("max_date"),
            )
            .where(DailyMacroFactor.target == target)
            .group_by(DailyMacroFactor.factor_key)
            .subquery()
        )
        stmt = (
            select(DailyMacroFactor)
            .join(
                sub,
                and_(
                    DailyMacroFactor.factor_key == sub.c.factor_key,
                    DailyMacroFactor.snapshot_date == sub.c.max_date,
                ),
            )
            .where(DailyMacroFactor.target == target)
        )
        result = await self._session.execute(stmt)
        return {row.factor_key: row for row in result.scalars().all()}
