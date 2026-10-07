"""V0.79.0 Step E：MacroThresholdCalculator + MacroFactorHistoryRepository 测试。

覆盖：
- 空表 → 5 因子全回退 hardcode（cb_gold 显式跳过）
- 60/252 样本下的 percentile 正确性
- 41-59 样本边界 → 单因子回退 hardcode
- 24h TTL 缓存命中
- (target, date) key 隔离
- cb_gold 即使种 252 日也走 hardcode
- upsert_batch 幂等
- is_dynamic_active 边界
- _percentile 边界（n=1、pct=0/100、夹值插值）
"""

from __future__ import annotations

import time as _time
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.repositories.db import async_session_factory
from app.repositories.macro_factor_history import MacroFactorHistoryRepository
from app.services.macro import MACRO_FACTOR_RULES
from app.services.macro_thresholds import (
    MacroThresholdCalculator,
    _percentile,
)

# ───────────────────────── 单元：_percentile ─────────────────────────


class TestPercentile:
    """线性插值 percentile 单测。"""

    def test_single_value(self) -> None:
        assert _percentile([42.0], 50.0) == 42.0
        assert _percentile([42.0], 90.0) == 42.0
        assert _percentile([42.0], 10.0) == 42.0

    def test_empty(self) -> None:
        assert _percentile([], 50.0) == 0.0

    def test_two_values(self) -> None:
        # n=2: P10 = v0 + 0.1*(v1-v0); P90 = v0 + 0.9*(v1-v0)
        result_10 = _percentile([10.0, 20.0], 10.0)
        result_90 = _percentile([10.0, 20.0], 90.0)
        assert abs(result_10 - 11.0) < 1e-9
        assert abs(result_90 - 19.0) < 1e-9

    def test_252_values(self) -> None:
        # n=252 → P10 rank = 0.1*251 = 25.1 → 在 idx 25 与 26 之间插值
        values = [float(i) for i in range(252)]
        p10 = _percentile(values, 10.0)
        p90 = _percentile(values, 90.0)
        # 线性: P10 = 25 + 0.1*(26-25) = 25.1
        assert abs(p10 - 25.1) < 1e-9
        # P90 = 225 + 0.9*(226-225) = 225.9
        assert abs(p90 - 225.9) < 1e-9


# ───────────────────────── 集成：calculator + repo ─────────────────────────


@pytest.fixture
async def repo() -> MacroFactorHistoryRepository:
    async with async_session_factory() as session:
        yield MacroFactorHistoryRepository(session)


def _hardcode_dict() -> dict[str, tuple[float, float]]:
    return {r["key"]: (float(r["best"]), float(r["worst"])) for r in MACRO_FACTOR_RULES}


async def _seed(
    repo: MacroFactorHistoryRepository,
    factor_key: str,
    values: list[float],
    target: str = "default",
    end_date: date | None = None,
    data_date: str = "2026-08-28",
) -> None:
    """种入 N 条历史（end_date 倒推 N 个工作日，每日一条不同 snapshot_date）。"""
    end = end_date or date.today()
    for i, v in enumerate(values):
        # 倒推 N 个日历日（不扣周末，仅测试用）
        snap = end - timedelta(days=i)
        await repo.upsert_batch(
            target=target,
            snapshot_date=snap,
            factors=[(factor_key, float(v), data_date, "美联储 H.15")],
        )


class TestCalculatorWithEmptyTable:
    """空表场景：5 因子全回退 hardcode。"""

    async def test_empty_table_returns_all_hardcode(
        self, repo: MacroFactorHistoryRepository
    ) -> None:
        calc = MacroThresholdCalculator(repo=repo, min_samples=60)
        thresholds = await calc.get_or_compute("default")
        assert thresholds == _hardcode_dict()

    async def test_is_dynamic_active_false_on_empty(
        self, repo: MacroFactorHistoryRepository
    ) -> None:
        calc = MacroThresholdCalculator(repo=repo)
        thresholds = await calc.get_or_compute("default")
        assert calc.is_dynamic_active(thresholds) is False


