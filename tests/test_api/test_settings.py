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
        "trend": {
            "structure": 0.4,
            "momentum": 0.2,
            "support": 0.2,
            "momentum_rsi": 0.1,
            "drawdown": 0.1,
        },
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
        "trend": {
            "structure": 0.5,
            "momentum": 0.5,
            "support": 0.2,
            "momentum_rsi": 0.1,
            "drawdown": 0.1,
        },
        "macro": {"dxy": 0.25, "us10y": 0.2, "us30y": 0.15, "vix": 0.15, "cb_gold": 0.25},
        "combine": {"tech": 0.6, "macro": 0.4, "news": 0.2},
    }
    resp = await client.put("/api/v1/settings/weights", json=payload)
    assert resp.status_code == 422


# ───────────────────── V0.74.0 N+18 · alert-rules API ─────────────────────


async def test_n18_get_alert_rules_default(client: AsyncClient) -> None:
    """GET /alert-rules 默认空 rules 列表 + channels 至少 1 项。"""
    resp = await client.get("/api/v1/settings/alert-rules")
    assert resp.status_code == 200
    body = resp.json()
    assert "rules" in body
    assert isinstance(body["rules"], list)
    assert "channels" in body
    assert len(body["channels"]) >= 1


async def test_n18_put_new_schema_rules(client: AsyncClient) -> None:
    """PUT /alert-rules 新格式 rules 列表(异构 kind)→ 200 + GET 回读一致。"""
    payload = {
        "rules": [
            {"kind": "volatility", "threshold_pct": 2.5, "enabled": True, "note": "测试波动"},
            {"kind": "crossing", "axis_levels": 4, "enabled": True},
            {"kind": "window", "window": {"mode": "quiet", "start": "22:00", "end": "07:00"}, "enabled": True},
            {"kind": "t_plus_n", "t_plus_n_days": 3, "t_plus_n_pct": 1.5, "enabled": True},
        ],
        "channels": ["email", "wechat"],
    }
    resp = await client.put("/api/v1/settings/alert-rules", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["rules"]) == 4
    kinds = sorted(r["kind"] for r in body["rules"])
    assert kinds == ["crossing", "t_plus_n", "volatility", "window"]
    # GET 回读
    resp2 = await client.get("/api/v1/settings/alert-rules")
    assert resp2.json()["rules"][0]["threshold_pct"] == 2.5


async def test_n18_put_legacy_schema_migrates(client: AsyncClient) -> None:
    """PUT /alert-rules 旧扁平字段 → 自动迁移为 rules 列表(向后兼容)。"""
    payload = {
        "level_crossing_enabled": True,
        "volatility_enabled": True,
        "volatility_pct": 2.0,
        "quiet_hours": {"start": "23:00", "end": "06:00"},
        "channels": ["email"],
    }
    resp = await client.put("/api/v1/settings/alert-rules", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    kinds = sorted(r["kind"] for r in body["rules"])
    assert kinds == ["crossing", "volatility", "window"], f"旧字段未迁移: {kinds}"
    vol = next(r for r in body["rules"] if r["kind"] == "volatility")
    assert vol["threshold_pct"] == 2.0
    win = next(r for r in body["rules"] if r["kind"] == "window")
    assert win["window"]["start"] == "23:00"


async def test_n18_put_invalid_kind_rejected(client: AsyncClient) -> None:
    """PUT /alert-rules 非法 kind → 422。"""
    payload = {
        "rules": [{"kind": "nonexistent", "enabled": True}],
        "channels": ["email"],
    }
    resp = await client.put("/api/v1/settings/alert-rules", json=payload)
    assert resp.status_code == 422


async def test_n18_put_threshold_out_of_range_rejected(client: AsyncClient) -> None:
    """PUT /alert-rules threshold_pct 越界(>20)→ 422。"""
    payload = {
        "rules": [{"kind": "volatility", "threshold_pct": 50.0, "enabled": True}],
        "channels": ["email"],
    }
    resp = await client.put("/api/v1/settings/alert-rules", json=payload)
    assert resp.status_code == 422


async def test_n18_put_empty_channels_rejected(client: AsyncClient) -> None:
    """PUT /alert-rules channels 为空 → 422。"""
    payload = {
        "rules": [{"kind": "volatility", "threshold_pct": 3.0, "enabled": True}],
        "channels": [],
    }
    resp = await client.put("/api/v1/settings/alert-rules", json=payload)
    assert resp.status_code == 422


async def test_n18_put_duplicate_channels_rejected(client: AsyncClient) -> None:
    """PUT /alert-rules channels 重复 → 422。"""
    payload = {
        "rules": [{"kind": "volatility", "threshold_pct": 3.0, "enabled": True}],
        "channels": ["email", "email"],
    }
    resp = await client.put("/api/v1/settings/alert-rules", json=payload)
    assert resp.status_code == 422


async def test_n18_put_webpush_channel_accepted(client: AsyncClient) -> None:
    """PUT /alert-rules 含 webpush 渠道 → 200(后端创建时不强制需要 vapid)。"""
    payload = {
        "rules": [{"kind": "volatility", "threshold_pct": 3.0, "enabled": True}],
        "channels": ["webpush"],
    }
    resp = await client.put("/api/v1/settings/alert-rules", json=payload)
    assert resp.status_code == 200
    assert resp.json()["channels"] == ["webpush"]
