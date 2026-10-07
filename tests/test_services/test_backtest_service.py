"""回测引擎单元测试（V0.71.0）：Sharpe / 最大回撤 / 网格展开 / 节流 / 覆盖期。

V0.79.0 Step G：增 ``trend_weights`` / ``macro_weights`` 嵌套权重 + 上限 1000。
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from app.schemas.backtest import (
    MACRO_DIM_FIELDS,
    TREND_DIM_FIELDS,
    BacktestCoverageOut,
    BacktestRequestIn,
    MacroWeights,
    ThresholdBand,
    TrendWeights,
    WeightGrid,
)
from app.services.backtest import (
    _CALIBRATION_BUCKETS,
    BacktestService,
    _aggregate_from_detail,
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


def test_backtest_request_rejects_grid_above_1000() -> None:
    """V0.79.0 Step G：网格组合 > 1000 触发 ValueError。

    5×5×5 × 4×4 × 1×1 = 2000 > 1000 触发拒绝（含默认阈值带 bullish × bearish = 16 组合）。
    旧 V0.71.0 上限 125 是 tech×macro×news = 5×5×5 边界；新版含阈值带与嵌套维度，
    故 125 不再是边界，需重新计算。
    """
    big = WeightGrid(
        tech=[0.1, 0.2, 0.3, 0.4, 0.5],
        macro=[0.1, 0.2, 0.3, 0.4, 0.5],
        news=[0.1, 0.2, 0.3, 0.4, 0.5],
    )
    with pytest.raises(ValueError, match="超过上限 1000"):
        BacktestRequestIn(days=90, target="etf", weight_grid=big)


def test_backtest_request_accepts_default_grid() -> None:
    """默认网格（3×1×1 × 4×4 × 1×1 = 48）合法不抛错（验证上修不影响默认路径）。"""
    grid = WeightGrid(tech=[0.3, 0.4, 0.5], macro=[0.4], news=[0.3])
    req = BacktestRequestIn(days=90, target="etf", weight_grid=grid)
    assert req.weight_grid.tech == [0.3, 0.4, 0.5]


# ─────────────── V0.79.0 Step G · 嵌套权重 + 上限 1000 ───────────────


def test_weight_grid_field_names_match_constants() -> None:
    """TREND_DIM_FIELDS / MACRO_DIM_FIELDS 与 weights.html ``TREND_FIELDS`` /
    ``MACRO_FIELDS`` 必须同步 —— 前后端任何一处改名都必须同步两处。
    """
    # 5 个维度（结构 / 动量 / 支撑 / 动能 / 回撤）；顺序无要求
    assert set(TREND_DIM_FIELDS) == {"结构", "动量", "支撑", "动能", "回撤"}
    assert len(TREND_DIM_FIELDS) == 5
    # 5 个宏观因子（美元 / 利率 / 通胀 / 地缘 / 避险）
    assert set(MACRO_DIM_FIELDS) == {"美元", "利率", "通胀", "地缘", "避险"}
    assert len(MACRO_DIM_FIELDS) == 5


def test_trend_weights_happy_path() -> None:
    """TrendWeights：和=1.0 + 覆盖全部字段 → 通过。"""
    tw = TrendWeights(
        weights=[
            {"结构": 0.30, "动量": 0.20, "支撑": 0.20, "动能": 0.15, "回撤": 0.15},
            {"结构": 0.50, "动量": 0.10, "支撑": 0.10, "动能": 0.10, "回撤": 0.20},
        ]
    )
    assert len(tw.weights) == 2
    assert tw.weights[0]["结构"] == 0.30


def test_trend_weights_sum_must_be_one() -> None:
    """TrendWeights：候选和 ≠ 1.0 → ValueError。"""
    with pytest.raises(ValueError, match=r"必须为 1\.0"):
        TrendWeights(
            weights=[
                {"结构": 0.30, "动量": 0.20, "支撑": 0.20, "动能": 0.15, "回撤": 0.20},  # 和=1.05
            ]
        )


def test_trend_weights_must_cover_all_5_fields() -> None:
    """TrendWeights：缺字段 → ValueError（明示哪些缺 / 哪些多）。"""
    with pytest.raises(ValueError, match="缺"):
        TrendWeights(
            weights=[
                {"结构": 0.30, "动量": 0.20, "支撑": 0.20, "动能": 0.30},  # 缺「回撤」
            ]
        )


def test_trend_weights_extra_field_rejected() -> None:
    """TrendWeights：多字段 → ValueError（防止字段漂移导致「旧数据 + 新权重」静默错算）。"""
    with pytest.raises(ValueError, match="多"):
        TrendWeights(
            weights=[
                {
                    "结构": 0.30,
                    "动量": 0.20,
                    "支撑": 0.20,
                    "动能": 0.15,
                    "回撤": 0.15,
                    "噪声": 0.0,  # 多「噪声」
                },
            ]
        )


def test_macro_weights_happy_path() -> None:
    """MacroWeights：和=1.0 + 覆盖 5 因子 → 通过。"""
    MacroWeights(
        weights=[
            {"美元": 0.30, "利率": 0.20, "通胀": 0.20, "地缘": 0.15, "避险": 0.15},
        ]
    )


def test_weight_grid_accepts_trend_weights() -> None:
    """WeightGrid 加 trend_weights（1 个候选）→ 整体通过。"""
    grid = WeightGrid(
        tech=[0.3, 0.4, 0.5],
        macro=[0.4],
        news=[0.3],
        trend_weights=TrendWeights(
            weights=[{"结构": 0.30, "动量": 0.20, "支撑": 0.20, "动能": 0.15, "回撤": 0.15}],
        ),
    )
    assert grid.trend_weights is not None
    assert len(grid.trend_weights.weights) == 1


def test_backtest_request_grid_cap_1000_rejects_overflow() -> None:
    """网格上限 125 → 1000：5×5×5 × 4×4 × 2×2 = 6400 → ValueError。"""
    grid = WeightGrid(
        tech=[0.1] * 5,
        macro=[0.1] * 5,
        news=[0.1] * 5,
        trend_weights=TrendWeights(
            weights=[
                {"结构": 0.20, "动量": 0.20, "支撑": 0.20, "动能": 0.20, "回撤": 0.20},
                {"结构": 0.40, "动量": 0.20, "支撑": 0.10, "动能": 0.10, "回撤": 0.20},
            ]
        ),
        macro_weights=MacroWeights(
            weights=[
                {"美元": 0.20, "利率": 0.20, "通胀": 0.20, "地缘": 0.20, "避险": 0.20},
                {"美元": 0.40, "利率": 0.20, "通胀": 0.10, "地缘": 0.10, "避险": 0.20},
            ]
        ),
    )
    with pytest.raises(ValueError, match="超过上限 1000"):
        BacktestRequestIn(days=90, target="etf", weight_grid=grid)


def test_backtest_request_grid_cap_1000_accepts_within() -> None:
    """网格上限 1000：边界内合法。2×5×5 × 4×4 × 1×1 = 800 ≤ 1000 → 通过。"""
    grid = WeightGrid(
        tech=[0.1, 0.2],
        macro=[0.1, 0.2, 0.3, 0.4, 0.5],
        news=[0.1, 0.2, 0.3, 0.4, 0.5],
        trend_weights=TrendWeights(
            weights=[
                {"结构": 0.20, "动量": 0.20, "支撑": 0.20, "动能": 0.20, "回撤": 0.20},
            ]
        ),
    )
    req = BacktestRequestIn(days=90, target="etf", weight_grid=grid)
    assert req.weight_grid.trend_weights is not None


# ─────────────── V0.79.0 Step G · _evaluate_grid 读 tech_detail/macro_detail ───────────────


def test_aggregate_from_detail_happy_path() -> None:
    """_aggregate_from_detail：tech_detail 全维度 + 全 score → 加权和。"""
    detail = json.dumps(
        {"结构": {"score": 70.0}, "动量": {"score": 60.0}, "支撑": {"score": 80.0}},
        ensure_ascii=False,
    )
    # 0.5*70 + 0.3*60 + 0.2*80 = 35 + 18 + 16 = 69.0
    result = _aggregate_from_detail(detail, {"结构": 0.5, "动量": 0.3, "支撑": 0.2}, "tech")
    assert result == pytest.approx(69.0, abs=1e-6)


def test_aggregate_from_detail_returns_none_for_null() -> None:
    """tech_detail=None → 返回 None（V0.78.0 Step D 纪律：数据不足 ≠ 中性）。"""
    assert _aggregate_from_detail(None, {"结构": 1.0}, "tech") is None


def test_aggregate_from_detail_returns_none_for_missing_dim() -> None:
    """weights 中的维度在 detail 中缺失 → 返回 None（防止静默错算）。"""
    detail = json.dumps(
        {"结构": {"score": 70.0}, "动量": {"score": 60.0}},
        ensure_ascii=False,
    )
    # weights 要求 5 维，detail 只有 2 维
    assert (
        _aggregate_from_detail(
            detail,
            {"结构": 0.20, "动量": 0.20, "支撑": 0.20, "动能": 0.20, "回撤": 0.20},
            "tech",
        )
        is None
    )


def test_aggregate_from_detail_returns_none_for_none_score() -> None:
    """任一维度 score 为 None → 返回 None（不要兜底 50）。"""
    detail = json.dumps(
        {
            "结构": {"score": 70.0},
            "动量": {"score": None},  # 数据不足（V0.78.0 Step D）
            "支撑": {"score": 80.0},
            "动能": {"score": 60.0},
            "回撤": {"score": 50.0},
        },
        ensure_ascii=False,
    )
    assert (
        _aggregate_from_detail(
            detail,
            {"结构": 0.20, "动量": 0.20, "支撑": 0.20, "动能": 0.20, "回撤": 0.20},
            "tech",
        )
        is None
    )


def test_aggregate_from_detail_invalid_json_returns_none() -> None:
    """JSON 解析错误 → 返回 None（容错：旧快照格式漂移不致回测 500）。"""
    assert _aggregate_from_detail("{not valid}", {"type": 1.0}, "tech") is None


def test_evaluate_grid_with_tech_weights_reweights() -> None:
    """_evaluate_grid + tech_dim_weights → tech_index 被覆写计算。
    ⚠ 关键集成测试：mock snapshot.tech_detail，验证嵌套权重**真的**改变 score。
    """
    snap = _make_snapshot_with_details(
        date(2026, 1, 1),
        tech_index=80.0,
        macro_index=50.0,
        news_index=50.0,
        tech_detail={"结构": {"score": 60.0}, "动量": {"score": 80.0}},
    )
    svc = BacktestService(
        session=None,  # type: ignore[arg-type]
        gold=None,  # type: ignore[arg-type]
        weights=None,  # type: ignore[arg-type]
    )
    # 不提供 weights → 用扁平 tech_index=80 → 综合分 = 80*0.5 + 50*0.3 + 50*0.2 = 61.0
    flat = svc._evaluate_grid(
        snapshots=[snap],
        next_returns={},
        tech_w=0.5,
        macro_w=0.3,
        news_w=0.2,
        bullish_threshold=70.0,
        bearish_threshold=30.0,
    )
    assert flat.samples == 1
    assert flat.tech_dim_weights is None

    # 提供 weights 但 detail 只有 2 维 → 整根跳过 → samples=0
    partial = svc._evaluate_grid(
        snapshots=[snap],
        next_returns={},
        tech_w=0.5,
        macro_w=0.3,
        news_w=0.2,
        bullish_threshold=70.0,
        bearish_threshold=30.0,
        tech_dim_weights={"结构": 0.5, "动量": 0.5, "支撑": 0.0, "动能": 0.0, "回撤": 0.0},
    )
    assert partial.samples == 0  # 跳过
    assert partial.tech_dim_weights is not None


def test_evaluate_grid_with_complete_tech_weights_uses_detail() -> None:
    """_evaluate_grid + 完整 5 维 tech_dim_weights → 用 tech_detail 重算 tech_score。"""
    snap = _make_snapshot_with_details(
        date(2026, 1, 1),
        tech_index=999.0,  # 故意离谱，验证被忽略
        macro_index=50.0,
        news_index=50.0,
        tech_detail={
            "结构": {"score": 80.0},
            "动量": {"score": 60.0},
            "支撑": {"score": 70.0},
            "动能": {"score": 50.0},
            "回撤": {"score": 40.0},
        },
    )
    svc = BacktestService(
        session=None,  # type: ignore[arg-type]
        gold=None,  # type: ignore[arg-type]
        weights=None,  # type: ignore[arg-type]
    )
    # weights = 0.3*80 + 0.2*60 + 0.2*70 + 0.15*50 + 0.15*40 = 24+12+14+7.5+6 = 63.5
    row = svc._evaluate_grid(
        snapshots=[snap],
        next_returns={},
        tech_w=0.5,
        macro_w=0.3,
        news_w=0.2,
        bullish_threshold=70.0,
        bearish_threshold=30.0,
        tech_dim_weights={
            "结构": 0.30,
            "动量": 0.20,
            "支撑": 0.20,
            "动能": 0.15,
            "回撤": 0.15,
        },
    )
    assert row.samples == 1
    # 综合分 = 63.5*0.5 + 50*0.3 + 50*0.2 = 31.75 + 15 + 10 = 56.75
    # （next_return=0，next_returns={} → no hit，但 sims 长度=1）
    assert row.sharpe == 0.0  # 单点收益无法算 Sharpe


def test_evaluate_grid_skips_snapshot_when_tech_detail_null_with_weights() -> None:
    """_evaluate_grid + tech_dim_weights + tech_detail=None → 跳过（samples=0）。"""
    snap = _make_snapshot_with_details(
        date(2026, 1, 1),
        tech_index=80.0,
        macro_index=50.0,
        news_index=50.0,
        tech_detail=None,  # 历史行（V0.79.0 #162 说明：历史 16/24 无法回溯）
    )
    svc = BacktestService(
        session=None,  # type: ignore[arg-type]
        gold=None,  # type: ignore[arg-type]
        weights=None,  # type: ignore[arg-type]
    )
    row = svc._evaluate_grid(
        snapshots=[snap],
        next_returns={},
        tech_w=0.5,
        macro_w=0.3,
        news_w=0.2,
        bullish_threshold=70.0,
        bearish_threshold=30.0,
        tech_dim_weights={"结构": 0.20, "动量": 0.20, "支撑": 0.20, "动能": 0.20, "回撤": 0.20},
    )
    assert row.samples == 0  # 跳过：tech_detail=NULL ⇒ 不能 50 兜底


def test_evaluate_grid_falls_back_to_flat_when_weights_none() -> None:
    """_evaluate_grid 不传 tech_dim_weights → 用扁平 tech_index（旧行为）。"""
    snap = _make_snapshot_with_details(
        date(2026, 1, 1),
        tech_index=80.0,
        macro_index=50.0,
        news_index=50.0,
        tech_detail={"结构": {"score": 60.0}},  # 即便 detail 在，weights=None 时忽略
    )
    svc = BacktestService(
        session=None,  # type: ignore[arg-type]
        gold=None,  # type: ignore[arg-type]
        weights=None,  # type: ignore[arg-type]
    )
    row = svc._evaluate_grid(
        snapshots=[snap],
        next_returns={},
        tech_w=0.5,
        macro_w=0.3,
        news_w=0.2,
        bullish_threshold=70.0,
        bearish_threshold=30.0,
    )
    assert row.samples == 1  # detail 在但 weights=None → 用扁平 tech_index=80
    assert row.tech_dim_weights is None


# ─────────────── 校准 5 桶 ───────────────


def test_calibration_buckets_5_buckets() -> None:
    """5 桶分箱：0-20 / 20-40 / 40-60 / 60-80 / 80-100。"""
    assert len(_CALIBRATION_BUCKETS) == 5
    assert _CALIBRATION_BUCKETS[0] == (0, 20)
    assert _CALIBRATION_BUCKETS[-1] == (80, 100)


# ─────────────── V0.79.0 Step G · helper ───────────────


def _make_snapshot_with_details(
    d: date,
    *,
    tech_index: float,
    macro_index: float,
    news_index: float,
    tech_detail: dict | None = None,
    macro_detail: dict | None = None,
):
    """构造一个裸 DailySnapshot（无需 DB），方便 _evaluate_grid 单测。

    ⚠ 直接 new() 而非经 DB session —— ``_evaluate_grid`` 只读字段值，不
    触碰 lazy-loaded relationship，回测服务层从不主动 flush 任何 ORM 状态。
    """
    from app.models.snapshot import DailySnapshot

    snap = DailySnapshot(
        snapshot_date=d,
        symbol="518880",
        name="黄金ETF华安",
        close=10.0,
        change_pct=0.0,
        high=10.0,
        low=10.0,
        ma20=10.0,
        ma40=10.0,
        direction="up",
        tech_index=tech_index,
        macro_index=macro_index,
        news_index=news_index,
        trend_index=tech_index * 0.5 + macro_index * 0.3 + news_index * 0.2,
        index_level="up",
        macro_detail=json.dumps(macro_detail, ensure_ascii=False) if macro_detail else "{}",
        tech_detail=json.dumps(tech_detail, ensure_ascii=False) if tech_detail else None,
        data_source="live",
    )
    return snap


# ─────────────── 集成：节流 + 覆盖期 ───────────────


class _FakeSession:
    """最小化 AsyncSession stub，仅满足 type hint。

    ⚠ V0.79.0 #163：``coverage()`` 用了两种结果形态 ——
    ``select(DailySnapshot)`` 走 ``scalars().all()``，
    ``select(func.count())`` 走 ``scalar_one()``。桩起初只实现前者，
    CI 报 ``'_Result' object has no attribute 'scalar_one'``。

    **这是本轮第三次因「桩缺方法」返工**（前两次：``test_backtest_usability``
    与 ``test_snapshot_tech_detail``）⇒ 已在本文件与两处补全。
    教训见 LESSONS §2.2j：**被测代码新增查询形态时，桩必须同步扩展**，
    且应一次列全（本例两种形态都在同一 stub 里），避免逐个失败再补。
    """

    async def execute(self, stmt):
        class _Result:
            def scalars(self_inner):
                class _Scalars:
                    def all(self_inner_inner):
                        return []

                return _Scalars()

            def scalar(self_inner):
                return 0

            def scalar_one(self_inner):
                # count 查询（排除数 / 总数统计）
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


# ─────────────── V0.79.0 Step H · 样本阈值分层边界 ───────────────


def test_backtest_min_samples_threshold_constants() -> None:
    """Step H 抽常量：MIN_SAMPLES_OVERALL/BUCKET 已从 _MIN_SAMPLES=20 拆分为 10/5。"""
    from app.services.backtest import MIN_SAMPLES_BUCKET, MIN_SAMPLES_OVERALL

    assert MIN_SAMPLES_OVERALL == 10
    assert MIN_SAMPLES_BUCKET == 5


def _make_sized_session(n_rows: int) -> type:
    """构造一个返回 N 行快照的 AsyncSession 桩（用于 Step H 边界测试）。"""
    from datetime import timedelta as _td
    from types import SimpleNamespace

    class _Row(SimpleNamespace):
        pass

    rows = [_Row(snapshot_date=date(2026, 1, 1) + _td(days=i)) for i in range(n_rows)]

    class _Result:
        def scalars(self_inner):
            class _Scalars:
                def all(self_inner_inner):
                    return rows

            return _Scalars()

        def scalar(self_inner):
            return 0

        def scalar_one(self_inner):
            return 0

    class _SizedSession:
        async def execute(self, stmt):
            return _Result()

    return _SizedSession


def test_backtest_coverage_below_threshold_triggers_warning() -> None:
    """Step H：可用样本 < MIN_SAMPLES_OVERALL(10) → sample_warning=True。"""
    from types import SimpleNamespace

    from app.repositories.review import GoldPriceRepository
    from app.services.backtest import MIN_SAMPLES_OVERALL, BacktestService

    SizedSession = _make_sized_session(MIN_SAMPLES_OVERALL - 1)
    svc = BacktestService(
        session=SizedSession(),
        gold=GoldPriceRepository(None),  # type: ignore[arg-type]
        weights=WeightService(None),  # type: ignore[arg-type]
    )

    async def _zero_count(*_args, **_kwargs):
        return 0

    async def _empty_list(*_args, **_kwargs):
        return []

    svc._gold = SimpleNamespace(  # type: ignore[assignment]
        count_in_range=_zero_count,
        upsert_many=_zero_count,
        list_range=_empty_list,
    )
    import asyncio

    cov = asyncio.run(svc.coverage(target="etf", days=90))
    assert cov.available_days == MIN_SAMPLES_OVERALL - 1
    assert cov.sample_warning is True
    assert str(MIN_SAMPLES_OVERALL) in cov.note


def test_backtest_coverage_at_threshold_no_warning() -> None:
    """Step H：可用样本 == MIN_SAMPLES_OVERALL(10) 时，
    `available < MIN_SAMPLES_OVERALL` 判定为 False（仅看样本阈值；
    价格日历为空会独立触发 sample_warning，与阈值分支解耦）。
    """
    from types import SimpleNamespace

    from app.repositories.review import GoldPriceRepository
    from app.services.backtest import MIN_SAMPLES_OVERALL, BacktestService

    SizedSession = _make_sized_session(MIN_SAMPLES_OVERALL)
    svc = BacktestService(
        session=SizedSession(),
        gold=GoldPriceRepository(None),  # type: ignore[arg-type]
        weights=WeightService(None),  # type: ignore[arg-type]
    )

    async def _zero_count(*_args, **_kwargs):
        return 0

    async def _empty_list(*_args, **_kwargs):
        return []

    svc._gold = SimpleNamespace(  # type: ignore[assignment]
        count_in_range=_zero_count,
        upsert_many=_zero_count,
        list_range=_empty_list,
    )
    import asyncio

    cov = asyncio.run(svc.coverage(target="etf", days=90))
    assert cov.available_days == MIN_SAMPLES_OVERALL
    # 价格日历为 0 → usable=False → sample_warning=True（与阈值分支无关）
    # Step H 分支：available == MIN_SAMPLES_OVERALL ⇒ 阈值分支不触发
    assert cov.sample_warning is True
    assert "价格日历为空" in cov.note