class TestCalculatorWithData:
    """有数据场景：4 滚动因子切到 percentile，cb_gold 永远 hardcode。"""

    async def test_252_samples_dxy_us10y_us30y_vix_dynamic(
        self, repo: MacroFactorHistoryRepository
    ) -> None:
        await _seed(repo, "dxy", [96.5 + i * 0.1 for i in range(252)])
        await _seed(repo, "us10y", [4.0 + i * 0.01 for i in range(252)])
        await _seed(repo, "us30y", [4.5 + i * 0.01 for i in range(252)])
        await _seed(repo, "vix", [15.0 + i * 0.05 for i in range(252)])

        calc = MacroThresholdCalculator(repo=repo, min_samples=60)
        thresholds = await calc.get_or_compute("default")
        hardcode = _hardcode_dict()

        # 4 个滚动因子阈值 ≠ hardcode
        for k in ("dxy", "us10y", "us30y", "vix"):
            assert thresholds[k] != hardcode[k], f"{k} should be dynamic"
        # cb_gold 显式跳过 → 走 hardcode
        assert thresholds["cb_gold"] == hardcode["cb_gold"]

        assert calc.is_dynamic_active(thresholds) is True

    async def test_cb_gold_even_with_252_samples_still_hardcode(
        self, repo: MacroFactorHistoryRepository
    ) -> None:
        await _seed(repo, "cb_gold", [1000.0] * 252)  # 252 个相同值

        calc = MacroThresholdCalculator(repo=repo, min_samples=60)
        thresholds = await calc.get_or_compute("default")
        assert thresholds["cb_gold"] == (1200.0, 500.0)  # hardcode
        # 仅 cb_gold dynamic，4 个滚动因子回退 → False
        assert calc.is_dynamic_active(thresholds) is False

    async def test_60_samples_minimum_dynamic(self, repo: MacroFactorHistoryRepository) -> None:
        await _seed(repo, "dxy", [96.0 + i * 0.1 for i in range(60)])
        calc = MacroThresholdCalculator(repo=repo, min_samples=60)
        thresholds = await calc.get_or_compute("default")
        assert thresholds["dxy"] != (95.0, 105.0)  # 切到 percentile

    async def test_59_samples_falls_back_to_hardcode(
        self, repo: MacroFactorHistoryRepository
    ) -> None:
        await _seed(repo, "dxy", [96.0 + i * 0.1 for i in range(59)])
        calc = MacroThresholdCalculator(repo=repo, min_samples=60)
        thresholds = await calc.get_or_compute("default")
        assert thresholds["dxy"] == (95.0, 105.0)  # 回退


class TestIsDynamicActive:
    """is_dynamic_active 边界。"""

    async def test_all_hardcode_returns_false(self, repo: MacroFactorHistoryRepository) -> None:
        calc = MacroThresholdCalculator(repo=repo)
        hardcode = _hardcode_dict()
        assert calc.is_dynamic_active(hardcode) is False

    async def test_three_dynamic_returns_false(self, repo: MacroFactorHistoryRepository) -> None:
        """3 因子切到 dynamic → 不足 4 阈值 → False。"""
        calc = MacroThresholdCalculator(repo=repo)
        thresholds = _hardcode_dict()
        # 改 dxy / us10y / us30y → 3 因子动态
        thresholds["dxy"] = (100.0, 90.0)
        thresholds["us10y"] = (4.0, 3.0)
        thresholds["us30y"] = (4.5, 3.5)
        assert calc.is_dynamic_active(thresholds) is False

    async def test_four_dynamic_returns_true(self, repo: MacroFactorHistoryRepository) -> None:
        """4 因子切到 dynamic → True。"""
        calc = MacroThresholdCalculator(repo=repo)
        thresholds = _hardcode_dict()
        thresholds["dxy"] = (100.0, 90.0)
        thresholds["us10y"] = (4.0, 3.0)
        thresholds["us30y"] = (4.5, 3.5)
        thresholds["vix"] = (20.0, 18.0)
        assert calc.is_dynamic_active(thresholds) is True


