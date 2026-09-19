"""交易面与决策 API 集成测试（注入假行情源）。"""

from datetime import date

import pytest
from httpx import AsyncClient

from app.dependencies import get_market_data_repository


class FakeMarket:
    """假行情：ETF 价固定 10.0（V0.61.0 起持仓估值用 ETF 价），历史序列上升。"""

    async def get_gold_quote(self, symbol: str = "XAU"):
        """纽约金价（美元/盎司）——不参与 ETF 持仓估值。"""
        return type(
            "Q",
            (),
            {"symbol": symbol, "price_usd": 4349.7, "change_pct": 0.5, "updated_at": date.today()},
        )()

    async def get_gold_etf_quote(self, symbol: str = "518880"):
        """518880 ETF 价（元/份）——持仓估值唯一价格源。"""
        return type(
            "Q",
            (),
            {"symbol": symbol, "price_usd": 10.0, "change_pct": 0.5, "updated_at": date.today()},
        )()

    async def get_gold_gram_quote(self, symbol: str = "Au99.99"):
        """Au99.99 元/克——「按克开仓」折算用（V0.70.0 P2 #8）。"""
        return type(
            "Q",
            (),
            {"symbol": symbol, "price_usd": 990.5, "change_pct": 0.35, "updated_at": date.today()},
        )()

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

    async def get_gold_gram_history(self, days: int = 60):
        from datetime import timedelta

        from app.repositories.market_data import GoldKline

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

    async def get_us_gold_history(self, days: int = 60):
        from datetime import timedelta

        from app.repositories.market_data import GoldKline

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


# =========================================================================
# V0.70.0 P2 #8 · 克数持仓 API 测试
# =========================================================================


async def test_open_position_with_grams_body(client: AsyncClient) -> None:
    """按克开仓（grams 入参）：1000 g → 99000 份（990 手 × 100）。"""
    resp = await client.post(
        "/api/v1/positions",
        json={"symbol": "518880", "grams": 1000.0, "price": 10.0},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["quantity"] == 99000
    assert body["grams_held"] == pytest.approx(1000.0, abs=0.001)


async def test_add_trade_with_grams_body(client: AsyncClient) -> None:
    """按克加仓：原 1000 g + 500 g → grams_held ≈ 1500。"""
    resp = await client.post(
        "/api/v1/positions",
        json={"symbol": "518880", "grams": 1000.0, "price": 10.0},
    )
    pid = resp.json()["id"]

    resp = await client.post(
        f"/api/v1/positions/{pid}/trades",
        json={"side": "buy", "grams": 500.0, "price": 10.5},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["grams_held"] == pytest.approx(1500.0, abs=0.001)


async def test_open_position_rejects_both_quantity_and_grams(client: AsyncClient) -> None:
    """quantity 与 grams 同时传 → 422（Pydantic 校验）。"""
    resp = await client.post(
        "/api/v1/positions",
        json={"symbol": "518880", "quantity": 100, "grams": 100.0, "price": 10.0},
    )
    assert resp.status_code == 422


async def test_add_trade_sell_more_grams_than_held(client: AsyncClient) -> None:
    """卖出克数 > 当前持有 → 400。"""
    resp = await client.post(
        "/api/v1/positions",
        json={"symbol": "518880", "grams": 1000.0, "price": 10.0},
    )
    pid = resp.json()["id"]

    resp = await client.post(
        f"/api/v1/positions/{pid}/trades",
        json={"side": "sell", "grams": 2000.0, "price": 10.0},
    )
    assert resp.status_code == 400
    assert "克数" in resp.json()["detail"]
