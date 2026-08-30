"""机会分析 API 集成测试（含参数校验）。"""

from httpx import AsyncClient

BULLISH_PAYLOAD = {
    "factors": {
        "dxy": 96.0,
        "us10y_yield": 3.6,
        "real_rate": 1.4,
        "inflation_expectation": 3.0,
        "risk_off": 9,
    },
    "gold_price_usd": 2350.5,
}


async def test_evaluate_opportunity_returns_score(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/analysis/opportunity", json=BULLISH_PAYLOAD)
    assert resp.status_code == 200
    body = resp.json()

    assert body["score"] >= 70
    assert body["window"] == "strong"
    assert body["signal"] == "bullish"
    assert body["record_id"] is not None
    assert len(body["factors"]) == 5
    # 因子明细含方向字段，供前端红绿着色区分利多/利空
    assert all(
        f["direction"] in {"bullish", "bearish", "neutral"} for f in body["factors"]
    )


async def test_history_after_evaluation(client: AsyncClient) -> None:
    await client.post("/api/v1/analysis/opportunity", json=BULLISH_PAYLOAD)
    resp = await client.get("/api/v1/analysis/history")
    assert resp.status_code == 200
    records = resp.json()
    assert len(records) == 1
    assert records[0]["score"] >= 70
    assert records[0]["window"] == "strong"


async def test_invalid_risk_off_rejected(client: AsyncClient) -> None:
    """risk_off 超出 0-10 范围应被 Pydantic 拒绝（422）。"""
    payload = {
        "factors": {
            "dxy": 100.0,
            "us10y_yield": 4.0,
            "real_rate": 2.0,
            "inflation_expectation": 2.5,
            "risk_off": 11,
        }
    }
    resp = await client.post("/api/v1/analysis/opportunity", json=payload)
    assert resp.status_code == 422


async def test_missing_factor_rejected(client: AsyncClient) -> None:
    """缺少必填因子应返回 422。"""
    resp = await client.post(
        "/api/v1/analysis/opportunity",
        json={"factors": {"dxy": 100.0}},
    )
    assert resp.status_code == 422


async def test_history_limit_respected(client: AsyncClient) -> None:
    """limit 越界应被 Query 参数校验拦截。"""
    resp = await client.get("/api/v1/analysis/history?limit=0")
    assert resp.status_code == 422
