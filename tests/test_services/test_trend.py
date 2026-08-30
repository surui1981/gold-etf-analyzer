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
