"""趋势分析服务单元测试：均线、方向判定与追踪指数。"""

from datetime import date, timedelta

import pytest

from app.repositories.market_data import GoldKline
from app.schemas.common import DirectionSignal
from app.schemas.market import MacroIndexOut, TrendDirection, TrendIndexLevel
from app.services.trend import (
    GROUP_MAPPING,
    GROUP_WEIGHTS,
    TREND_WEIGHTS,
    TrendService,
    moving_average,
)


class FakeMacro:
    """假宏观服务：固定中性 50 分，避免测试依赖网络。"""

    async def evaluate(self) -> MacroIndexOut:
        return MacroIndexOut(
            score=50.0,
            direction=DirectionSignal.NEUTRAL,
            factors=[],
            summary="测试宏观",
        )


class FakeMacroFixed:
    """假宏观服务：固定分数（用于验证「面被剔除后综合指数按有效面归一化」）。"""

    def __init__(self, score: float) -> None:
        self._score = score

    async def evaluate(self) -> MacroIndexOut:
        return MacroIndexOut(
            score=self._score,
            direction=DirectionSignal.NEUTRAL,
            factors=[],
            summary="测试宏观",
        )


def _service(klines: list[GoldKline], macro_score: float | None = None) -> TrendService:
    macro = FakeMacro() if macro_score is None else FakeMacroFixed(macro_score)
    return TrendService(FakeRepo(klines), macro=macro)


class FakeRepo:
    """内存假仓储：注入确定性 K 线序列。"""

    def __init__(self, klines: list[GoldKline]) -> None:
        self._k = klines

    async def get_gold_history(self, days: int = 60) -> list[GoldKline]:
        return self._k

    async def get_gold_gram_history(self, days: int = 60) -> list[GoldKline]:
        return self._k

    async def get_us_gold_history(self, days: int = 60) -> list[GoldKline]:
        return self._k


def _mk_klines(closes: list[float]) -> list[GoldKline]:
    base = date(2026, 6, 1)
    return [
        GoldKline(
            date=base + timedelta(days=i),
            open=c,
            close=c,
            high=round(c * 1.01, 3),
            low=round(c * 0.99, 3),
            volume=1000.0,
        )
        for i, c in enumerate(closes)
    ]


def test_moving_average_window() -> None:
    """窗口不足返回 None，窗口足够后输出滑动均值。"""
    assert moving_average([1, 2, 3, 4], 2) == [None, 1.5, 2.5, 3.5]
    assert moving_average([1, 2], 5) == [None, None]


async def test_upward_trend_detected() -> None:
    """持续上行序列应判定为上升趋势。"""
    closes = [round(1 + i * 0.01, 3) for i in range(60)]
    service = _service(_mk_klines(closes))
    result = await service.analyze(days=60)

    assert result.metrics.direction == TrendDirection.UP
    assert result.metrics.change_pct > 0
    assert result.metrics.trading_days == 60
    assert len(result.points) == 60
    # 最新 MA20 应为最近 20 个收盘价均值
    expected_ma20 = round(sum(closes[-20:]) / 20, 3)
    assert result.metrics.ma20 == expected_ma20


async def test_downward_trend_detected() -> None:
    """持续下行序列应判定为下降趋势。"""
    closes = [round(2 - i * 0.01, 3) for i in range(60)]
    service = _service(_mk_klines(closes))
    result = await service.analyze(days=60)

    assert result.metrics.direction == TrendDirection.DOWN
    assert result.metrics.change_pct < 0


async def test_insufficient_data_raises() -> None:
    """数据不足 2 个交易日应报错。"""
    service = _service(_mk_klines([1.0]))
    try:
        await service.analyze(days=60)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_trend_weights_sum_to_one() -> None:
    """追踪指数权重必须归一。"""
    assert sum(TREND_WEIGHTS.values()) == pytest.approx(1.0)


