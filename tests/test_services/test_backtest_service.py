"""回测引擎单元测试（V0.71.0）：Sharpe / 最大回撤 / 网格展开 / 节流 / 覆盖期。"""

from __future__ import annotations

import pytest

from app.schemas.backtest import (
    BacktestCoverageOut,
    BacktestRequestIn,
    ThresholdBand,
    WeightGrid,
)
from app.services.backtest import (
    _CALIBRATION_BUCKETS,
    BacktestService,
    _direction_from_score,
    compute_max_drawdown,
    compute_sharpe,
)
from app.services.review import judge_hit
from app.services.settings import WeightService

# ─────────────── 纯函数 ───────────────


def test_compute_sharpe_positive_trend_high() -> None:
    """线性增长收益（带波动）→ 高 sharpe（mean > 0, std > 0）。"""
    # 模拟稳定上涨但有波动：1% 上下波动（std 大于 0）
    returns = [0.5, -0.3, 0.7, -0.2, 0.6, -0.4, 0.8]
    s = compute_sharpe(returns)
    # 简化：mean ~0.24, std ~0.46 → sharpe ≈ 0.52 × √252 ≈ 8.3
    assert s > 0, f"上涨序列 sharpe 应 > 0，实际 {s}"


def test_compute_sharpe_negative_trend_negative() -> None:
    """线性下跌收益（带波动）→ 负 sharpe。"""
    returns = [-0.5, 0.3, -0.7, 0.2, -0.6, 0.4, -0.8]
    s = compute_sharpe(returns)
    assert s < 0, f"下跌序列 sharpe 应 < 0，实际 {s}"


def test_compute_sharpe_zero_variance_returns_zero() -> None:
    """全 0 数据 → 零方差 → 0.0（不抛错）。"""
    assert compute_sharpe([0.0, 0.0, 0.0, 0.0]) == 0.0


def test_compute_sharpe_single_value_returns_zero() -> None:
    """单数据点 → 0.0（不足 2 个不计算）。"""
    assert compute_sharpe([1.5]) == 0.0


def test_compute_sharpe_empty_returns_zero() -> None:
    """空列表 → 0.0。"""
    assert compute_sharpe([]) == 0.0


def test_compute_max_drawdown_monotonic_up_returns_zero() -> None:
    """单调上升净值 → 0%。"""
    equity = [1.0, 1.1, 1.2, 1.3, 1.5]
    assert compute_max_drawdown(equity) == 0.0


def test_compute_max_drawdown_50pct_drop_returns_50() -> None:
    """净值从 100 跌到 50 → 50%。"""
    equity = [100.0, 80.0, 50.0, 60.0, 70.0]
    assert compute_max_drawdown(equity) == 50.0


def test_compute_max_drawdown_empty_returns_zero() -> None:
    """空序列 → 0%。"""
    assert compute_max_drawdown([]) == 0.0


def test_direction_from_score_thresholds() -> None:
    """阈值带 → 方向判定（bullish ≥ 阈值 / bearish ≤ 阈值 / NEUTRAL 中间）。"""
    from app.schemas.common import DirectionSignal

    assert _direction_from_score(70.0, 55.0, 45.0) == DirectionSignal.BULLISH
    assert _direction_from_score(56.0, 55.0, 45.0) == DirectionSignal.BULLISH
    assert _direction_from_score(50.0, 55.0, 45.0) == DirectionSignal.NEUTRAL
    assert _direction_from_score(40.0, 55.0, 45.0) == DirectionSignal.BEARISH
    assert _direction_from_score(30.0, 55.0, 45.0) == DirectionSignal.BEARISH


def test_judge_hit_integration() -> None:
    """judge_hit 在回测中作为 T+1 命中判定器（与 review 一致）。"""
    from app.schemas.common import DirectionSignal

    # BULLISH + 上涨 → 命中
    hit, _label = judge_hit(DirectionSignal.BULLISH, 1.0)
    assert hit is True
    # BULLISH + 下跌 → 未命中
    hit, _label = judge_hit(DirectionSignal.BULLISH, -1.0)
    assert hit is False
    # BEARISH + 下跌 → 命中
    hit, _label = judge_hit(DirectionSignal.BEARISH, -1.0)
    assert hit is True