class TestCache:
    """24h TTL + (target, date) key 隔离。"""

    async def test_cache_hit_within_ttl(self, repo: MacroFactorHistoryRepository) -> None:
        await _seed(repo, "dxy", [96.0 + i * 0.1 for i in range(60)])
        calc = MacroThresholdCalculator(repo=repo, min_samples=60, ttl_seconds=3600)

        first = await calc.get_or_compute("default")
        # 第二次直接命中缓存（不查表）
        with patch.object(repo, "get_window") as mock_get:
            second = await calc.get_or_compute("default")
            mock_get.assert_not_called()
        assert second == first

    async def test_cache_key_isolates_by_date(self, repo: MacroFactorHistoryRepository) -> None:
        await _seed(repo, "dxy", [96.0 + i * 0.1 for i in range(60)])
        calc = MacroThresholdCalculator(repo=repo, min_samples=60)

        today = date.today()
        yesterday = today - timedelta(days=1)
        await calc.get_or_compute("default", today=today)
        await calc.get_or_compute("default", today=yesterday)
        # 不同日期应各自查表 → 结果独立写入缓存
        keys = list(calc._cache.keys())
        assert any(today.isoformat() in str(k) for k in keys)
        assert any(yesterday.isoformat() in str(k) for k in keys)

    async def test_cache_ttl_expiry(self, repo: MacroFactorHistoryRepository) -> None:
        await _seed(repo, "dxy", [96.0 + i * 0.1 for i in range(60)])
        calc = MacroThresholdCalculator(repo=repo, min_samples=60, ttl_seconds=10)

        await calc.get_or_compute("default")
        # 强制时间前进到 TTL 之外
        # 现在缓存已过期 → 应重新查表
        with (
            patch("app.services.macro_thresholds.time.time", return_value=_time.time() + 100),
            patch.object(repo, "get_window") as mock_get,
        ):
            await calc.get_or_compute("default")
            mock_get.assert_called()


class TestRepoUpsert:
    """MacroFactorHistoryRepository.upsert_batch 测试。"""

    async def test_upsert_batch_idempotent(self, repo: MacroFactorHistoryRepository) -> None:
        today = date.today()
        factors = [("dxy", 96.5, "2026-08-28", "美联储 H.15")]
        n1 = await repo.upsert_batch("default", today, factors)
        n2 = await repo.upsert_batch("default", today, factors)
        assert n1 >= 1
        assert n2 >= 1
        # 样本数仍是 1（覆盖而非累加）
        count = await repo.count_samples("default", "dxy")
        assert count == 1

    async def test_upsert_batch_empty(self, repo: MacroFactorHistoryRepository) -> None:
        n = await repo.upsert_batch("default", date.today(), [])
        assert n == 0

    async def test_get_window_orders_desc(self, repo: MacroFactorHistoryRepository) -> None:
        end = date.today()
        # 种 5 条，跨 5 个日历日
        factors = [("dxy", 100.0 + i, "2026-08-28", "美联储 H.15") for i in range(5)]
        # 同一 snapshot_date 是 UPSERT 唯一键，所以分 5 个日期
        for i, (k, v, dt, src) in enumerate(factors):
            await repo.upsert_batch(
                "default",
                end - timedelta(days=i),
                [(k, v, dt, src)],
            )
        window = await repo.get_window("default", "dxy", days=10)
        # 倒序：第一条是最新的（end）
        assert window[0].snapshot_date == end
        assert window[-1].snapshot_date == end - timedelta(days=4)
        assert len(window) == 5
