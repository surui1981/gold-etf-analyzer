"""趋势分析服务单元测试：均线、方向判定与追踪指数。"""

from datetime import date, timedelta

import pytest

from app.repositories.market_data import GoldKline
from app.schemas.common import DirectionSignal
from app.schemas.market import MacroIndexOut, TrendDirection, TrendIndexLevel
from app.services.trend import TREND_WEIGHTS, TrendService, moving_average


class FakeMacro:
    """假宏观服务：固定中性 50 分，避免测试依赖网络。"""

    async def evaluate(self) -> MacroIndexOut:
        return MacroIndexOut(
            score=50.0,
            direction=DirectionSignal.NEUTRAL,
            factors=[],
            summary="测试宏观",
        )


def _service(klines: list[GoldKline]) -> TrendService:
    return TrendService(FakeRepo(klines), macro=FakeMacro())


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