# ─────────────── 阈值带 / 网格校验 ───────────────


def test_threshold_band_default_values() -> None:
    """默认阈值带：bullish=[55,60,65,70] / bearish=[45,40,35,30]。"""
    band = ThresholdBand()
    assert band.bullish == [55, 60, 65, 70]
    assert band.bearish == [45, 40, 35, 30]


def test_weight_grid_round_to_4_decimals() -> None:
    """权重候选精度校验。"""
    grid = WeightGrid(tech=[0.333333], macro=[0.4], news=[0.266667])
    assert grid.tech[0] == 0.3333
    assert grid.news[0] == 0.2667


def test_weight_grid_reject_out_of_range() -> None:
    """权重候选超出 [0,1] 抛 ValueError。"""
    with pytest.raises(ValueError):
        WeightGrid(tech=[1.5], macro=[0.4], news=[0.3])
    with pytest.raises(ValueError):
        WeightGrid(tech=[-0.1], macro=[0.4], news=[0.3])


def test_backtest_request_rejects_grid_above_125() -> None:
    """网格组合 > 125 触发 ValueError（前端 UI 性能上限，5×5×5 是边界）。"""
    # 5×5×6 = 150 > 125 触发拒绝
    big = WeightGrid(tech=[0.1, 0.2, 0.3, 0.4, 0.5], macro=[0.1, 0.2, 0.3, 0.4, 0.5], news=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6])
    with pytest.raises(ValueError, match="超过 UI 性能上限"):
        BacktestRequestIn(days=90, target="etf", weight_grid=big)


def test_backtest_request_accepts_125_grid() -> None:
    """网格组合 = 125（5×5×5 边界）合法不抛错。"""
    grid = WeightGrid(tech=[0.1, 0.2, 0.3, 0.4, 0.5], macro=[0.1, 0.2, 0.3, 0.4, 0.5], news=[0.1, 0.2, 0.3, 0.4, 0.5])
    req = BacktestRequestIn(days=90, target="etf", weight_grid=grid)
    assert req.weight_grid.tech == [0.1, 0.2, 0.3, 0.4, 0.5]


# ─────────────── 校准 5 桶 ───────────────


def test_calibration_buckets_5_buckets() -> None:
    """5 桶分箱：0-20 / 20-40 / 40-60 / 60-80 / 80-100。"""
    assert len(_CALIBRATION_BUCKETS) == 5
    assert _CALIBRATION_BUCKETS[0] == (0, 20)
    assert _CALIBRATION_BUCKETS[-1] == (80, 100)


# ─────────────── 集成：节流 + 覆盖期 ───────────────


class _FakeSession:
    """最小化 AsyncSession stub，仅满足 type hint。"""

    async def execute(self, stmt):
        class _Result:
            def scalars(self_inner):
                class _Scalars:
                    def all(self_inner_inner):
                        return []

                return _Scalars()

            def scalar(self_inner):
                return 0

        return _Result()


def test_coverage_empty_snapshots_returns_warning() -> None:
    """空 daily_snapshots 表：coverage 返回 note + sample_warning=True。"""
    from app.repositories.review import GoldPriceRepository

    svc = BacktestService(
        session=_FakeSession(),
        gold=GoldPriceRepository(None),  # type: ignore[arg-type]
        weights=WeightService(None),  # type: ignore[arg-type]
    )
    import asyncio

    cov = asyncio.run(svc.coverage(target="etf", days=90))
    assert isinstance(cov, BacktestCoverageOut)
    assert cov.available_days == 0
    assert cov.sample_warning is True
    assert "无法回测" in cov.note


def test_backtest_service_imports() -> None:
    """BacktestService 类签名检查（无 DB 实际运行）。"""
    assert hasattr(BacktestService, "coverage")
    assert hasattr(BacktestService, "run")
    assert hasattr(BacktestService, "_evaluate_grid")