async def test_recent_changes_1d_and_5d() -> None:
    """指标摘要含昨日涨跌（1 日）与近 5 个交易日涨跌。"""
    closes = [round(100 + i * 1.0, 3) for i in range(60)]  # 每日 +1
    result = await _service(_mk_klines(closes)).analyze(days=60)
    m = result.metrics

    # closes[-1]=159, [-2]=158, [-6]=154
    assert m.change_pct_1d == pytest.approx((159 - 158) / 158 * 100, abs=0.05)
    assert m.change_pct_5d == pytest.approx((159 - 154) / 154 * 100, abs=0.05)


async def test_recent_changes_short_series() -> None:
    """数据不足时近期涨跌返回 0，不报错。"""
    assert TrendService._recent_changes([]) == (0.0, 0.0)
    assert TrendService._recent_changes([10.0]) == (0.0, 0.0)
    # 不足 6 根时，5 日涨跌退化为与首根比较
    assert TrendService._recent_changes([100.0, 101.0, 102.0])[1] == pytest.approx(2.0, abs=0.01)


async def test_trend_index_components() -> None:
    """上升序列应输出 5 个参数维度 + 偏多综合指数。"""
    closes = [round(1 + i * 0.01, 3) for i in range(60)]
    service = _service(_mk_klines(closes))
    result = await service.analyze(days=60)

    assert len(result.indicators) == 5
    assert result.index.score >= 55
    assert result.index.level in (TrendIndexLevel.UP, TrendIndexLevel.STRONG_UP)
    # 技术面维度贡献求和 = 技术面分；综合指数 = 技术×0.3 + 宏观×0.4 + 消息面×0.3（未打分中性50）
    tech_sum = sum(i.contribution for i in result.indicators)
    assert tech_sum == pytest.approx(98.5, abs=0.5)
    assert result.index.score == pytest.approx(tech_sum * 0.3 + 50.0 * 0.4 + 50.0 * 0.3, abs=0.5)
    # 宏观参考 + 消息面
    assert result.macro.score == 50.0
    assert result.news.score == 50.0
    assert result.news.scored is False
    # 全部维度分数在 0-100
    assert all(0 <= i.score <= 100 for i in result.indicators)


async def test_weak_trend_index_low_score() -> None:
    """单边下行序列应输出偏空指数。"""
    closes = [round(2 - i * 0.01, 3) for i in range(60)]
    service = _service(_mk_klines(closes))
    result = await service.analyze(days=60)

    assert result.index.score < 45
    assert result.index.level in (TrendIndexLevel.DOWN, TrendIndexLevel.STRONG_DOWN)


async def test_multi_target_symbols() -> None:
    """多标的支持：ny/gram/etf 返回对应 symbol 与名称。"""
    closes = [round(1 + i * 0.01, 3) for i in range(60)]
    service = _service(_mk_klines(closes))

    ny = await service.analyze(days=60, target="ny")
    assert ny.symbol == "GC"
    assert "纽约金" in ny.name

    gram = await service.analyze(days=60, target="gram")
    assert gram.symbol == "Au99.99"
    assert "上海金" in gram.name

    etf = await service.analyze(days=60, target="etf")
    assert etf.symbol == "518880"


# ───────────────────── V0.64.0 多时间框架（周/月线聚合）─────────────────────


async def test_v064_analyze_interval_field_default_d() -> None:
    """V0.64.0：默认 interval="D"，响应字段 interval=D，行为与之前一致（5 维 indicators 仍输出）。"""
    closes = [round(1 + i * 0.01, 3) for i in range(60)]
    service = _service(_mk_klines(closes))
    result = await service.analyze(days=60)
    assert result.interval == "D"
    assert len(result.indicators) == 5


