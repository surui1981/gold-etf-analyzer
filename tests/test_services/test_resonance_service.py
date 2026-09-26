"""共振信号服务单元测试（V0.70.0 P2 #7）。

覆盖：
- 4 类信号判定（strong_up / strong_down / weak_up / divergent / neutral）
- strength_up 命中统计（含样本不足警告）
- history 按日期倒序返回
"""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news import NewsScore
from app.services.resonance import ResonanceService, compute_resonance

# =========================================================================
# 纯函数 compute_resonance —— 4 类信号判定
# =========================================================================


def test_compute_strong_up_all_three_bullish() -> None:
    """三面同向看多（≥55）→ STRONG_UP。"""
    out = compute_resonance({"tech": 60, "macro": 62, "news": 58})
    assert out.signal == "strong_up"
    assert out.label == "强共振看多"
    assert 55 <= out.confidence <= 100
    assert out.components == {"tech": 60, "macro": 62, "news": 58}


def test_compute_strong_down_mirror() -> None:
    """三面同向看空（≤45）→ STRONG_DOWN。"""
    out = compute_resonance({"tech": 40, "macro": 38, "news": 42})
    assert out.signal == "strong_down"
    assert out.label == "强共振看空"


def test_compute_weak_up_two_of_three() -> None:
    """三面中 2 维看多 → WEAK_UP（confidence=65）。"""
    out = compute_resonance({"tech": 60, "macro": 48, "news": 58})
    assert out.signal == "weak_up"
    assert out.confidence == 65.0


def test_compute_divergent_mix() -> None:
    """tech 与 macro 反向（≥55 vs ≤45）→ DIVERGENT。"""
    out = compute_resonance({"tech": 65, "macro": 40, "news": 50})
    assert out.signal == "divergent"
    # confidence = (65 - 40) × 0.5 = 12.5
    assert out.confidence == pytest.approx(12.5, abs=0.1)


def test_compute_neutral_all_near_50() -> None:
    """三面都中性 → NEUTRAL（confidence=50）。"""
    out = compute_resonance({"tech": 50, "macro": 50, "news": 50})
    assert out.signal == "neutral"
    assert out.confidence == 50.0


def test_compute_score_date_propagates() -> None:
    """score_date 入参会出现在结果中。"""
    d = date(2026, 6, 1)
    out = compute_resonance({"tech": 60, "macro": 60, "news": 60}, score_date=d)
    assert out.score_date == d


def test_compute_default_dim_50_when_missing() -> None:
    """缺维度时按中性 50 兜底。"""
    out = compute_resonance({"tech": 60})  # macro / news 缺失
    # tech=60, macro=50, news=50 → tech 看多，宏观/消息中性 → 仅 1 维看多 → 中性或弱多
    assert out.signal in {"neutral", "weak_up"}


# =========================================================================
# ResonanceService —— 命中统计与历史回放
# =========================================================================


class FakeMarket:
    """假行情：返回单调上升 ETF 价格序列（用于构造「命中」样本）。"""

    def __init__(self, base_close: float = 10.0, daily_delta: float = 0.05) -> None:
        self.base_close = base_close
        self.daily_delta = daily_delta

    async def get_gold_history(self, days: int = 60):
        from datetime import timedelta

        from app.repositories.market_data import GoldKline

        start = date.today() - timedelta(days=days)
        return [
            GoldKline(
                date=start + timedelta(days=i),
                open=self.base_close,
                close=round(self.base_close + i * self.daily_delta, 4),
                high=self.base_close + 1,
                low=self.base_close - 1,
                volume=0.0,
            )
            for i in range(days)
        ]


class FakeNewsRepo:
    """假消息面仓储：内存中维护 NewsScore 列表，按日期查。"""

    def __init__(self, records: list[NewsScore]) -> None:
        self._records = records

    async def list_between(self, start: date, end: date) -> list[NewsScore]:
        return [r for r in self._records if start <= r.score_date <= end]


def _make_news(score_date: date, slot: int, score: float, notes: str = "") -> NewsScore:
    return NewsScore(
        score_date=score_date,
        slot=slot,
        score=score,
        direction="bullish" if score >= 55 else ("bearish" if score <= 45 else "neutral"),
        notes=notes,
        basis="",
        backfilled=0,
        scored_at=score_date,
    )


async def test_history_replays_trend_per_day(db_session: AsyncSession) -> None:
    """history(days)：5 个打分日 → 5 项按日期倒序。"""
    today = date.today()
    records = [_make_news(today - timedelta(days=i), 1, 60 + i) for i in range(5)]
    fake_news = FakeNewsRepo(records)
    service = ResonanceService.__new__(ResonanceService)  # 不调 __init__
    service._trend = None
    service._news = fake_news  # type: ignore[assignment]

    out = await service.history(days=10)
    assert out.total == 5
    # 按日期倒序
    dates = [it.score_date for it in out.items]
    assert dates == sorted(dates, reverse=True)
    # 每项至少含 score_date
    for it in out.items:
        assert it.score_date is not None


async def test_strength_up_filters_bullish_news_only() -> None:
    """strength_up：仅当 effective_score ≥ 55 且 BULLISH 才计入。"""
    today = date.today()
    # 30 天 BULLISH（score=60）—— 在单调上升价序列里全部命中
    bull = [_make_news(today - timedelta(days=i), 1, 60) for i in range(30)]
    fake_news = FakeNewsRepo(bull)
    service = ResonanceService.__new__(ResonanceService)
    service._news = fake_news  # type: ignore[assignment]

    fake_trend = SimpleNamespace(_repo=FakeMarket())
    service._trend = fake_trend  # type: ignore[assignment]

    out = await service.strength_up(days=30, horizon=1)
    # 30 天全部 BULLISH → total_strong_up=30；
    # 但 T+1 对今天/昨天尚未到期 → resolved=28（最近 2 天 pending）
    assert out.total_strong_up == 30
    assert out.resolved == 28
    assert out.hits == 28
    assert out.hit_rate == 100.0
    assert out.sample_warning is False


async def test_strength_up_sample_warning_below_threshold() -> None:
    """样本 < 20 → sample_warning=True。"""
    today = date.today()
    bull = [_make_news(today - timedelta(days=i), 1, 60) for i in range(15)]
    fake_news = FakeNewsRepo(bull)
    service = ResonanceService.__new__(ResonanceService)
    service._news = fake_news  # type: ignore[assignment]
    service._trend = SimpleNamespace(_repo=FakeMarket())  # type: ignore[assignment]

    out = await service.strength_up(days=15, horizon=1)
    assert out.sample_warning is True
    assert "仅供参考" in out.note


async def test_strength_up_empty_window_returns_warning() -> None:
    """窗口无记录 → total=0 + warning。"""
    fake_news = FakeNewsRepo([])
    service = ResonanceService.__new__(ResonanceService)
    service._news = fake_news  # type: ignore[assignment]
    service._trend = SimpleNamespace(_repo=FakeMarket())  # type: ignore[assignment]

    out = await service.strength_up(days=30, horizon=1)
    assert out.total_strong_up == 0
    assert out.resolved == 0
    assert out.hit_rate is None
    assert out.sample_warning is True
    assert "无消息面打分记录" in out.note
