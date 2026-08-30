"""权重配置 API 测试。"""

from httpx import AsyncClient


async def test_get_weights_default(client: AsyncClient) -> None:
    """默认权重返回。"""
    resp = await client.get("/api/v1/settings/weights")
    assert resp.status_code == 200
    body = resp.json()

    assert body["trend"]["structure"] == 0.30
    assert body["macro"]["dxy"] == 0.25
    assert body["combine"]["tech"] == 0.30
    assert body["combine"]["news"] == 0.30


async def test_put_and_get_weights(client: AsyncClient) -> None:
    """保存后读取一致。"""
    payload = {
        "trend": {"structure": 0.4, "momentum": 0.2, "support": 0.2, "momentum_rsi": 0.1, "drawdown": 0.1},
        "macro": {"dxy": 0.3, "us10y": 0.2, "us30y": 0.1, "vix": 0.2, "cb_gold": 0.2},
        "combine": {"tech": 0.5, "macro": 0.3, "news": 0.2},
    }
    resp = await client.put("/api/v1/settings/weights", json=payload)
    assert resp.status_code == 200
    assert resp.json()["trend"]["structure"] == 0.4

    resp = await client.get("/api/v1/settings/weights")
    assert resp.json()["combine"]["tech"] == 0.5


async def test_put_invalid_sum_422(client: AsyncClient) -> None:
    """权重和不为 1 → 422。"""
    payload = {
        "trend": {"structure": 0.5, "momentum": 0.5, "support": 0.2, "momentum_rsi": 0.1, "drawdown": 0.1},
        "macro": {"dxy": 0.25, "us10y": 0.2, "us30y": 0.15, "vix": 0.15, "cb_gold": 0.25},
        "combine": {"tech": 0.6, "macro": 0.4, "news": 0.2},
    }
    resp = await client.put("/api/v1/settings/weights", json=payload)
    assert resp.status_code == 422