async def test_v064_analyze_interval_w_aggregates_and_skips_indicators() -> None:
    """V0.64.0：interval="W" 触发聚合 + 技术面 indicators 旁路 + 宏观/消息面仍正常合成。"""
    closes = [round(100 + i * 0.5, 3) for i in range(14)]  # 14 个日 K 跨 2 个 ISO 周
    service = _service(_mk_klines(closes))
    result = await service.analyze(days=14, interval="W")

    assert result.interval == "W"
    assert result.metrics.trading_days == 2  # 14 个日 K 聚合到 2 个周 K
    assert len(result.points) == 2
    # W 模式下 indicators 旁路（空列表 + 技术面按中性 50）
    assert result.indicators == []
    assert result.index.components.get("tech") == 50.0
    # 宏观 + 消息面仍正常合成（默认 50）
    assert result.macro.score == 50.0
    assert result.news.score == 50.0
    # 摘要反映「周 K」口径
    assert "近 1 年" in result.metrics.summary


async def test_v064_analyze_interval_m_aggregates_24_months() -> None:
    """V0.64.0：interval="M" 跨 24 个月聚合，输出 ~24 个点 + MA 在聚合序列上重算。"""
    # 730 个日 K → ~24 个月 K（按日期升序跨 24 个月）
    closes = [round(100 + i * 0.05, 3) for i in range(730)]
    service = _service(_mk_klines(closes))
    result = await service.analyze(days=730, interval="M")

    assert result.interval == "M"
    # 24 月聚合
    assert 20 <= result.metrics.trading_days <= 25
    assert len(result.points) == result.metrics.trading_days
    # M 模式 indicators 旁路
    assert result.indicators == []
    # MA 在聚合后序列上重算：MA5/MA20 满足窗口（24 ≥ 5/20），MA40 不满足窗口 → None
    last = result.points[-1]
    assert last.ma5 is not None
    assert last.ma20 is not None
    assert last.ma40 is None  # 24 个点不够算 MA40
    # 摘要反映「月 K」口径
    assert "近 2 年" in result.metrics.summary


async def test_v064_analyze_interval_invalid_falls_back_to_d() -> None:
    """V0.64.0：非法 interval 自动回退 D 模式（防御性设计）。"""
    closes = [round(1 + i * 0.01, 3) for i in range(60)]
    service = _service(_mk_klines(closes))
    result = await service.analyze(days=60, interval="X")  # type: ignore[arg-type]
    assert result.interval == "D"
    assert len(result.indicators) == 5  # 与日 K 一致


# ───────────────────── V0.71.0：白银 target 适配 ─────────────────────


def test_target_units_contains_silver() -> None:
    """_TARGET_UNITS 包含 silver_etf 与 silver_ny 两个白银 target。"""
    from app.services.trend import _TARGET_UNITS

    assert "silver_etf" in _TARGET_UNITS
    assert "silver_ny" in _TARGET_UNITS
    assert _TARGET_UNITS["silver_etf"] == "元"
    assert _TARGET_UNITS["silver_ny"] == "美元/盎司"


def test_freshness_keys_maps_silver_to_ny_and_etf() -> None:
    """_FRESHNESS_KEYS：silver_ny → ny 时段，silver_etf → etf 时段（V0.71.0）。"""
    from app.services.trend import _FRESHNESS_KEYS

    assert _FRESHNESS_KEYS["silver_ny"] == "ny"
    assert _FRESHNESS_KEYS["silver_etf"] == "etf"


async def test_load_klines_silver_etf_dispatches_to_repo() -> None:
    """TrendService._load_klines(target='silver_etf') 调用 repo.get_silver_etf_history。"""

    class SilverEtfRepo:
        def __init__(self) -> None:
            self.called = False
            self.days = None

        async def get_silver_etf_history(self, days: int = 60):
            self.called = True
            self.days = days
            from datetime import date, timedelta

            from app.repositories.market_data import GoldKline

            return [
                GoldKline(
                    date=date(2026, 6, 1) + timedelta(days=i),
                    open=2.45,
                    close=2.45 + i * 0.01,
                    high=2.5,
                    low=2.4,
                    volume=0.0,
                )
                for i in range(50)
            ]

        async def get_gold_history(self, days: int = 60):
            raise AssertionError("应走 silver 分支")

    repo = SilverEtfRepo()
    svc = TrendService(repo, macro=FakeMacro())
    _klines, symbol, name = await svc._load_klines(days=30, target="silver_etf")
    assert repo.called, "应调用 get_silver_etf_history"
    assert repo.days == 30
    assert symbol == "562800"
    assert name == "白银ETF易方达"
    assert len(_klines) == 50


