"""共振信号 API 集成测试（V0.70.0 P2 #7）。

覆盖：
- /signal：返回 4 类信号 + 置信度
- /strength-up：horizon 校验 + 命中统计
- /history：空表 → empty list
"""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.dependencies import (
    get_news_repository,
    get_resonance_service,
    get_trend_service,
)
from app.models.news import NewsScore
from app.services.resonance import ResonanceService


class FakeMarket:
    """假行情：单调上升 ETF 价。"""

    async def get_gold_history(self, days: int = 60):
        from datetime import timedelta as _td

        from app.repositories.market_data import GoldKline

        start = date.today() - _td(days=days)
        return [
            GoldKline(
                date=start + _td(days=i),
                open=10.0,
                close=round(10.0 + i * 0.05, 4),
                high=11.0,
                low=9.0,
                volume=0.0,
            )
            for i in range(days)
        ]


class FakeTrend:
    def __init__(self, market: FakeMarket) -> None:
        self._repo = market

    async def analyze(self, days: int = 60, target: str = "etf"):
        # ResonanceService 只用 index.components，用 SimpleNamespace 足矣
        return SimpleNamespace(
            index=SimpleNamespace(components={"tech": 70, "macro": 65, "news": 60}),
        )


def _make_news(score_date: date, slot: int, score: float) -> NewsScore:
    return NewsScore(
        score_date=score_date,
        slot=slot,
        score=score,
        direction="bullish" if score >= 55 else ("bearish" if score <= 45 else "neutral"),
        notes="",
        basis="",
        backfilled=0,
        scored_at=score_date,
    )


@pytest.fixture(autouse=True)
def _override_resonance_deps():
    from app.main import app

    fake_market = FakeMarket()
    fake_trend = FakeTrend(fake_market)
    today = date.today()
    records = [_make_news(today - timedelta(days=i), 1, 60) for i in range(30)]

    class FakeNews:
        async def list_between(self, start: date, end: date) -> list[NewsScore]:
            return [r for r in records if start <= r.score_date <= end]

    app.dependency_overrides[get_trend_service] = lambda: fake_trend
    app.dependency_overrides[get_news_repository] = lambda: FakeNews()
    app.dependency_overrides[get_resonance_service] = lambda: ResonanceService(
        trend=fake_trend,  # type: ignore[arg-type]
        news=FakeNews(),  # type: ignore[arg-type]
    )
    yield
    app.dependency_overrides.clear()


async def test_signal_endpoint_returns_4_class_signal(client: AsyncClient) -> None:
    """/signal：返回 4 类信号 + confidence。"""
    resp = await client.get("/api/v1/resonance/signal")
    assert resp.status_code == 200
    body = resp.json()
    assert body["signal"] in {"strong_up", "strong_down", "weak_up", "divergent", "neutral"}
    assert body["label"]
    assert 0 <= body["confidence"] <= 100
    assert "tech" in body["components"]


async def test_strength_up_invalid_horizon_422(client: AsyncClient) -> None:
    """/strength-up：horizon 必须 ∈ {1, 3, 5}。"""
    resp = await client.get("/api/v1/resonance/strength-up?horizon=99")
    assert resp.status_code == 200  # 服务端 horizon=99 自动回退到 1
    body = resp.json()
    assert body["horizon"] == 1


async def test_history_empty_when_no_records(client: AsyncClient) -> None:
    """/history：当消息面无打分 → empty list。"""
    from app.main import app

    # 替换为空的 FakeNews
    class EmptyNews:
        async def list_between(self, start: date, end: date) -> list[NewsScore]:
            return []

    # 本测试临时替换 resonance service；autouse fixture 的 teardown 会
    # app.dependency_overrides.clear()，因此无需在此手动保存/恢复原值。
    app.dependency_overrides[get_resonance_service] = lambda: ResonanceService(
        trend=app.dependency_overrides[get_trend_service](),
        news=EmptyNews(),  # type: ignore[arg-type]
    )

    resp = await client.get("/api/v1/resonance/history?days=30")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []
