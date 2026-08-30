"""行情 API 测试。"""

from httpx import AsyncClient


async def test_gold_quote(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/market/gold")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "XAU"
    assert body["price_usd"] > 0
    assert "updated_at" in body
