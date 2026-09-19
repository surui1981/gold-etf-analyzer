"""回测 API 集成测试（V0.71.0 P3-a）。

覆盖：
- POST /api/v1/backtest/run：200 / 422 / 5 分钟节流
- GET /api/v1/backtest/coverage：返回覆盖期窗口
- GET/PUT /api/v1/backtest/config：保存 + 读取一致
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.services import backtest_throttle as throttle


@pytest.fixture(autouse=True)
def _reset_throttle_cache() -> None:
    """每个用例前清空 5 分钟节流缓存（避免跨测试污染）。"""
    throttle.clear()


def _valid_payload() -> dict:
    """最小合法回测请求体（默认 27 组合 × 默认阈值带 16 = 432 行，但库内 snapshots 为空）。"""
    return {
        "days": 90,
        "target": "etf",
        "weight_grid": {
            "tech": [0.3, 0.4],
            "macro": [0.4],
            "news": [0.3],
        },
        "threshold_bands": {
            "bullish": [55, 60],
            "bearish": [45, 40],
        },
    }


# ─────────────────── POST /api/v1/backtest/run ───────────────────


async def test_run_endpoint_returns_200(client: AsyncClient) -> None:
    """POST /run：合法 payload → 200 + summary 结构完整。"""
    resp = await client.post("/api/v1/backtest/run", json=_valid_payload())
    assert resp.status_code == 200
    body = resp.json()

    assert "rows" in body
    assert "summary" in body
    assert "coverage" in body
    assert body["target"] == "etf"
    assert body["cached"] is False
    # snapshots 为空时 rows 应为空但 summary 仍存在
    assert body["summary"]["total_rows"] == 0


async def test_run_endpoint_returns_cached_within_5min(client: AsyncClient) -> None:
    """POST /run：相同 payload 5 分钟内第二次 → cached=true + X-Backtest-Cached header。"""
    payload = _valid_payload()
    resp1 = await client.post("/api/v1/backtest/run", json=payload)
    assert resp1.status_code == 200
    assert resp1.headers.get("x-backtest-cached") == "false"
    assert resp1.json()["cached"] is False

    resp2 = await client.post("/api/v1/backtest/run", json=payload)
    assert resp2.status_code == 200
    assert resp2.headers.get("x-backtest-cached") == "true"
    assert resp2.json()["cached"] is True


async def test_run_invalid_params_422(client: AsyncClient) -> None:
    """POST /run：网格组合 > 125 → 422 拒绝。"""
    bad = {
        "days": 90,
        "target": "etf",
        "weight_grid": {
            "tech": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],  # 6×6×6 = 216
            "macro": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
            "news": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
        },
        "threshold_bands": {
            "bullish": [55, 60],
            "bearish": [45, 40],
        },
    }
    resp = await client.post("/api/v1/backtest/run", json=bad)
    assert resp.status_code == 422


async def test_run_invalid_target_422(client: AsyncClient) -> None:
    """POST /run：target 不在白名单 → 422。"""
    bad = _valid_payload()
    bad["target"] = "unknown_target"
    resp = await client.post("/api/v1/backtest/run", json=bad)
    assert resp.status_code == 422


# ─────────────────── GET /api/v1/backtest/coverage ───────────────────


async def test_coverage_returns_window_with_empty_db(client: AsyncClient) -> None:
    """GET /coverage：daily_snapshots 空 → 返回 0 天 + sample_warning。"""
    resp = await client.get("/api/v1/backtest/coverage?target=etf&days=90")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available_days"] == 0
    assert body["available_window_trading_days"] == 0
    assert body["sample_warning"] is True
    assert body["start_date"] is None
    assert body["end_date"] is None
    assert "无法回测" in body["note"]


async def test_coverage_accepts_silver_targets(client: AsyncClient) -> None:
    """GET /coverage：target=silver_etf/silver_ny 通过 pattern 校验（V0.71.0 新增）。"""
    for tgt in ("silver_etf", "silver_ny"):
        resp = await client.get(f"/api/v1/backtest/coverage?target={tgt}&days=60")
        assert resp.status_code == 200, f"{tgt} → {resp.status_code}"
        assert resp.json()["target"] == tgt


# ─────────────────── GET/PUT /api/v1/backtest/config ───────────────────


async def test_get_backtest_config_default(client: AsyncClient) -> None:
    """GET /config：未保存 → 返回默认配置。"""
    resp = await client.get("/api/v1/backtest/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["days"] == 90
    assert body["target"] == "etf"
    assert body["weight_grid"]["tech"] == [0.3, 0.4, 0.5]
    assert body["threshold_bands"]["bullish"] == [55, 60, 65, 70]


async def test_put_then_get_backtest_config(client: AsyncClient) -> None:
    """PUT /config：保存 → GET 取回一致。"""
    payload = {
        "days": 180,
        "target": "silver_etf",
        "weight_grid": {
            "tech": [0.4, 0.5],
            "macro": [0.3],
            "news": [0.2],
        },
        "threshold_bands": {
            "bullish": [60, 65, 70],
            "bearish": [40, 35, 30],
        },
    }
    resp = await client.put("/api/v1/backtest/config", json=payload)
    assert resp.status_code == 200
    assert resp.json()["target"] == "silver_etf"
    assert resp.json()["days"] == 180

    resp = await client.get("/api/v1/backtest/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["target"] == "silver_etf"
    assert body["days"] == 180
    assert body["weight_grid"]["tech"] == [0.4, 0.5]
    assert body["threshold_bands"]["bearish"] == [40, 35, 30]


async def test_put_backtest_config_invalid_422(client: AsyncClient) -> None:
    """PUT /config：days 越界 → 422。"""
    bad = {
        "days": 500,  # > 365
        "target": "etf",
        "weight_grid": {"tech": [0.3], "macro": [0.4], "news": [0.3]},
        "threshold_bands": {"bullish": [55], "bearish": [45]},
    }
    resp = await client.put("/api/v1/backtest/config", json=bad)
    assert resp.status_code == 422