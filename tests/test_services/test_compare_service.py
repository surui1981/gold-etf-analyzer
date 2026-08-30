"""对照服务单元测试：日期对齐、归一化与领先判定。"""

from datetime import date, timedelta

import pytest

from app.repositories.market_data import GoldKline
from app.services.compare import GoldCompareService


class FakeRepo:
    """假行情仓储：注入 ETF 与克价序列。"""

    def __init__(self, etf: list[GoldKline], gram: list[GoldKline]) -> None:
        self._etf = etf
        self._gram = gram

    async def get_gold_history(self, days: int = 60) -> list[GoldKline]:
        return self._etf

    async def get_gold_gram_history(self, days: int = 60) -> list[GoldKline]:
        return self._gram


def _kline(base: float, step: float, n: int, start: date) -> list[GoldKline]:
    return [
        GoldKline(
            date=start + timedelta(days=i),
            open=c,
            close=c,
            high=c,
            low=c,
            volume=0.0,
        )
        for i, c in enumerate(base + step * i for i in range(n))
    ]


async def test_compare_alignment_and_leader() -> None:
    """公共日期对齐 + 归一化起点 100 + ETF 领先判定 + 完整指标。"""
    dates_start = date(2026, 7, 1)
    etf = _kline(9.0, 0.05, 60, dates_start)  # 9.0 → 11.95，+32.8%
    gram = _kline(990.0, 1.0, 60, dates_start)  # 990 → 1049，+5.96%
    service = GoldCompareService(FakeRepo(etf, gram))
    out = await service.compare(days=60)

    assert out.days == 60
    assert len(out.points) == 60
    assert out.points[0].etf == 100.0
    assert out.points[0].gram == 100.0
    assert out.leader == "etf"
    assert out.etf.change_pct == pytest.approx(32.78, abs=0.1)
    assert out.gram.change_pct == pytest.approx(5.96, abs=0.1)
    assert out.lead_gap == pytest.approx(26.82, abs=0.2)
    assert "领先" in out.summary
    # 完整指标
    assert out.etf.high == pytest.approx(11.95, abs=0.01)
    assert out.etf.low == pytest.approx(9.0, abs=0.01)
    assert out.etf.ma20 == pytest.approx(11.475, abs=0.01)
    assert out.etf.ma40 == pytest.approx(10.975, abs=0.01)
    assert out.etf.direction.value == "up"
    assert out.gram.direction.value == "up"


async def test_compare_gram_leader() -> None:
    """克价涨幅更大 → gram 领先。"""
    dates_start = date(2026, 7, 1)
    etf = _kline(9.0, 0.01, 10, dates_start)  # +1.0%
    gram = _kline(990.0, 2.0, 10, dates_start)  # +1.8%
    service = GoldCompareService(FakeRepo(etf, gram))
    out = await service.compare(days=10)

    assert out.leader == "gram"


async def test_compare_partial_overlap() -> None:
    """部分日期重叠时按交集对齐。"""
    start = date(2026, 7, 1)
    etf = _kline(9.0, 0.05, 10, start)
    # 克价从第 3 天开始（少 2 天）
    gram = _kline(990.0, 1.0, 8, start + timedelta(days=2))
    service = GoldCompareService(FakeRepo(etf, gram))
    out = await service.compare(days=10)

    assert out.days == 8
    assert len(out.points) == 8


async def test_compare_insufficient_overlap() -> None:
    """无重叠 → ValueError。"""
    etf = _kline(9.0, 0.05, 5, date(2026, 7, 1))
    gram = _kline(990.0, 1.0, 5, date(2026, 8, 1))  # 日期完全不重叠
    service = GoldCompareService(FakeRepo(etf, gram))
    with pytest.raises(ValueError):
        await service.compare(days=5)
