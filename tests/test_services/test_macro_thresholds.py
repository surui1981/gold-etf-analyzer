"""V0.79.0 Step E：MacroThresholdCalculator + MacroFactorHistoryRepository 测试。

覆盖：
- 空表 → 11 因子全回退 hardcode（4 个低频因子显式跳过）
- 60/252 样本下的 percentile 正确性
- 41-59 样本边界 → 单因子回退 hardcode
- 24h TTL 缓存命中
- (target, date) key 隔离
- cb_gold / 3 个政府债务因子即使种 252 日也走 hardcode
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
    """有数据场景：7 个滚动因子切到 percentile，低频 4 因子永远 hardcode。

    V0.118.0：可滚动因子从 4 个变成 7 个（+us2y / +curve_10y2y / +real10y）。
    ``is_dynamic_active`` 的口径同步改成「**全部**可滚动因子都动态」——
    旧版的 ``>= 4`` 在 7 个因子里会松成「过半即算」，badge 会撒谎。

    V0.119.0：因子总数 8 → 11，但**可滚动数仍是 7** —— 新增的 3 个政府债务
    因子是季度/年度低频序列，与 ``cb_gold`` 同类，显式跳过滚动。
    """

    #: 7 个可滚动因子（cb_gold 与 3 个政府债务因子显式跳过）
    ROLLING = ("dxy", "us2y", "us10y", "us30y", "curve_10y2y", "real10y", "vix")

    async def test_252_samples_all_rolling_factors_dynamic(
        self, repo: MacroFactorHistoryRepository
    ) -> None:
        for k in self.ROLLING:
            await _seed(repo, k, [100.0 + i * 0.1 for i in range(252)])

        calc = MacroThresholdCalculator(repo=repo, min_samples=60)
        thresholds = await calc.get_or_compute("default")
        hardcode = _hardcode_dict()

        # 7 个滚动因子阈值 ≠ hardcode
        for k in self.ROLLING:
            assert thresholds[k] != hardcode[k], f"{k} should be dynamic"
        # cb_gold 显式跳过 → 走 hardcode
        assert thresholds["cb_gold"] == hardcode["cb_gold"]

        assert calc.is_dynamic_active(thresholds) is True

    async def test_one_rolling_factor_missing_keeps_whole_set_inactive(
        self, repo: MacroFactorHistoryRepository
    ) -> None:
        """少 1 个因子的样本 → 该因子回退 hardcode → 整体判 False（严格口径）。"""
        for k in self.ROLLING:
            if k == "real10y":
                continue
            await _seed(repo, k, [100.0 + i * 0.1 for i in range(252)])

        calc = MacroThresholdCalculator(repo=repo, min_samples=60)
        thresholds = await calc.get_or_compute("default")
        hardcode = _hardcode_dict()

        assert thresholds["real10y"] == hardcode["real10y"]
        assert calc.is_dynamic_active(thresholds) is False

    async def test_cb_gold_even_with_252_samples_still_hardcode(
        self, repo: MacroFactorHistoryRepository
    ) -> None:
        await _seed(repo, "cb_gold", [1000.0] * 252)  # 252 个相同值

        calc = MacroThresholdCalculator(repo=repo, min_samples=60)
        thresholds = await calc.get_or_compute("default")
        assert thresholds["cb_gold"] == (1200.0, 500.0)  # hardcode
        # 仅 cb_gold dynamic，7 个滚动因子回退 → False
        assert calc.is_dynamic_active(thresholds) is False

    async def test_gov_debt_factors_even_with_252_samples_still_hardcode(
        self, repo: MacroFactorHistoryRepository
    ) -> None:
        """V0.119.0：3 个政府债务因子即使种满 252 日也走 hardcode。

        季度/年度序列日频落表会把同一个值重复几十次 ⇒ P10 == P90 ⇒
        滚动分位退化成常数（``_friendly_score`` 撞 best == worst 分支恒返回 50）。
        """
        await _seed(repo, "us_gov_debt", [122.59] * 252)
        await _seed(repo, "cn_gov_debt", [88.33] * 252)
        await _seed(repo, "eu_gov_debt", [82.9] * 252)

        calc = MacroThresholdCalculator(repo=repo, min_samples=60)
        thresholds = await calc.get_or_compute("default")
        hardcode = _hardcode_dict()

        assert thresholds["us_gov_debt"] == hardcode["us_gov_debt"]
        assert thresholds["cn_gov_debt"] == hardcode["cn_gov_debt"]
        assert thresholds["eu_gov_debt"] == hardcode["eu_gov_debt"]

    async def test_60_samples_minimum_dynamic(self, repo: MacroFactorHistoryRepository) -> None:
        await _seed(repo, "dxy", [96.0 + i * 0.1 for i in range(60)])
        calc = MacroThresholdCalculator(repo=repo, min_samples=60)
        thresholds = await calc.get_or_compute("default")
        assert thresholds["dxy"] != (94.0, 107.0)  # 切到 percentile

    async def test_59_samples_falls_back_to_hardcode(
        self, repo: MacroFactorHistoryRepository
    ) -> None:
        await _seed(repo, "dxy", [96.0 + i * 0.1 for i in range(59)])
        calc = MacroThresholdCalculator(repo=repo, min_samples=60)
        thresholds = await calc.get_or_compute("default")
        assert thresholds["dxy"] == (94.0, 107.0)  # 回退


class TestRollingSignConvention:
    """V0.118.0：滚动分位的 best/worst 方向必须与因子的**符号约定**一致。

    回归背景：此前**所有**因子一律 ``best=P90``。对 6 个负相关因子
    （美元 / 三档美债 / 实际利率 / 10Y-2Y 利差，占宏观权重 65%）方向整个反了 ——
    美元指数创窗口新高会被判成「最利多黄金」给 100 分。
    该缺陷自 V0.79.0 起一直休眠（滚动窗口样本不足，从未真正激活），
    一旦按计划回填历史让滚动分位接管，6 个因子会集体反向。
    """

    async def test_negative_factor_best_is_low_percentile(
        self, repo: MacroFactorHistoryRepository
    ) -> None:
        """负相关因子（dxy）：best = P10（低分位），worst = P90。"""
        values = [90.0 + i * 0.2 for i in range(100)]  # 90.0 .. 109.8
        await _seed(repo, "dxy", values)

        calc = MacroThresholdCalculator(repo=repo, min_samples=60)
        thresholds = await calc.get_or_compute("default")
        best, worst = thresholds["dxy"]

        assert best == pytest.approx(_percentile(values, 10.0))
        assert worst == pytest.approx(_percentile(values, 90.0))
        assert best < worst, "负相关因子 best 必须小于 worst（值越低越利多黄金）"

    async def test_positive_factor_best_is_high_percentile(
        self, repo: MacroFactorHistoryRepository
    ) -> None:
        """正相关因子（vix）：best = P90（高分位），worst = P10。"""
        values = [10.0 + i * 0.2 for i in range(100)]
        await _seed(repo, "vix", values)

        calc = MacroThresholdCalculator(repo=repo, min_samples=60)
        thresholds = await calc.get_or_compute("default")
        best, worst = thresholds["vix"]

        assert best == pytest.approx(_percentile(values, 90.0))
        assert worst == pytest.approx(_percentile(values, 10.0))
        assert best > worst, "正相关因子 best 必须大于 worst"

    async def test_every_rolling_factor_follows_its_own_sign(
        self, repo: MacroFactorHistoryRepository
    ) -> None:
        """逐因子核对方向：每个**可滚动**因子都对得上自己的 ``positive`` 标志。"""
        from app.services.macro import SKIP_ROLLING_FACTORS

        for rule in MACRO_FACTOR_RULES:
            if rule["key"] in SKIP_ROLLING_FACTORS:
                continue
            await _seed(repo, rule["key"], [10.0 + i * 0.2 for i in range(100)])

        calc = MacroThresholdCalculator(repo=repo, min_samples=60)
        thresholds = await calc.get_or_compute("default")

        for rule in MACRO_FACTOR_RULES:
            key = rule["key"]
            if key in SKIP_ROLLING_FACTORS:
                continue
            best, worst = thresholds[key]
            if rule["positive"]:
                assert best > worst, f"{key} 是正相关因子，best 必须是高分位"
            else:
                assert best < worst, f"{key} 是负相关因子，best 必须是低分位"


class TestIsDynamicActive:
    """is_dynamic_active 边界。"""

    async def test_all_hardcode_returns_false(self, repo: MacroFactorHistoryRepository) -> None:
        calc = MacroThresholdCalculator(repo=repo)
        hardcode = _hardcode_dict()
        assert calc.is_dynamic_active(hardcode) is False

    async def test_three_dynamic_returns_false(self, repo: MacroFactorHistoryRepository) -> None:
        """3 个可滚动因子切到 dynamic → 其余 4 个仍 hardcode → False。"""
        calc = MacroThresholdCalculator(repo=repo)
        thresholds = _hardcode_dict()
        thresholds["dxy"] = (100.0, 90.0)
        thresholds["us10y"] = (4.0, 3.0)
        thresholds["us30y"] = (4.5, 3.5)
        assert calc.is_dynamic_active(thresholds) is False

    async def test_six_of_seven_dynamic_returns_false(
        self, repo: MacroFactorHistoryRepository
    ) -> None:
        """V0.118.0 口径护栏：6/7 个因子动态**不算**动态。

        旧版判据是硬编码 ``>= 4``，在 4 个可滚动因子的世界里恰好等价于「全动态」；
        因子扩到 7 个后照抄会松成「过半即算」—— badge 说「用滚动分位」，
        但仍有 1 个因子在用 2020-2023 的硬编码阈值。
        """
        calc = MacroThresholdCalculator(repo=repo)
        thresholds = _hardcode_dict()
        for k in ("dxy", "us2y", "us10y", "us30y", "curve_10y2y", "vix"):
            thresholds[k] = (100.0, 90.0)
        assert calc.is_dynamic_active(thresholds) is False

    async def test_all_seven_dynamic_returns_true(self, repo: MacroFactorHistoryRepository) -> None:
        """7 个可滚动因子全部 dynamic → True。"""
        calc = MacroThresholdCalculator(repo=repo)
        thresholds = _hardcode_dict()
        for k in ("dxy", "us2y", "us10y", "us30y", "curve_10y2y", "real10y", "vix"):
            thresholds[k] = (100.0, 90.0)
        assert calc.is_dynamic_active(thresholds) is True

    async def test_cb_gold_never_counts_as_rolling(
        self, repo: MacroFactorHistoryRepository
    ) -> None:
        """cb_gold 即使改了阈值也不算数（它显式跳过滚动）。"""
        calc = MacroThresholdCalculator(repo=repo)
        thresholds = _hardcode_dict()
        for k in ("dxy", "us2y", "us10y", "us30y", "curve_10y2y", "real10y", "vix"):
            thresholds[k] = (100.0, 90.0)
        thresholds["cb_gold"] = (999.0, 111.0)  # 改了也不该影响判定
        assert calc.is_dynamic_active(thresholds) is True

    async def test_rolling_band_equal_to_hardcode_still_counts_as_dynamic(
        self, repo: MacroFactorHistoryRepository
    ) -> None:
        """滚动分位算出的 best/worst **恰好等于**静态带时，仍要算「动态」。

        V0.120.0 修：旧判据是「阈值 ≠ hardcode」。但静态带常常就是拿同一段
        历史标定的 ⇒ 两者可能逐位相同 ⇒ 该因子被误报成「还在用静态阈值」。
        实测（资金流面 ``cn_money_gap``）：滚动 P10/P90 = -11.2 / -3.1，
        与静态带一模一样，旧判据下 badge 说 5/6 而真相是 6/6。
        """
        # dxy 静态带 = (94.0, 107.0)。构造 61 个样本让 P10/P90 精确落在这两个值上：
        # n=61 ⇒ rank = 60×0.1 = 6、60×0.9 = 54 都是整数 ⇒ 无插值误差。
        dxy_values = [1.0] * 6 + [94.0] + [100.0] * 47 + [107.0] + [200.0] * 6
        for k in ("us2y", "us10y", "us30y", "curve_10y2y", "real10y", "vix"):
            await _seed(repo, k, [100.0 + i * 0.1 for i in range(61)])
        await _seed(repo, "dxy", dxy_values)

        calc = MacroThresholdCalculator(repo=repo, min_samples=60)
        thresholds = await calc.get_or_compute("default")
        hardcode = _hardcode_dict()

        # 前提：dxy 的滚动带与静态带逐位相同
        assert thresholds["dxy"] == hardcode["dxy"] == (94.0, 107.0)

        # 旧判据（值比较）把它当成静态 → 6/7 → 整体 False
        assert calc.is_dynamic_active(thresholds) is False

        # 新判据（用计算器记录的滚动集）→ 7/7 都走了滚动分位 → True
        assert calc.rolling_keys("default") == frozenset(
            ("dxy", "us2y", "us10y", "us30y", "curve_10y2y", "real10y", "vix")
        )
        assert calc.is_dynamic_active(thresholds, target="default") is True


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