async def test_load_klines_silver_ny_dispatches_to_repo() -> None:
    """TrendService._load_klines(target='silver_ny') 调用 repo.get_silver_ny_history。"""

    class SilverNyRepo:
        def __init__(self) -> None:
            self.called = False

        async def get_silver_ny_history(self, days: int = 60):
            self.called = True
            from datetime import date, timedelta

            from app.repositories.market_data import GoldKline

            return [
                GoldKline(
                    date=date(2026, 6, 1) + timedelta(days=i),
                    open=31.5,
                    close=31.5 + i * 0.05,
                    high=32.0,
                    low=31.0,
                    volume=0.0,
                )
                for i in range(50)
            ]

        async def get_gold_history(self, days: int = 60):
            raise AssertionError("应走 silver_ny 分支")

    repo = SilverNyRepo()
    svc = TrendService(repo, macro=FakeMacro())
    _klines, symbol, name = await svc._load_klines(days=30, target="silver_ny")
    assert repo.called
    assert symbol == "SI"
    assert name == "纽约白银COMEX"


# ───────────── V0.78.0 Step D：兜底差异化（数据不足不再伪装中性 50）─────────────


def test_dim_min_bars_covers_all_weights() -> None:
    """DIM_MIN_BARS 的键集合必须与 TREND_WEIGHTS 完全一致。

    否则将来新增维度时会漏给门槛 —— 那会让新维度在所有数据长度下都「有效」或
    直接 KeyError，两者都不易在评审时看出来。
    """
    from app.services.trend import DIM_MIN_BARS

    assert set(DIM_MIN_BARS) == set(TREND_WEIGHTS)
    assert all(isinstance(v, int) and v > 1 for v in DIM_MIN_BARS.values())


def test_rsi_returns_none_when_insufficient() -> None:
    """RSI 数据不足返回 None（不再是 50）；**恰好 15 根时不得越界**。

    ⚠ 本用例立项时抓到既有崩溃：守卫原写 ``len(closes) <= period``，而循环最低要读
    ``closes[-(period + 2)]`` ⇒ 传给 15 根时 IndexError 冒泡成 HTTP 500（动能维度本该
    判「数据不足」）。故把 15 这个曾经的崩溃点写成断言。
    """
    from app.services.trend import _rsi

    assert _rsi([100.0] * 14) is None
    assert _rsi([100.0] * 15) is None, "15 根曾触发 IndexError，必须归入数据不足"
    assert isinstance(_rsi([100.0 + i for i in range(16)]), float)


def test_rsi_ignores_latest_bar_is_known_not_accidental() -> None:
    """把 RSI「不看最新一根」的偏差写成断言（既有行为，本版只锁不修）。

    循环 ``range(-period - 1, -1)`` 到 -2 为止、不含 -1 ⇒ 最新一根的涨跌不参与计算，
    RSI 实为「截至前一根」的值。修它会让所有 RSI 值变化并传导到动能分、综合指数、
    决策与历史快照 —— 属口径变更，须先按 ``parameter-evaluation.md`` §6.2 做三维
    （Sharpe / 最大回撤 / 命中率）回测交叉验证。若将来修好，本断言会失败 —— 那是预期
    行为：应同时更新本用例与 ``services/trend.py::_rsi`` 的注释，而不是悄悄改动。
    """
    from app.services.trend import _rsi

    base = [100.0, 101.0] * 8  # 16 根，交替 +1
    spiked = [100.0, 101.0] * 7 + [100.0, 999.0]  # 只把**末根**改成暴涨
    assert _rsi(base) == _rsi(spiked), "末根已被计入 RSI —— 请同步更新本用例与代码注释"


