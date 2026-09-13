"""每日快照 API 测试。"""

from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from app.dependencies import get_market_data_repository, get_trend_service
from app.repositories.market_data import GoldKline
from app.schemas.common import DirectionSignal
from app.schemas.market import MacroIndexOut
from app.services.trend import TrendService


class FakeMarketRepo:
    async def get_gold_quote(self, symbol: str = "XAU"):
        return type("Q", (), {"symbol": symbol, "price_usd": 5.5, "change_pct": 1.2, "updated_at": date.today()})()

    async def get_gold_history(self, days: int = 60) -> list[GoldKline]:
        base = date(2026, 6, 1)
        return [
            GoldKline(date=base + timedelta(days=i), open=5.0, close=round(5.0 + i * 0.02, 3), high=5.1, low=4.9, volume=1000.0)
            for i in range(days)
        ]

    async def get_gold_gram_history(self, days: int = 60) -> list[GoldKline]:
        base = date(2026, 6, 1)
        return [
            GoldKline(date=base + timedelta(days=i), open=990.0, close=round(990.0 + i * 1.5, 2), high=992.0, low=988.0, volume=0.0)
            for i in range(days)
        ]

    async def get_us_gold_history(self, days: int = 60) -> list[GoldKline]:
        base = date(2026, 6, 1)
        return [
            GoldKline(date=base + timedelta(days=i), open=4400.0, close=round(4400.0 + i * 3.0, 2), high=4410.0, low=4390.0, volume=0.0)
            for i in range(days)
        ]


class FakeMacro:
    async def evaluate(self) -> MacroIndexOut:
        return MacroIndexOut(score=50.0, direction=DirectionSignal.NEUTRAL, factors=[], summary="测试")


@pytest.fixture(autouse=True)
def _override_deps():
    from app.main import app

    app.dependency_overrides[get_market_data_repository] = lambda: FakeMarketRepo()
    app.dependency_overrides[get_trend_service] = lambda: TrendService(FakeMarketRepo(), macro=FakeMacro())
    yield
    app.dependency_overrides.clear()


async def test_capture_snapshot(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/snapshots/capture")
    assert resp.status_code == 200
    body = resp.json()

    assert body["symbol"] == "GC"
    assert body["trend_index"] > 0
    assert body["index_level"] in {"strong_up", "up", "sideways", "down", "strong_down"}
    assert body["close"] > 0


async def test_list_snapshots(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/snapshots?days=10")
    assert resp.status_code == 200
    body = resp.json()

    assert body["total"] >= 1
    snap = body["snapshots"][0]
    assert snap["snapshot_date"] == date.today().isoformat()
    assert snap["tech_index"] > 0


async def test_v063_list_snapshots_days_one(client: AsyncClient) -> None:
    """V0.63.0：days=1 边界 —— 应当返回 1 条且为当日。"""
    resp = await client.get("/api/v1/snapshots?days=1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["snapshots"][0]["snapshot_date"] == date.today().isoformat()


async def test_v063_list_snapshots_days_max(client: AsyncClient) -> None:
    """V0.63.0：days=365 上限 —— 应当 200 且 total 与 days 兼容（≤ days，惰性补当日仍只有 1 条）。"""
    resp = await client.get("/api/v1/snapshots?days=365")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] <= 365
    assert body["total"] >= 1  # 惰性补当日至少 1 条


async def test_v063_snapshot_includes_news_index(client: AsyncClient) -> None:
    """V0.63.0：响应 schema 包含 news_index 字段（消息面曲线的数据来源）。"""
    resp = await client.get("/api/v1/snapshots?days=1")
    assert resp.status_code == 200
    snap = resp.json()["snapshots"][0]
    assert "news_index" in snap
    assert isinstance(snap["news_index"], (int, float))
    # 未打分的 fallback 是 50.0（中性）
    assert 0 <= snap["news_index"] <= 100


async def test_v063_days_query_validation(client: AsyncClient) -> None:
    """V0.63.0：days 越界（0 / 366）应返回 422 校验错误。"""
    for bad in ("0", "366", "-1"):
        resp = await client.get(f"/api/v1/snapshots?days={bad}")
        assert resp.status_code == 422, f"days={bad} 应被拒：{resp.status_code}"
