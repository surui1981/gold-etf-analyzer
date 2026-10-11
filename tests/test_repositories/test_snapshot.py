"""``repositories/snapshot.py`` 仓储层单测（V0.90.0 维护线）。

目标：覆盖 ``SnapshotRepository.list_in_range`` 全部分支（含 V0.90.0 新增）。

策略：
- 纯仓储层单测，依赖 ``db_session`` fixture（in-memory SQLite）
- 不依赖 FastAPI / HTTP
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.snapshot import DailySnapshot
from app.repositories.snapshot import SnapshotRepository


# ──────────────── 测试 fixture ────────────────


async def _insert_snapshot(
    session: AsyncSession, snapshot_date: date, **overrides
) -> DailySnapshot:
    """插入一行 DailySnapshot（默认值覆盖即可满足 schema 必填）。"""
    defaults = {
        "snapshot_date": snapshot_date,
        "symbol": "518880",
        "name": "黄金ETF华安",
        "close": 5.5,
        "change_pct": 1.2,
        "high": 5.6,
        "low": 5.4,
        "ma20": 5.45,
        "ma40": 5.40,
        "direction": "up",
        "tech_index": 65.0,
        "macro_index": 58.0,
        "news_index": 60.0,
        "trend_index": 61.0,
        "index_level": "偏多",
        "tech_detail": None,
        "macro_detail": '{"DXY": {"value": 104.5}}',
        "data_source": "live",
    }
    defaults.update(overrides)
    row = DailySnapshot(**defaults)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


# ──────────────── list_in_range（V0.90.0 新增）────────────


class TestListInRange:
    """V0.90.0 新增 ``list_in_range(start, end)`` 全部边界分支。"""

    async def test_empty_db_returns_empty_list(self, db_session: AsyncSession) -> None:
        """空 DB：返回空 list（不抛异常）。"""
        repo = SnapshotRepository(db_session)
        result = await repo.list_in_range(date(2026, 10, 1), date(2026, 10, 7))
        assert result == []

    async def test_single_date_in_range(
        self, db_session: AsyncSession
    ) -> None:
        """``start == end``：只返回当日 1 行。"""
        target = date(2026, 10, 1)
        await _insert_snapshot(db_session, target)

        repo = SnapshotRepository(db_session)
        result = await repo.list_in_range(target, target)

        assert len(result) == 1
        assert result[0].snapshot_date == target

    async def test_range_inclusive_endpoints(
        self, db_session: AsyncSession
    ) -> None:
        """范围含首尾（含端点）：插入 7 天，返回 7 行。"""
        start = date(2026, 10, 1)
        for i in range(7):
            await _insert_snapshot(db_session, start + timedelta(days=i))

        repo = SnapshotRepository(db_session)
        result = await repo.list_in_range(start, start + timedelta(days=6))

        assert len(result) == 7
        # 正序确认
        for i, row in enumerate(result):
            assert row.snapshot_date == start + timedelta(days=i)

    async def test_range_excludes_outside(
        self, db_session: AsyncSession
    ) -> None:
        """范围外的快照被排除：插入 1-15 日，查 5-10 日 → 6 行（5/6/7/8/9/10）。"""
        start = date(2026, 10, 1)
        for i in range(15):
            await _insert_snapshot(db_session, start + timedelta(days=i))

        repo = SnapshotRepository(db_session)
        q_start = start + timedelta(days=4)   # 10-05
        q_end = start + timedelta(days=9)     # 10-10
        result = await repo.list_in_range(q_start, q_end)

        assert len(result) == 6
        assert result[0].snapshot_date == q_start
        assert result[-1].snapshot_date == q_end

    async def test_ascending_order(
        self, db_session: AsyncSession
    ) -> None:
        """返回按日期**升序**（timeline 聚合需要顺序遍历）。"""
        start = date(2026, 10, 1)
        # 倒序插入 5 行，验证 list_in_range 输出仍升序
        for i in [4, 2, 0, 3, 1]:
            await _insert_snapshot(db_session, start + timedelta(days=i))

        repo = SnapshotRepository(db_session)
        result = await repo.list_in_range(start, start + timedelta(days=4))

        dates = [r.snapshot_date for r in result]
        assert dates == sorted(dates)
        assert len(result) == 5

    async def test_inverted_range_returns_empty(
        self, db_session: AsyncSession
    ) -> None:
        """``start > end``：返回空 list（**不抛异常**；调用方负责参数校验）。

        仓储层保持「零业务规则」：入参无意义时空返回；端点层负责 400 错误。
        """
        await _insert_snapshot(db_session, date(2026, 10, 5))

        repo = SnapshotRepository(db_session)
        result = await repo.list_in_range(date(2026, 10, 10), date(2026, 10, 1))

        assert result == []

    async def test_sparse_data_returns_only_existing(
        self, db_session: AsyncSession
    ) -> None:
        """稀疏数据：只插入 10-01 与 10-05，查 10-01 ~ 10-07 → 2 行（中间不补全）。"""
        await _insert_snapshot(db_session, date(2026, 10, 1))
        await _insert_snapshot(db_session, date(2026, 10, 5))

        repo = SnapshotRepository(db_session)
        result = await repo.list_in_range(date(2026, 10, 1), date(2026, 10, 7))

        assert len(result) == 2
        assert {r.snapshot_date for r in result} == {
            date(2026, 10, 1),
            date(2026, 10, 5),
        }

    async def test_does_not_affect_other_methods(
        self, db_session: AsyncSession
    ) -> None:
        """新增 ``list_in_range`` 不影响 ``get_by_date`` / ``list_recent`` / ``get_latest_before``。"""
        await _insert_snapshot(db_session, date(2026, 10, 1))
        await _insert_snapshot(db_session, date(2026, 10, 2))

        repo = SnapshotRepository(db_session)

        # get_by_date 仍能查
        row = await repo.get_by_date(date(2026, 10, 1))
        assert row is not None
        assert row.snapshot_date == date(2026, 10, 1)

        # list_recent 仍能查
        recent = await repo.list_recent(days=10)
        assert len(recent) == 2

        # get_latest_before 仍能查
        prev = await repo.get_latest_before(date(2026, 10, 5))
        assert prev is not None
        assert prev.snapshot_date == date(2026, 10, 2)


# ──────────────── 既有方法回归（防 schema 字段破坏）────────────


class TestExistingMethodsUnchanged:
    """V0.90.0 加 ``list_in_range`` 不影响既有 4 个仓储方法。"""

    async def test_get_by_date_still_works(
        self, db_session: AsyncSession
    ) -> None:
        await _insert_snapshot(db_session, date(2026, 10, 1))
        repo = SnapshotRepository(db_session)
        assert (await repo.get_by_date(date(2026, 10, 1))) is not None
        assert (await repo.get_by_date(date(2026, 10, 2))) is None

    async def test_upsert_still_works(self, db_session: AsyncSession) -> None:
        """upsert 硬编码白名单（``macro_detail`` 已在列）—— V0.90.0 schema 增字段不影响 upsert。"""
        repo = SnapshotRepository(db_session)
        snap = DailySnapshot(
            snapshot_date=date(2026, 10, 1),
            symbol="518880",
            name="黄金ETF华安",
            close=5.5, change_pct=1.0, high=5.6, low=5.4,
            ma20=5.45, ma40=5.40, direction="up",
            tech_index=65.0, macro_index=58.0, news_index=60.0,
            trend_index=61.0, index_level="偏多",
            macro_detail='{"DXY": {"value": 105}}',
            data_source="live",
        )
        await repo.upsert(snap)

        row = await repo.get_by_date(date(2026, 10, 1))
        assert row is not None
        assert row.macro_detail == '{"DXY": {"value": 105}}'