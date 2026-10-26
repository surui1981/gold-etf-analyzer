"""宏观数据源（FRED / Yahoo / Eurostat）解析与取数单测（V0.118.0 / V0.119.0）。

不依赖真实网络：``_fetch_text`` 全部打桩。
重点锁两件事：
1. **解析不能造脏数据** —— 缺值（``.``）不前值填充，Yahoo 当日未收盘的 ``null`` 跳过；
2. **User-Agent 按源分别指定** —— 三个源的 UA 规则互相矛盾，发错就是 403 或读超时。

V0.119.0 追加低频序列（季度/年度）的口径锁：
3. **观测期归一到期末** —— FRED 用期初日期、Eurostat 用 ``"2026-Q2"`` 标签，
   两者都必须换算成 ISO 期末日（否则前端滞后天数凭空多一整个季度）。
"""

import json
from datetime import date

import pytest

from app.repositories.macro_sources import (
    BROWSER_UA,
    FRED_PERIODIC_SERIES,
    _fred_url,
    clear_macro_sources_cache,
    eurostat_period_end,
    fred_period_end,
    parse_eurostat_gov_debt,
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


# ───────────────────── V0.119.0 · 低频序列（季度/年度） ─────────────────────
#
# 3 个政府债务因子的源与现有 8 个因子完全不同：
# - FRED 低频序列用**期初日期**标注观测（2026-01-01 = 2026Q1），必须归一到**期末**；
# - Eurostat 用 ``"2026-Q2"`` 期间标签，``Date.parse`` 解析不了，必须自己换算；
# - 季度/年度序列在 30 天窗口里一条都取不到 ⇒ ���须给足 lookback。


def test_fred_period_end_quarterly() -> None:
    """FRED 季度：期初 → 期末（季末最后一天）。"""
    assert fred_period_end(date(2026, 1, 1), "quarterly") == date(2026, 3, 31)
    assert fred_period_end(date(2026, 4, 1), "quarterly") == date(2026, 6, 30)
    assert fred_period_end(date(2026, 7, 1), "quarterly") == date(2026, 9, 30)
    assert fred_period_end(date(2026, 10, 1), "quarterly") == date(2026, 12, 31)
    # 闰年 2 月末日：2024Q1 → 2024-03-31
    assert fred_period_end(date(2024, 1, 1), "quarterly") == date(2024, 3, 31)


def test_fred_period_end_annual() -> None:
    """FRED 年度：年初 → 年末。"""
    assert fred_period_end(date(2024, 1, 1), "annual") == date(2024, 12, 31)
    assert fred_period_end(date(2026, 1, 1), "annual") == date(2026, 12, 31)


def test_fred_period_end_unknown_period_returns_input() -> None:
    """未知频率原样返回（日频序列不该被改写）。"""
    d = date(2026, 10, 21)
    assert fred_period_end(d, "daily") == d


def test_eurostat_period_end_labels() -> None:
    """Eurostat 期间标签 → 期末日期。"""
    assert eurostat_period_end("2026-Q2") == date(2026, 6, 30)
    assert eurostat_period_end("2026-Q1") == date(2026, 3, 31)
    assert eurostat_period_end("2026-Q4") == date(2026, 12, 31)
    assert eurostat_period_end("2024") == date(2024, 12, 31)


def test_eurostat_period_end_invalid_returns_none() -> None:
    """解析不了 → None（不能猜一个日期出来）。"""
    assert eurostat_period_end("") is None
    assert eurostat_period_end("2026-Q5") is None
    assert eurostat_period_end("nonsense") is None
    # Date.parse('2026-Q2') 是 NaN —— 这就是必须自己换算的原因
    assert eurostat_period_end("2026-Q2") is not None


def test_parse_eurostat_gov_debt_filters_dimensions() -> None:
    """只取 na_item=GD / sector=S13 / unit=PC_GDP 三者同时成立的记录。"""
    payload = {
        "id": ["freq", "na_item", "sector", "unit", "geo", "time"],
        "size": [1, 2, 2, 2, 1, 2],
        "dimension": {
            "freq": {"category": {"index": {"Q": 0}}},
            "na_item": {"category": {"index": {"GD": 0, "FA": 1}}},
            "sector": {"category": {"index": {"S13": 0, "S11": 1}}},
            "unit": {"category": {"index": {"PC_GDP": 0, "RT": 1}}},
            "geo": {"category": {"index": {"EU27_2020": 0}}},
            "time": {"category": {"index": ["2026-Q1", "2026-Q2"]}},
        },
        # 扁平下标：size = [1,2,2,2,1,2] ⇒ 最后一维最快
        "value": {
            "0": 81.5,  # GD/S13/PC_GDP/2026-Q1
            "1": 82.9,  # GD/S13/PC_GDP/2026-Q2
            "2": 30.0,  # FA/S13/PC_GDP/2026-Q1
            "3": 31.0,  # FA/S13/PC_GDP/2026-Q2
            "4": 40.0,  # GD/S11/PC_GDP/2026-Q1
            "5": 41.0,  # GD/S11/PC_GDP/2026-Q2
            "6": 5.0,  # GD/S13/RT/2026-Q1
            "7": 6.0,  # GD/S13/RT/2026-Q2
        },
    }
    parsed = parse_eurostat_gov_debt(json.dumps(payload))
    assert parsed == [("2026-Q1", 81.5), ("2026-Q2", 82.9)]


def test_parse_eurostat_gov_debt_skips_null_values() -> None:
    """Eurostat 用 ``status`` 标注暂定/预估，值为 null 的记录要跳过（不前值填充）。"""
    payload = {
        "id": ["na_item", "sector", "unit", "time"],
        "size": [1, 1, 1, 2],
        "dimension": {
            "na_item": {"category": {"index": {"GD": 0}}},
            "sector": {"category": {"index": {"S13": 0}}},
            "unit": {"category": {"index": {"PC_GDP": 0}}},
            "time": {"category": {"index": ["2026-Q1", "2026-Q2"]}},
        },
        "value": {"0": 81.5, "1": None},
        "status": {"1": "e"},
    }
    parsed = parse_eurostat_gov_debt(json.dumps(payload))
    assert parsed == [("2026-Q1", 81.5)]


def test_parse_eurostat_gov_debt_invalid_json_returns_empty() -> None:
    """坏 JSON → 空列表（调用方回退静态兜底，不是抛异常）。"""
    assert parse_eurostat_gov_debt("{not-json") == []


def test_fred_periodic_series_registry() -> None:
    """低频序列登记表：每条都要给足 lookback（30 天窗口对低频序列一条都取不到）。"""
    assert FRED_PERIODIC_SERIES["GFDEGDQ188S"] == ("us_gov_debt", 200, "quarterly")
    assert FRED_PERIODIC_SERIES["GGGDTACNA188N"] == ("cn_gov_debt", 900, "annual")
    for factor_key, lookback, period in FRED_PERIODIC_SERIES.values():
        assert lookback >= 180, factor_key
        assert period in ("quarterly", "annual"), factor_key


@pytest.mark.asyncio
async def test_fetch_fred_periodic_latest_normalizes_to_period_end(monkeypatch) -> None:
    """低频 FRED 取数：期初观测日 → 期末日期。"""
    from app.repositories import macro_sources

    clear_macro_sources_cache()

    async def fake_fetch_text(url, timeout=15, user_agent=None):
        seen["url"] = url
        return "observation_date,GFDEGDQ188S\n2025-10-01,120.5\n2026-01-01,122.6\n"

    seen: dict = {}
    monkeypatch.setattr(macro_sources, "_fetch_text", fake_fetch_text)

    result = await macro_sources.fetch_fred_periodic_latest(
        "GFDEGDQ188S",
        base_url="https://x/?id={series_id}",
        lookback_days=200,
        period="quarterly",
    )
    assert result == (122.6, date(2026, 3, 31))
    clear_macro_sources_cache()


@pytest.mark.asyncio
async def test_fetch_eurostat_gov_debt_returns_value_and_period_end(monkeypatch) -> None:
    """Eurostat 取数 → (值, 期末日期)。"""
    from app.repositories import macro_sources

    clear_macro_sources_cache()

    async def fake_fetch_text(url, timeout=15, user_agent=None):
        seen["url"] = url
        seen["user_agent"] = user_agent
        return json.dumps(
            {
                "id": ["na_item", "sector", "unit", "time"],
                "size": [1, 1, 1, 1],
                "dimension": {
                    "na_item": {"category": {"index": {"GD": 0}}},
                    "sector": {"category": {"index": {"S13": 0}}},
                    "unit": {"category": {"index": {"PC_GDP": 0}}},
                    "time": {"category": {"index": ["2026-Q2"]}},
                },
                "value": {"0": 82.9},
            }
        )

    seen: dict = {}
    monkeypatch.setattr(macro_sources, "_fetch_text", fake_fetch_text)

    result = await macro_sources.fetch_eurostat_gov_debt(base_url="https://x/{dataset}")
    assert result == (82.9, date(2026, 6, 30))
    assert "GOV_10Q_GGDEBT" in seen["url"]
    assert "EU27_2020" in seen["url"]
    clear_macro_sources_cache()