async def test_trend_dim_insufficient_returns_none() -> None:
    """20 根 K 线：结构（需 40）与动量（需 21）数据不足 → score/contribution 均 None。"""
    closes = [round(100 + i * 0.5, 3) for i in range(20)]
    result = await _service(_mk_klines(closes)).analyze(days=20)

    by_name = {i.name: i for i in result.indicators}
    assert len(by_name) == 5
    for name in ("结构", "动量"):
        assert by_name[name].score is None, f"{name} 应因数据不足为 None"
        assert by_name[name].contribution is None
        assert by_name[name].value == "—"
        assert by_name[name].direction == DirectionSignal.NEUTRAL
    for name in ("支撑", "动能", "回撤"):
        assert by_name[name].score is not None, f"{name} 数据足够，应正常出分"
        assert by_name[name].contribution is not None


async def test_trend_dim_reason_populated() -> None:
    """数据不足的维度必须给出原因（含所需交易日数）；有效维度 reason 为 None。"""
    closes = [round(100 + i * 0.5, 3) for i in range(20)]
    result = await _service(_mk_klines(closes)).analyze(days=20)
    by_name = {i.name: i for i in result.indicators}

    assert by_name["结构"].reason is not None and "40" in by_name["结构"].reason
    assert by_name["动量"].reason is not None and "21" in by_name["动量"].reason
    assert by_name["动能"].reason is None
    assert by_name["支撑"].reason is None
    assert by_name["回撤"].reason is None


async def test_trend_combined_re_normalize_when_partial() -> None:
    """部分维度缺失：权重按 Σ有效组权重 归一化，且 Σcontribution == 技术面指数。

    V0.79.0 Step F：组内平均模式 —— dim 的 ``weight`` 现在是「有效合成权重」，
    合计 = 1.0（不是原始 per-dim 配置权重 0.20+0.15+0.15=0.5）；contribution
    = weight × group_score（**不是**了 score × weight），因为同组内 dim 共享
    同一 group_score。``Σcontribution`` 仍恒等于 ``tech_index.score`` 不变式。
    """
    closes = [round(100 + i * 0.5, 3) for i in range(20)]
    result = await _service(_mk_klines(closes)).analyze(days=20)

    valid = [i for i in result.indicators if i.score is not None]
    assert len(valid) == 3  # 支撑 / 动能 / 回撤
    tech_sum = sum(i.contribution for i in valid)
    assert tech_sum == pytest.approx(result.index.components["tech"], abs=0.05)

    # V0.79.0 Step F：有效合成权重归一化为 1.0（不再 = 0.5）
    cfg_sum = sum(i.weight for i in valid)
    assert cfg_sum == pytest.approx(1.0, abs=1e-9)
    # 仍然验证 Σcontribution 不变式（per-dim contribution 不再 = score × weight，
    # 因为同组 dim 共享同一 group_score —— 这是组内平均的本质）


async def test_combined_summary_notes_excluded_dims() -> None:
    """综合指数文案须说明「哪几维数据不足、已归一化」——客户不能把它当常态口径。"""
    closes = [round(100 + i * 0.5, 3) for i in range(20)]
    result = await _service(_mk_klines(closes)).analyze(days=20)

    summary = result.index.summary
    assert "结构" in summary and "动量" in summary
    assert "归一化" in summary


