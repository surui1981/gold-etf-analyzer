"""宏观数据源（FRED / Yahoo）解析与取数单测（V0.118.0）。

不依赖真实网络：``_fetch_text`` 全部打桩。
重点锁两件事：
1. **解析不能造脏数据** —— 缺值（``.``）不前值填充，Yahoo 当日未收盘的 ``null`` 跳过；
2. **User-Agent 按源分别指定** —— 三个源的 UA 规则互相矛盾，发错就是 403 或读超时。
"""

from datetime import date

import pytest

from app.repositories.macro_sources import (
    BROWSER_UA,
    _fred_url,
    clear_macro_sources_cache,
    parse_fred_csv,
    parse_yahoo_chart_json,
)

# ───────────────────── FRED CSV 解析 ─────────────────────


def test_parse_fred_csv_basic() -> None:
    """标准 FRED CSV：跳过表头，按日期升序。"""
    text = "observation_date,DFII10\n2026-10-21,2.63\n2026-10-22,2.64\n"
    assert parse_fred_csv(text) == [(date(2026, 10, 21), 2.63), (date(2026, 10, 22), 2.64)]


def test_parse_fred_csv_skips_missing_values() -> None:
    """缺值用 ``.`` 表示 → 跳过，**不做前值填充**。

    填充会把「当天没数据」伪装成「当天就是这个数」—— 滚动分位窗口里两者含义完全不同。
    """
    text = "observation_date,VIXCLS\n2026-10-21,19.00\n2026-10-22,.\n2026-10-23,18.50\n"
    assert parse_fred_csv(text) == [(date(2026, 10, 21), 19.0), (date(2026, 10, 23), 18.5)]


def test_parse_fred_csv_skips_empty_and_malformed() -> None:
    """空值 / 坏日期 / 坏数字 → 跳过，不抛异常。"""
    text = (
        "observation_date,DFII10\n"
        "2026-10-21,2.63\n"
        ",2.64\n"
        "not-a-date,2.65\n"
        "2026-10-23,abc\n"
        "2026-10-24,\n"
    )
    assert parse_fred_csv(text) == [(date(2026, 10, 21), 2.63)]


def test_parse_fred_csv_empty_input() -> None:
    """空串 → 空列表。"""
    assert parse_fred_csv("") == []


def test_fred_url_contains_series_and_date_range() -> None:
    """URL 拼装：序列 ID + cosd/coed 区间。"""
    base = "https://example.org/graph/fredgraph.csv?id={series_id}"
    url = _fred_url(base, "DFII10", date(2026, 1, 1), date(2026, 10, 25))
    assert "DFII10" in url
    assert "cosd=2026-01-01" in url
    assert "coed=2026-10-25" in url


# ───────────────────── Yahoo chart JSON 解析 ─────────────────────


def test_parse_yahoo_chart_json_basic() -> None:
    """标准 chart JSON：timestamp 与 close 按位置对齐。"""
    import json

    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [1760000000, 1760086400],
                    "indicators": {"quote": [{"close": [101.5, 101.75]}]},
                }
            ]
        }
    }
    out = parse_yahoo_chart_json(json.dumps(payload))
    assert len(out) == 2
    assert out[-1][1] == 101.75


def test_parse_yahoo_chart_json_skips_null_close() -> None:
    """当日未收盘时末位 close 为 ``null`` → 跳过（不能写成 None 读数）。"""
    import json

    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [1760000000, 1760086400],
                    "indicators": {"quote": [{"close": [101.5, None]}]},
                }
            ]
        }
    }
    out = parse_yahoo_chart_json(json.dumps(payload))
    assert len(out) == 1
    assert out[0][1] == 101.5


def test_parse_yahoo_chart_json_malformed() -> None:
    """坏 JSON / 空 result → 空列表，不抛异常。"""
    assert parse_yahoo_chart_json("not json") == []
    assert parse_yahoo_chart_json('{"chart":{"result":[]}}') == []
    assert parse_yahoo_chart_json('{"chart":{"error":{"code":"Not Found"}}}') == []


# ───────────────────── User-Agent 规则 ─────────────────────


