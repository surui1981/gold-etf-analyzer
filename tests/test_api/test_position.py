"""交易面与决策 API 集成测试（注入假行情源）。"""

from datetime import date

import pytest
from httpx import AsyncClient

from app.dependencies import get_market_data_repository


class FakeMarket:
    """假行情：固定最新价 10.0，历史序列上升。"""

    async def get_gold_quote(self, symbol: str = "XAU"):
        return type("Q", (), {"symbol": symbol, "price_usd": 10.0, "change_pct": 0.5, "updated_at": date.today()})()

    async def get_gold_history(self, days: int = 60):
        from datetime import timedelta

        from app.repositories.market_data import GoldKline

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


@pytest.fixture(autouse=True)
def _override_market_repo():
    from app.main import app

    app.dependency_overrides[get_market_data_repository] = lambda: FakeMarket()
    yield
    app.dependency_overrides.clear()


async def test_position_lifecycle(client: AsyncClient) -> None:
    # 开仓
    resp = await client.post(
        "/api/v1/positions",
        json={"symbol": "518880", "quantity": 100, "price": 9.0, "fee": 1.0},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["quantity"] == 100
    assert body["avg_cost"] == 9.0
    assert body["market_price"] == 10.0
    assert body["pnl"] == 100.0
    pid = body["id"]

    # 加仓 → 均价 9.5
    resp = await client.post(
        f"/api/v1/positions/{pid}/trades",
        json={"side": "buy", "quantity": 100, "price": 10.0},
    )
    assert resp.status_code == 200
    assert resp.json()["avg_cost"] == 9.5

    # 持仓列表
    resp = await client.get("/api/v1/positions")
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    # 超减 → 400
    resp = await client.post(
        f"/api/v1/positions/{pid}/trades",
        json={"side": "sell", "quantity": 999, "price": 10.0},
    )
    assert resp.status_code == 400

    # 清仓
    resp = await client.post(f"/api/v1/positions/{pid}/close")
    assert resp.status_code == 200
    assert resp.json()["status"] == "closed"


async def test_decision_etf(client: AsyncClient) -> None:
    """空仓 + 强趋势（假数据上升序列）→ 买入建议。"""
    resp = await client.get("/api/v1/decision/etf")
    assert resp.status_code == 200
    body = resp.json()
    assert body["action"] in {"BUY", "ADD", "HOLD", "REDUCE", "SELL", "WAIT"}
    assert body["action_label"]
    assert body["confidence"] in {"high", "medium", "low"}
    assert body["trend_index"]["score"] > 0
    assert len(body["reasons"]) >= 2