async def test_trend_combined_none_when_all_insufficient() -> None:
    """9 根 K 线：5 维全不足 → 技术面指数 None；综合指数剔除技术面并按剩余面归一化。

    为什么是 9 根而不是 10 根：回撤维度的门槛恰为 10（``< 10`` 才判不足），
    10 根时它仍然有效、技术面不会整面缺失。
    """
    closes = [round(100 + i * 0.5, 3) for i in range(9)]
    svc = _service(_mk_klines(closes), macro_score=80.0)
    result = await svc.analyze(days=9)

    assert all(i.score is None for i in result.indicators)
    assert all(i.contribution is None for i in result.indicators)
    # 关键：不给技术面塞一个中性 50 占位，而是整面消失
    assert "tech" not in result.index.components
    assert set(result.index.components) == {"macro", "news"}
    # 归一化：(80×0.4 + 50×0.3) / (0.4+0.3) = 67.14 → 不再被 50×0.3 稀释成 62.0
    assert result.index.score == pytest.approx((80.0 * 0.4 + 50.0 * 0.3) / 0.7, abs=0.05)
    assert "技术面" in result.index.summary and "归一化" in result.index.summary


async def test_trend_combined_keeps_tech_when_all_dims_valid() -> None:
    """60 根 K 线：5 维全有效 → 综合指数仍按 技术×30% + 宏观×40% + 消息×30%（回归保护）。"""
    closes = [round(1 + i * 0.01, 3) for i in range(60)]
    result = await _service(_mk_klines(closes)).analyze(days=60)

    assert set(result.index.components) == {"tech", "macro", "news"}
    assert result.index.score == pytest.approx(
        result.index.components["tech"] * 0.3 + 50.0 * 0.4 + 50.0 * 0.3, abs=0.15
    )
    assert all(i.score is not None and i.reason is None for i in result.indicators)
    assert "归一化" not in result.index.summary, "全维度有效时不应出现任何归一化说明"


async def test_w_and_m_interval_discloses_neutral_tech_in_summary() -> None:
    """W/M 模式技术面旁路仍按中性 50 计，但**必须在对外文案里披露**。

    ⚠ 立项动机（本版发现的既有缺陷）：原先那句「已按中性 50 处理」写在
    ``tech_index.summary`` 里，而该对象只被读取 ``.score``、summary 从不进入响应
    ⇒ **从未对外披露**，52W/24M 视图上的中性 50 其实是沉默的假中性。故本用例断言的
    是**响应里可见的那句话**，不是内部对象的字段。

    保留 50（而非改成 None）的理由：①「口径不适用」与「数据不足」不是同一类问题；
    ② 整面剔除会让 52W/24M 的指数相对 60D 出现结构性（非市场）落差，破坏跨周期可比性。
    """
    closes = [round(100 + i * 0.5, 3) for i in range(14)]
    result = await _service(_mk_klines(closes)).analyze(days=14, interval="W")

    assert result.indicators == []
    assert result.index.components.get("tech") == 50.0
    assert "不适用" in result.index.summary, "W/M 的技术面旁路必须在对外 summary 中说明"
    assert "50" in result.index.summary


# =========================================================================
# V0.79.0 Step F · 组内平均（combine_by_group + TrendIndexOut.composed_by）
# =========================================================================


def test_group_weights_sum_to_one() -> None:
    """Step F：3 组权重合计 1.0（与旧 TREND_WEIGHTS 维度权重同合计）。"""
    assert sum(GROUP_WEIGHTS.values()) == pytest.approx(1.0, abs=1e-9)
    assert set(GROUP_WEIGHTS) == {"trend", "overbought", "risk"}


def test_group_mapping_covers_all_5_dims() -> None:
    """Step F：GROUP_MAPPING 必须覆盖 TREND_WEIGHTS 全部 5 个维度。"""
    assert set(GROUP_MAPPING) == set(TREND_WEIGHTS)
    # 每组至少 1 个维度（不允许出现空组）
    for g in GROUP_WEIGHTS:
        dims_in = [n for n, mapped in GROUP_MAPPING.items() if mapped == g]
        assert len(dims_in) >= 1, f"空组 {g!r}"


