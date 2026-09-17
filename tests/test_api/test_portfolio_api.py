"""交易业绩 API 集成测试：收益曲线 + 获利分析 + ETF 报价 + 持仓流水（V0.61.0）。"""

from datetime import date, timedelta

from httpx import AsyncClient

from app.dependencies import get_market_data_repository
from app.main import app
from app.repositories.market_data import GoldKline


class FakeMarket:
    """假行情：ETF 历史价固定 10.0，日期覆盖最近 120 天（含今天）。"""

    async def get_gold_history(self, days: int = 60):
        today = date.today()
        return [
            GoldKline(
                date=today - timedelta(days=119 - i),
                open=10.0,
                close=10.0,
                high=10.0,
                low=10.0,
                volume=0.0,
            )
            for i in range(120)
        ]

    async def get_gold_etf_quote(self, symbol: str = "518880"):
        return type(
            "Q",
            (),
            {
                "symbol": symbol,
                "price_usd": 10.0,
                "change_pct": 0.0,
                "updated_at": date.today(),
            },
        )()

    async def get_gold_quote(self, symbol: str = "XAU"):
        return type(
            "Q",
            (),
            {
                "symbol": symbol,
                "price_usd": 4349.7,
                "change_pct": 0.0,
                "updated_at": date.today(),
            },
        )()


def _override() -> None:
    app.dependency_overrides[get_market_data_repository] = lambda: FakeMarket()


async def test_performance_empty(client: AsyncClient) -> None:
    """无交易：空态 200 + 引导文案。"""
    _override()
    try:
        r = await client.get("/api/v1/portfolio/performance")
        assert r.status_code == 200
        body = r.json()
        assert body["total_pnl"] == 0
        assert body["win_rate"] == 0
        assert "暂无交易记录" in body["summary"]
    finally:
        app.dependency_overrides.clear()


async def test_equity_curve_empty(client: AsyncClient) -> None:
    """无交易：收益曲线返回空点位而非报错。"""
    _override()
    try:
        r = await client.get("/api/v1/portfolio/equity-curve?days=90")
        assert r.status_code == 200
        body = r.json()
        assert body["days"] == 90
        assert body["points"] == []
    finally:
        app.dependency_overrides.clear()


async def test_equity_and_performance_after_open(client: AsyncClient) -> None:
    """建仓后：收益曲线与获利分析联动（ETF 价 10.0 vs 成本 8.0）。"""
    _override()
    try:
        r = await client.post(
            "/api/v1/positions",
            json={"symbol": "518880", "quantity": 100, "price": 8.0, "fee": 0},
        )
        assert r.status_code == 201

        r = await client.get("/api/v1/portfolio/equity-curve?days=90")
        assert r.status_code == 200
        last = r.json()["points"][-1]
        assert last["quantity"] == 100
        assert last["return_pct"] == 25.0  # (1000-800)/800

        r = await client.get("/api/v1/portfolio/performance")
        perf = r.json()
        assert perf["total_invested"] == 800.0
        assert perf["unrealized_pnl"] == 200.0
        assert perf["open_positions"] == 1
    finally:
        app.dependency_overrides.clear()


async def test_equity_curve_days_validation(client: AsyncClient) -> None:
    """days 超出下界（<7）应被 Pydantic 校验拒绝。"""
    _override()
    try:
        r = await client.get("/api/v1/portfolio/equity-curve?days=3")
        assert r.status_code == 422
    finally:
        app.dependency_overrides.clear()


async def test_position_trades_endpoint(client: AsyncClient) -> None:
    """持仓流水查询：正常返回倒序流水；持仓不存在返回 404。"""
    _override()
    try:
        r = await client.post(
            "/api/v1/positions",
            json={"symbol": "518880", "quantity": 100, "price": 8.0, "fee": 1.5},
        )
        pid = r.json()["id"]

        r = await client.get(f"/api/v1/positions/{pid}/trades")
        assert r.status_code == 200
        trades = r.json()
        assert len(trades) == 1
        assert trades[0]["side"] == "buy"
        assert trades[0]["fee"] == 1.5

        r = await client.get("/api/v1/positions/9999/trades")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()


async def test_market_etf_quote_endpoint(client: AsyncClient) -> None:
    """ETF 报价端点（元/份）与纽约金端点（美元/盎司）分离，且单位字段显式。"""
    _override()
    try:
        r = await client.get("/api/v1/market/gold/etf-quote")
        assert r.status_code == 200
        body = r.json()
        assert body["symbol"] == "518880"
        assert body["price"] == 10.0
        assert body["currency"] == "CNY"
        assert body["unit"] == "元/份"
        assert "price_usd" not in body, "ETF 报价不得使用易混淆的 price_usd 字段"

        r = await client.get("/api/v1/market/gold")
        assert r.status_code == 200
        assert r.json()["price_usd"] == 4349.7
    finally:
        app.dependency_overrides.clear()
