"""打分数据宽表仓储（V0.92.0）

物化宽表的数据访问层。所有方法默认按当前用户过滤（V0.80.0 #159 隔离）。

⚠ V0.79.0 任务 #162 教训：``upsert`` 字段白名单必须列全 —— insert 与
   update 路径同步，避免加列后"update 路径永远不写新字段"（与
   ``repositories/snapshot.py::upsert`` 同类陷阱）。

⚠ V0.80.0 #159 教训：所有方法加 ``user_id`` 参数，默认 ``None`` = 取
   当前请求上下文（``utils.user_scope.resolve_user_id``）。越权访问
   表现为「查不到」（返回空列表 / ``None``），不用 403，避免泄露。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scoring_wide import ScoringDailyWide
from app.utils.user_scope import resolve_user_id


class ScoringWideRepository:
    """打分数据宽表数据访问（V0.80.0 数据隔离）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ──────────── 单日查询 ────────────

    async def get_by_date(
        self, target_date: date, user_id: int | None = None
    ) -> ScoringDailyWide | None:
        """按日期取单日宽表行。"""
        user_id = resolve_user_id(user_id)
        stmt = select(ScoringDailyWide).where(
            ScoringDailyWide.date == target_date,
            ScoringDailyWide.user_id == user_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    # ──────────── 区间查询 ────────────

    async def list_in_range(
        self, start: date, end: date, user_id: int | None = None
    ) -> list[ScoringDailyWide]:
        """按日期范围取宽表行（升序，含首尾）。

        用于：
        - ``/api/v1/scoring/summary`` 端点：按 group_by 聚合
        - ``/api/v1/scoring/hit-stats`` 端点：按 horizon 聚合
        - ``/api/v1/scoring/by-tag`` 端点：basis_tags 维度

        入参边界（与 ``SnapshotRepository.list_in_range`` 一致）：
        - ``start == end`` → 只返回当日 1 行
        - ``start > end`` → 返回空 list（**不抛异常**，调用方负责参数校验）
        """
        user_id = resolve_user_id(user_id)
        if start > end:
            return []
        stmt = (
            select(ScoringDailyWide)
            .where(
                ScoringDailyWide.date >= start,
                ScoringDailyWide.date <= end,
                ScoringDailyWide.user_id == user_id,
            )
            .order_by(ScoringDailyWide.date.asc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_recent(
        self, days: int = 90, user_id: int | None = None
    ) -> list[ScoringDailyWide]:
        """最近 N 天宽表行（按日期倒序）。"""
        user_id = resolve_user_id(user_id)
        stmt = (
            select(ScoringDailyWide)
            .where(ScoringDailyWide.user_id == user_id)
            .order_by(ScoringDailyWide.date.desc())
            .limit(days)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_dates(self, user_id: int | None = None) -> list[date]:
        """存在宽表记录的全部日期（升序），用于回填决策与离线 CLI。"""
        user_id = resolve_user_id(user_id)
        stmt = (
            select(ScoringDailyWide.date)
            .where(ScoringDailyWide.user_id == user_id)
            .distinct()
            .order_by(ScoringDailyWide.date)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    # ──────────── 写入 ────────────

    async def upsert(self, row: ScoringDailyWide) -> ScoringDailyWide:
        """按日期插入或更新（同一自然日重复 ETL 为更新）。

        ⚠ V0.79.0 任务 #162 教训：**字段白名单必须列全**。新列加入此表
        必须同步追加到下方 tuple，否则同日再次 ETL 时该字段永远不会被更新
        （与 ``repositories/snapshot.py::upsert`` 同根因）。
        """
        existing = await self.get_by_date(row.date, user_id=row.user_id)
        if existing is None:
            self._session.add(row)
        else:
            for field in (
                # 隔离
                "snapshot_id",
                # 4 指数
                "tech_index",
                "macro_index",
                "news_index",
                "trend_index",
                "index_level",
                # 价格
                "close",
                "change_pct",
                "direction",
                "data_source",
                "gold_ny_close",  # V0.95.0 NY 金美元/盎司
                # 消息面
                "news_slot_count",
                "news_basis_tags",
                "news_backfilled_count",
                # 共振
                "resonance_signal",
                "resonance_subtype",
                # outcomes
                "actual_change_pct_t0",  # V0.93.0 T+0
                "actual_change_pct_t1",
                "actual_change_pct_t3",
                "actual_change_pct_t5",
                "hit_t0",  # V0.93.0 T+0
                "hit_t1",
                "hit_t3",
                "hit_t5",
                "outcome_pending_until",
            ):
                setattr(existing, field, getattr(row, field))
        await self._session.commit()
        return row
