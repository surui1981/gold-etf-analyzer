"""资金流面三项改进的单测（V0.128.5）。

① **贴边饱和显式化**：线性评分把带外读数截断到 0/100 ⇒「刚好贴边」与「远远在外」一样。
   ⇒ 新增 ``position_pct``（未截断位置）+ ``saturated``（bottom/top）。
② **月度因子滞后收紧**：``max_lag_days`` 60 → 45（60 天意味着「一个半月前」仍算新鲜）。
③ **基准对照**：命中率必须与「闭眼猜」并排显示（见 test_scoring_benchmark.py）。
"""

from __future__ import annotations

import pytest

from app.services.money_flow import (
    MONEY_FLOW_FACTOR_RULES,
    _band_position,
    _lag_days,
)


class TestBandPosition:
    """① 贴边检测 + 未截断位置。"""

    def test_inside_band(self) -> None:
        pos, sat = _band_position(50.0, {"best": 100.0, "worst": 0.0})
        assert pos == pytest.approx(50.0)
        assert sat is None

    def test_bottom_saturated(self) -> None:
        pos, sat = _band_position(-20.0, {"best": 100.0, "worst": 0.0})
        assert pos == pytest.approx(-20.0)  # **未截断** ⇒ 看出「有多极端」
        assert sat == "bottom"

    def test_top_saturated(self) -> None:
        pos, sat = _band_position(150.0, {"best": 100.0, "worst": 0.0})
        assert pos == pytest.approx(150.0)
        assert sat == "top"

    def test_negative_band_orientation(self) -> None:
        """best 在低位（负相关因子）⇒ 位置公式仍然正确。"""
        # best=-11.2（低=好）, worst=-3.1（高=坏）
        pos, sat = _band_position(-2.7, {"best": -11.2, "worst": -3.1})
        assert pos < 0  # 超出「worst」那一侧 ⇒ 贴底（最坏）
        assert sat == "bottom"

    def test_degenerate_band(self) -> None:
        pos, sat = _band_position(1.0, {"best": 5.0, "worst": 5.0})
        assert pos == 50.0
        assert sat is None


class TestLagDays:
    """② 滞后天数。"""

    def test_none_when_no_obs_date(self) -> None:
        class _R:
            obs_date = None

        assert _lag_days(_R(), 45) is None

    def test_computes_days(self) -> None:
        from datetime import date, timedelta

        class _R:
            obs_date = date.today() - timedelta(days=26)

        assert _lag_days(_R(), 45) == 26


class TestMonthlyLagCapTightened:
    """② 月度因子的滞后上限必须是 45 天（不是 60）。"""

    def test_monthly_factors_use_45_days(self) -> None:
        monthly = [r for r in MONEY_FLOW_FACTOR_RULES if r["cadence"] == "monthly"]
        assert monthly, "应有月度因子"
        for rule in monthly:
            assert rule["max_lag_days"] == 45, (
                f"{rule['key']} 的 max_lag_days 应为 45（60 天意味着「一个半月前」仍算新鲜）"
            )

    def test_weekly_factors_unchanged(self) -> None:
        weekly = [r for r in MONEY_FLOW_FACTOR_RULES if r["cadence"] == "weekly"]
        assert weekly
        for rule in weekly:
            assert rule["max_lag_days"] == 14


class TestFlowFaceWeightsUnchanged:
    """回归：因子权重之和仍是 1（V0.128.5 没动权重，只加了显示字段）。"""

    def test_weights_sum_to_one(self) -> None:
        total = sum(float(r["weight"]) for r in MONEY_FLOW_FACTOR_RULES)
        assert total == pytest.approx(1.0, abs=1e-6)