def test_combine_by_group_full_valid() -> None:
    """5 维度都给分：组内平均后加权合成。

    给分：结构 60、动量 70 → 趋势组 65.0
         支撑 50、动能 50 → 超买组 50.0
         回撤 80 → 风险组 80.0
    预期 tech_index = 65×0.50 + 50×0.30 + 80×0.20 = 32.5 + 15 + 16 = 63.5
    """
    group_scores, weights_norm = TrendService.combine_by_group(
        {"结构": 60.0, "动量": 70.0, "支撑": 50.0, "动能": 50.0, "回撤": 80.0}
    )
    assert group_scores == {"trend": 65.0, "overbought": 50.0, "risk": 80.0}
    assert weights_norm == {"trend": 0.5, "overbought": 0.3, "risk": 0.2}


def test_combine_by_group_one_dim_missing_in_2dim_group() -> None:
    """2 维组中 1 个缺失：组内只剩 1 个，不强制 50 兜底。"""
    # 支撑缺失 → 超买组 = (动能)/1 = 单 dim；trend/risk 完整
    group_scores, weights_norm = TrendService.combine_by_group(
        {"结构": 60.0, "动量": 70.0, "支撑": None, "动能": 50.0, "回撤": 80.0}
    )
    assert group_scores["trend"] == 65.0
    assert group_scores["overbought"] == 50.0  # 只有动能
    assert group_scores["risk"] == 80.0
    # 3 组都有效 → 权重不重分配（仍 = GROUP_WEIGHTS）
    assert weights_norm == {"trend": 0.5, "overbought": 0.3, "risk": 0.2}


def test_combine_by_group_whole_group_missing() -> None:
    """整组（趋势组 2 维都 None）：该组从 weights_norm 中剔除，剩余组权重按 Σ(原权重) 归一化。"""
    # 趋势组 2 个维度都 None → 该组 score=None
    # 超买(0.30) + 风险(0.20) 有效 → valid_w_sum = 0.50
    # weights_norm: 超买 = 0.30/0.50 = 0.6, 风险 = 0.20/0.50 = 0.4
    group_scores, weights_norm = TrendService.combine_by_group(
        {"结构": None, "动量": None, "支撑": 50.0, "动能": 50.0, "回撤": 80.0}
    )
    assert group_scores["trend"] is None
    assert group_scores["overbought"] == 50.0
    assert group_scores["risk"] == 80.0
    assert weights_norm == {"overbought": 0.6, "risk": 0.4}
    assert "trend" not in weights_norm


def test_combine_by_group_all_missing() -> None:
    """5 维度都 None：tech_index = None（不引入 50 兜底）。"""
    group_scores, weights_norm = TrendService.combine_by_group(
        {"结构": None, "动量": None, "支撑": None, "动能": None, "回撤": None}
    )
    assert all(s is None for s in group_scores.values())
    assert weights_norm == {}


async def test_build_index_grouped_sets_composed_by() -> None:
    """Step F：_build_index 走组内平均分支时，GoldTrendOut.tech_composed_by = "grouped"。

    V0.79.0 Step F：composed_by 只对技术面有意义（不是综合指数的属性），
    故放在 GoldTrendOut.tech_composed_by 顶层。
    """
    closes = [round(100 + i * 0.5, 3) for i in range(60)]
    service = _service(_mk_klines(closes))
    result = await service.analyze(days=60)

    assert result.tech_composed_by == "grouped"
    # 全维度有效时，组内平均分数在 0-100
    assert 0 <= result.index.components["tech"] <= 100


