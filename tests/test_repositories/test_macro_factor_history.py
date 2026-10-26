"""每日宏观因子历史仓储单测（V0.118.1 · 重点是 ``get_latest_per_factor``）。

``get_latest_per_factor`` 是「上次成功落库的真实读数」的来源 ——
上游源抓不到读数时，宏观因子靠它兜底，而不是退回 2026-08-28 的内置常量。
所以它的正确性直接决定「当前生效」这一列显示的是不是真值。
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.macro_factor_history import MacroFactorHistoryRepository


async def _upsert(
    repo: MacroFactorHistoryRepository,
    snapshot_date: date,
    rows: list[tuple[str, float, str, str]],
    target: str = "default",
) -> None:
    """rows 每条为 (factor_key, value, data_date, source)。"""
    await repo.upsert_batch(
        target=target,
        snapshot_date=snapshot_date,
        factors=rows,
    )


class TestGetLatestPerFactor:
    async def test_empty_db_returns_empty_dict(self, db_session: AsyncSession) -> None:
        """空 DB → 空 dict（不抛异常）。"""
        repo = MacroFactorHistoryRepository(db_session)
        assert await repo.get_latest_per_factor("default") == {}

    async def test_returns_latest_row_per_factor(self, db_session: AsyncSession) -> None:
        """每个因子取 snapshot_date 最大的那一条。"""
        repo = MacroFactorHistoryRepository(db_session)
        await _upsert(
            repo,
            date(2026, 10, 22),
            [("dxy", 101.5, "2026-10-22", "Yahoo DX-Y.NYB")],
        )
        await _upsert(
            repo,
            date(2026, 10, 23),
            [("dxy", 101.81, "2026-10-23", "Yahoo DX-Y.NYB")],
        )

        latest = await repo.get_latest_per_factor("default")
        assert set(latest) == {"dxy"}
        assert latest["dxy"].value == pytest.approx(101.81)
        assert latest["dxy"].data_date == "2026-10-23"
        assert latest["dxy"].snapshot_date == date(2026, 10, 23)

    async def test_multiple_factors_each_get_own_latest(self, db_session: AsyncSession) -> None:
        """不同因子的最新行可以来自不同 snapshot_date。"""
        repo = MacroFactorHistoryRepository(db_session)
        await _upsert(
            repo,
            date(2026, 10, 23),
            [("dxy", 101.81, "2026-10-23", "Yahoo DX-Y.NYB")],
        )
        await _upsert(
            repo,
            date(2026, 10, 22),
            [
                ("vix", 19.03, "2026-10-22", "FRED VIXCLS"),
                ("us10y", 4.96, "2026-10-22", "美联储 H.15"),
            ],
        )

        latest = await repo.get_latest_per_factor("default")
        assert set(latest) == {"dxy", "vix", "us10y"}
        assert latest["dxy"].value == pytest.approx(101.81)
        assert latest["vix"].value == pytest.approx(19.03)
        assert latest["us10y"].value == pytest.approx(4.96)

    async def test_ignores_other_target(self, db_session: AsyncSession) -> None:
        """别的 target 的行不能混进来（target 是宏观因子的维度键）。"""
        repo = MacroFactorHistoryRepository(db_session)
        await _upsert(
            repo,
            date(2026, 10, 23),
            [("dxy", 101.81, "2026-10-23", "Yahoo DX-Y.NYB")],
            target="ny",
        )

        assert await repo.get_latest_per_factor("default") == {}
        latest = await repo.get_latest_per_factor("ny")
        assert latest["dxy"].value == pytest.approx(101.81)

    async def test_same_snapshot_date_multiple_factors(self, db_session: AsyncSession) -> None:
        """同一天写入多个因子 → 各自都能取到（不能只返回一条）。"""
        repo = MacroFactorHistoryRepository(db_session)
        await _upsert(
            repo,
            date(2026, 10, 22),
            [
                ("dxy", 101.81, "2026-10-23", "Yahoo DX-Y.NYB"),
                ("vix", 19.03, "2026-10-22", "FRED VIXCLS"),
                ("us2y", 4.65, "2026-10-22", "美联储 H.15"),
                ("us10y", 4.96, "2026-10-22", "美联储 H.15"),
                ("us30y", 5.29, "2026-10-22", "美联储 H.15"),
                ("curve_10y2y", 0.31, "2026-10-22", "派生 10Y-2Y"),
                ("real10y", 2.64, "2026-10-22", "FRED DFII10"),
            ],
        )

        latest = await repo.get_latest_per_factor("default")
        assert len(latest) == 7
        assert latest["curve_10y2y"].value == pytest.approx(0.31)
