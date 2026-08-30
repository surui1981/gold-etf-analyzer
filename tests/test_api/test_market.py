"""行情 API 测试：报价 + 趋势追踪（注入假数据源）。"""

from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from app.dependencies import get_market_data_repository
from app.repositories.market_data import GoldKline


class FakeMarketRepo:
    """内存假行情仓储：避免测试依赖网络。"""

    async def get_gold_quote(self, symbol: str = "XAU"):
        return type("Q", (), {"symbol": symbol, "price_usd": 5.5, "change_pct": 1.2, "updated_at": date.today()})()

    async def get_gold_history(self, days: int = 60) -> list[GoldKline]:
        base = date(2026, 6, 1)
        return [
            GoldKline(
                date=base + timedelta(days=i),
                open=5.0,
                close=round(5.0 + i * 0.02, 3),
                high=5.1,
                low=4.9,
                volume=1000.0,
            )
            for i in range(days)
        ]

    async def get_gold_gram_history(self, days: int = 60) -> list[GoldKline]:
        """克价序列：涨幅略低于 ETF，用于对照。"""
        base = date(2026, 6, 1)
        return [
            GoldKline(
                date=base + timedelta(days=i),
                open=990.0,
                close=round(990.0 + i * 1.5, 2),
                high=992.0,
                low=988.0,
                volume=0.0,
            )
            for i in range(days)
        ]

    async def get_us_gold_history(self, days: int = 60) -> list[GoldKline]:
        """纽约金序列（美元/盎司）。"""
        base = date(2026, 6, 1)
        return [
            GoldKline(
                date=base + timedelta(days=i),
                open=4400.0,
                close=round(4400.0 + i * 3.0, 2),
                high=4410.0,
                low=4390.0,
                volume=0.0,
            )
            for i in range(days)
        ]


@pytest.fixture(autouse=True)
def _override_market_repo():
    """所有行情用例注入假数据源。"""
    from app.main import app

    app.dependency_overrides[get_market_data_repository] = lambda: FakeMarketRepo()
    yield
    app.dependency_overrides.clear()


async def test_gold_quote(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/market/gold")
    assert resp.status_code == 200
    body = resp.json()
    assert body["price_usd"] > 0
    assert "updated_at" in body


async def test_gold_trend(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/market/gold/trend?days=60")
    assert resp.status_code == 200
    body = resp.json()

    assert body["symbol"] == "518880"
    assert len(body["points"]) == 60
    assert body["metrics"]["trading_days"] == 60
    assert body["metrics"]["direction"] in {"up", "down", "sideways"}
    # 上升序列 → change_pct > 0
    assert body["metrics"]["change_pct"] > 0
    assert body["metrics"]["ma20"] is not None
    # 趋势参数与追踪指数
    assert len(body["indicators"]) == 5
    assert 0 <= body["index"]["score"] <= 100
    assert body["index"]["level"] in {"strong_up", "up", "sideways", "down", "strong_down"}


async def test_gold_trend_days_validation(client: AsyncClient) -> None:
    """days 超出范围应 422。"""
    resp = await client.get("/api/v1/market/gold/trend?days=10")
    assert resp.status_code == 422


async def test_gold_compare(client: AsyncClient) -> None:
    """ETF vs 克价对照。"""
    resp = await client.get("/api/v1/market/gold/compare?days=60")
    assert resp.status_code == 200
    body = resp.json()

    assert body["days"] == 60
    assert body["etf"]["change_pct"] > 0  # 上升序列
    assert body["gram"]["change_pct"] > 0
    assert body["leader"] in {"etf", "gram", "tie"}
    assert len(body["points"]) == 60
    assert body["points"][0]["etf"] == 100.0
    assert body["points"][0]["gram"] == 100.0
    assert "对照" in body["summary"]


async def test_ny_gold_trend(client: AsyncClient) -> None:
    """纽约金 60 天趋势曲线。"""
    resp = await client.get("/api/v1/market/gold/ny-trend?days=60")
    assert resp.status_code == 200
    body = resp.json()

    assert body["symbol"] == "GC"
    assert "纽约金" in body["name"]
    assert len(body["points"]) == 60
    assert body["metrics"]["change_pct"] > 0
    assert body["metrics"]["end_price"] > 4000  # 美元/盎司量级
