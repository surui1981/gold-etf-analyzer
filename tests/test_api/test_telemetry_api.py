"""埋点接口测试（V0.68.0 客户端埋点底座）。"""

from httpx import AsyncClient


async def test_ingest_endpoint_accepts_batch(client: AsyncClient) -> None:
    """POST /api/v1/telemetry/ingest 接受批量事件。"""
    r = await client.post(
        "/api/v1/telemetry/ingest",
        json={
            "events": [
                {
                    "event_type": "page_view",
                    "page": "/static/portfolio.html",
                    "payload": {"from": "test"},
                    "session_id": "0123456789abcdef0123456789abcdef",
                },
                {
                    "event_type": "nav_drawer_open",
                    "page": "/static/trend.html",
                    "payload": {},
                    "session_id": "0123456789abcdef0123456789abcdef",
                },
            ]
        },
    )
    assert r.status_code == 200
    d = r.json()
    assert d["accepted"] == 2
    assert d["rejected"] == 0
    assert d["rejected_reasons"] == []


async def test_ingest_endpoint_rejects_outside_whitelist(client: AsyncClient) -> None:
    """白名单外事件类型返回 200 但带 rejected。"""
    r = await client.post(
        "/api/v1/telemetry/ingest",
        json={
            "events": [
                {
                    "event_type": "BAD_TYPE",
                    "page": "/x",
                    "payload": {},
                    "session_id": "x" * 32,
                }
            ]
        },
    )
    assert r.status_code == 200
    d = r.json()
    assert d["accepted"] == 0
    assert d["rejected"] == 1
    assert any("BAD_TYPE" in r for r in d["rejected_reasons"])


async def test_ingest_endpoint_validates_payload_size(client: AsyncClient) -> None:
    """Pydantic 在端点层先拦下过大 event_type / 过长 page。"""
    r = await client.post(
        "/api/v1/telemetry/ingest",
        json={
            "events": [
                {
                    "event_type": "x" * 33,  # > max_length=32
                    "page": "/static/portfolio.html",
                    "payload": {},
                    "session_id": "x" * 32,
                }
            ]
        },
    )
    assert r.status_code == 422  # Pydantic validation error


async def test_stats_endpoint_returns_aggregation(client: AsyncClient) -> None:
    """GET /api/v1/telemetry/stats?days=7 返回按类型聚合。"""
    # 先入 2 条
    await client.post(
        "/api/v1/telemetry/ingest",
        json={
            "events": [
                {
                    "event_type": "page_view",
                    "page": "/static/portfolio.html",
                    "payload": {},
                    "session_id": "abcdef0123456789abcdef0123456789",
                }
            ]
        },
    )
    r = await client.get("/api/v1/telemetry/stats?days=7")
    assert r.status_code == 200
    d = r.json()
    assert d["days"] == 7
    assert d["total"] >= 1
    by = {b["event_type"]: b for b in d["by_type"]}
    assert "page_view" in by
    assert by["page_view"]["count_7d"] >= 1


async def test_stats_endpoint_validates_days_range(client: AsyncClient) -> None:
    """days 参数越界返回 422（ge=1, le=30）。"""
    r = await client.get("/api/v1/telemetry/stats?days=0")
    assert r.status_code == 422
    r = await client.get("/api/v1/telemetry/stats?days=365")
    assert r.status_code == 422
