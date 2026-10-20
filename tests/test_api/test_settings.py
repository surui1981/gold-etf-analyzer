"""权重配置 API 测试。"""

from datetime import date

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
            {
                "kind": "window",
                "window": {"mode": "quiet", "start": "22:00", "end": "07:00"},
                "enabled": True,
            },
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


# ───────────────────── V0.110.0 · 宏观因子手动校准 API ─────────────────────


async def test_v01100_get_macro_overrides_default_empty(client: AsyncClient) -> None:
    """未设置过 → 5 个因子全为 null（页面据此显示「留空 = 自动源」）。"""
    resp = await client.get("/api/v1/settings/macro-overrides")
    assert resp.status_code == 200
    body = resp.json()
    for key in ("dxy", "us10y", "us30y", "vix", "cb_gold"):
        assert body[key] is None


async def test_v01100_put_and_get_macro_overrides(client: AsyncClient) -> None:
    """保存后读取一致，且 as_of 原样回传为 ISO 字符串。"""
    payload = {
        "dxy": {"value": 96.8, "as_of": "2026-10-21", "note": "Wind 收盘"},
        "vix": {"value": 21.4, "as_of": "2026-10-21", "note": None},
    }
    resp = await client.put("/api/v1/settings/macro-overrides", json=payload)
    assert resp.status_code == 200
    assert resp.json()["dxy"]["value"] == 96.8

    resp = await client.get("/api/v1/settings/macro-overrides")
    body = resp.json()
    assert body["dxy"]["as_of"] == "2026-10-21"
    assert body["dxy"]["note"] == "Wind 收盘"
    assert body["vix"]["value"] == 21.4
    assert body["us10y"] is None  # 未设置的因子保持 None


async def test_v01100_put_macro_overrides_replaces_whole_set(client: AsyncClient) -> None:
    """整体替换语义：第二次保存只带 dxy → 先前的 vix 覆盖被清掉。"""
    await client.put(
        "/api/v1/settings/macro-overrides",
        json={
            "dxy": {"value": 96.8, "as_of": "2026-10-21"},
            "vix": {"value": 21.4, "as_of": "2026-10-21"},
        },
    )
    resp = await client.put(
        "/api/v1/settings/macro-overrides",
        json={"dxy": {"value": 96.9, "as_of": "2026-10-21"}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dxy"]["value"] == 96.9
    assert body["vix"] is None


async def test_v01100_put_macro_overrides_missing_as_of_422(client: AsyncClient) -> None:
    """缺 as_of（数据日期）→ 422：没有日期就没法算滞后，也无法向用户披露时效。"""
    resp = await client.put("/api/v1/settings/macro-overrides", json={"dxy": {"value": 96.8}})
    assert resp.status_code == 422


async def test_v01100_put_macro_overrides_unknown_key_ignored(client: AsyncClient) -> None:
    """未知因子键被忽略（Pydantic 默认忽略多余字段），不污染存储。"""
    resp = await client.put(
        "/api/v1/settings/macro-overrides",
        json={"dxy": {"value": 96.8, "as_of": "2026-10-21"}, "spx": {"value": 1, "as_of": "2026-10-21"}},
    )
    assert resp.status_code == 200
    assert "spx" not in resp.json()


def _prime_served_cache(marker: str) -> None:
    """往 served_cache 塞一条占位结果。

    ``set_served`` 会打日志读 ``result.index.score``，所以不能直接传 dict，
    得给一个带 ``index.score`` 的最小对象。
    """
    from types import SimpleNamespace

    from app.services import cache as served_cache

    stub = SimpleNamespace(index=SimpleNamespace(score=1.0))
    served_cache.set_served("ny", stub, on_date=date.today())


async def test_v01100_put_macro_overrides_invalidates_served_cache(client: AsyncClient) -> None:
    """保存覆盖后必须失效 served_cache —— 它盖在 MacroFactorService._CACHE 之上。

    V0.110.0 实测踩到的坑：只清 ``clear_macro_cache()`` 时，GET /market/gold/trend
    仍从 served_cache 回放覆盖前的响应，页面「当前生效」列纹丝不动。用户看到的是
    "保存成功但没生效"，日志里没有任何异常。
    """
    from app.services import cache as served_cache

    _prime_served_cache("before-override")
    assert served_cache.get_served("ny") is not None

    resp = await client.put(
        "/api/v1/settings/macro-overrides",
        json={"dxy": {"value": 97.42, "as_of": "2026-10-21"}},
    )
    assert resp.status_code == 200

    assert served_cache.get_served("ny") is None, "served_cache 未失效，trend 会回放旧响应"


async def test_v01100_put_weights_invalidates_served_cache(client: AsyncClient) -> None:
    """保存权重同样要失效 served_cache —— 权重直接参与综合指数合成。

    这是本版顺带修掉的**既有缺陷**：``PUT /settings/weights`` 原先一个缓存都不清，
    改完权重后首页最长 600s（served_cache_ttl_seconds）仍显示旧指数。
    """
    from app.services import cache as served_cache

    _prime_served_cache("before-weights")
    assert served_cache.get_served("ny") is not None

    resp = await client.put(
        "/api/v1/settings/weights",
        json={
            "trend": {
                "structure": 0.3, "momentum": 0.2, "support": 0.2,
                "momentum_rsi": 0.15, "drawdown": 0.15,
            },
            "macro": {"dxy": 0.25, "us10y": 0.2, "us30y": 0.15, "vix": 0.2, "cb_gold": 0.2},
            "combine": {"tech": 0.4, "macro": 0.4, "news": 0.2},
        },
    )
    assert resp.status_code == 200

    assert served_cache.get_served("ny") is None, "served_cache 未失效，trend 会回放旧指数"