def test_build_index_weighted_path_sets_composed_by_weighted() -> None:
    """Step F：group_combine=False 时显式走旧路径，tech_composed_by = "weighted"。"""
    closes = [round(100 + i * 0.5, 3) for i in range(60)]
    service = _service(_mk_klines(closes))
    # 直接调 _build_index 并传 weights_meta={"group_combine": False}
    indicators, tech_index = service._build_index(
        closes=closes,
        highs=closes,
        ma20=moving_average(closes, 20),
        ma40=moving_average(closes, 40),
        weights=None,
        unit="元",
        weights_meta={"group_combine": False},
    )
    assert tech_index.composed_by == "weighted"
    assert 0 <= tech_index.score <= 100
    # 旧路径：Σ(weight) = 1.0（全维度有效）
    assert sum(i.weight for i in indicators) == pytest.approx(1.0, abs=1e-9)


async def test_build_index_grouped_sum_contribution_equals_tech_index() -> None:
    """Step F：组内平均路径下 Σ(contribution) 仍 == tech_index.score（不变式）。

    tech_index.score 在 GoldTrendOut 里以 ``index.components["tech"]`` 暴露
    （trend.py:521 components 字典），Σ(contribution) 应该等于它。
    """
    closes = [round(100 + i * 0.5, 3) for i in range(60)]
    service = _service(_mk_klines(closes))
    result = await service.analyze(days=60)

    valid = [i for i in result.indicators if i.score is not None]
    assert len(valid) == 5
    tech_sum = sum(i.contribution for i in valid)
    assert tech_sum == pytest.approx(result.index.components["tech"], abs=0.05)
    # 有效合成权重 Σ = 1.0（与单维度加权路径一致）
    assert sum(i.weight for i in valid) == pytest.approx(1.0, abs=1e-9)


# ───────────────────── Step F Commit 2 · settings 集成 ─────────────────────


class FakeWeightService:
    """假 WeightService：仅暴露本测试所需的 trend_weights / combine_weights / group_combine。

    其余 WeightService 方法在本测试中不被调用，无需实现。
    """

    def __init__(self, *, group_combine: bool = True) -> None:
        self._gc = group_combine

    async def trend_weights(self) -> dict[str, float]:
        return dict(TREND_WEIGHTS)

    async def combine_weights(self) -> tuple[float, float, float]:
        return (0.30, 0.40, 0.30)

    async def group_combine(self) -> bool:
        return self._gc


async def test_settings_group_combine_true_routes_to_grouped_path() -> None:
    """Step F Commit 2：settings.group_combine=True → _build_index 走组内平均分支。"""
    closes = [round(100 + i * 0.5, 3) for i in range(60)]
    service = TrendService(
        FakeRepo(_mk_klines(closes)),
        macro=FakeMacro(),
        settings=FakeWeightService(group_combine=True),
    )
    result = await service.analyze(days=60)
    assert result.tech_composed_by == "grouped"


async def test_settings_group_combine_false_routes_to_weighted_path() -> None:
    """Step F Commit 2：settings.group_combine=False → _build_index 走单维度加权分支。

    这是 Step F 的回滚通道：把配置改为 group_combine=false 立即恢复历史行为，
    不需要改代码或重启（除权重缓存 TTL 60s 外）。
    """
    closes = [round(100 + i * 0.5, 3) for i in range(60)]
    service = TrendService(
        FakeRepo(_mk_klines(closes)),
        macro=FakeMacro(),
        settings=FakeWeightService(group_combine=False),
    )
    result = await service.analyze(days=60)
    assert result.tech_composed_by == "weighted"


async def test_settings_none_falls_back_to_grouped_default() -> None:
    """Step F Commit 2：未注入 settings（_settings is None）→ 默认走组内平均分支。

    与 WeightConfig 默认 True 保持一致，避免「settings 默认 True + fallback 默认 False」
    出现行为分歧。
    """
    closes = [round(100 + i * 0.5, 3) for i in range(60)]
    # 不传 settings（None）→ 走 fallback 路径
    service = TrendService(
        FakeRepo(_mk_klines(closes)),
        macro=FakeMacro(),
        settings=None,
    )
    result = await service.analyze(days=60)
    assert result.tech_composed_by == "grouped"