def test_http_text_sends_no_ua_by_default() -> None:
    """**不发 UA** → urllib 用默认 ``Python-urllib/3.x``（FRED WAF 白名单里）。

    发 Mozilla 反而会被 FRED **挂起**（读超时，不是 403）—— 极易误判成网络抖动。
    """
    from app.repositories.macro_sources import _http_text

    seen: dict = {}

    class FakeResp:
        def read(self) -> bytes:
            return b"ok"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=15):
        seen["headers"] = dict(req.header_items())
        return FakeResp()

    import urllib.request

    orig = urllib.request.urlopen
    urllib.request.urlopen = fake_urlopen
    try:
        _http_text("https://example.org/x")
    finally:
        urllib.request.urlopen = orig

    header_names = {k.lower() for k in seen["headers"]}
    assert "user-agent" not in header_names


def test_http_text_sends_browser_ua_when_given() -> None:
    """显式给 UA → 请求头里带上（H.15 / Yahoo 必须走这条）。"""
    from app.repositories.macro_sources import _http_text

    seen: dict = {}

    class FakeResp:
        def read(self) -> bytes:
            return b"ok"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=15):
        seen["headers"] = {k.lower(): v for k, v in req.header_items()}
        return FakeResp()

    import urllib.request

    orig = urllib.request.urlopen
    urllib.request.urlopen = fake_urlopen
    try:
        _http_text("https://example.org/x", 15, BROWSER_UA)
    finally:
        urllib.request.urlopen = orig

    assert seen["headers"].get("user-agent") == BROWSER_UA


# ───────────────────── latest 取数 ─────────────────────


@pytest.mark.asyncio
async def test_fetch_fred_latest_returns_last_point(monkeypatch) -> None:
    """``fetch_fred_latest`` → 序列最后一个有效点。"""
    from app.repositories import macro_sources

    clear_macro_sources_cache()

    async def fake_fetch_text(url, timeout=15, user_agent=None):
        seen["url"] = url
        seen["user_agent"] = user_agent
        return "observation_date,DFII10\n2026-10-21,2.63\n2026-10-22,2.64\n"

    seen: dict = {}
    monkeypatch.setattr(macro_sources, "_fetch_text", fake_fetch_text)

    result = await macro_sources.fetch_fred_latest("DFII10", base_url="https://x/?id={series_id}")
    assert result == (2.64, date(2026, 10, 22))
    # FRED 不发 UA（与 H.15 / Yahoo 相反）
    assert seen["user_agent"] is None
    clear_macro_sources_cache()


@pytest.mark.asyncio
async def test_fetch_fred_latest_returns_none_on_empty(monkeypatch) -> None:
    """源返回空 → None（调用方回退静态参考值）。"""
    from app.repositories import macro_sources

    clear_macro_sources_cache()

    async def fake_fetch_text(url, timeout=15, user_agent=None):
        return "observation_date,DFII10\n"

    monkeypatch.setattr(macro_sources, "_fetch_text", fake_fetch_text)

    assert (
        await macro_sources.fetch_fred_latest("DFII10", base_url="https://x/?id={series_id}")
        is None
    )
    clear_macro_sources_cache()


@pytest.mark.asyncio
async def test_fetch_yahoo_latest_sends_browser_ua(monkeypatch) -> None:
    """Yahoo 必须带浏览器 UA（不发直接 403）。"""
    from app.repositories import macro_sources

    clear_macro_sources_cache()

    async def fake_fetch_text(url, timeout=15, user_agent=None):
        seen["url"] = url
        seen["user_agent"] = user_agent
        return (
            '{"chart":{"result":[{"timestamp":[1760000000],'
            '"indicators":{"quote":[{"close":[101.75]}]}}]}}'
        )

    seen: dict = {}
    monkeypatch.setattr(macro_sources, "_fetch_text", fake_fetch_text)

    result = await macro_sources.fetch_yahoo_latest(
        "DX-Y.NYB", base_url="https://x/?s={symbol}&r={range}&i={interval}"
    )
    assert result == (101.75, date(2025, 10, 9))
    assert seen["user_agent"] == BROWSER_UA
    assert "DX-Y.NYB" in seen["url"]
    clear_macro_sources_cache()
