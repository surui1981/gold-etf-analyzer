"""readhub fetcher 单测（V0.102）

覆盖：
- 正常返回：1 条 → 1 条 normalize（字段全保）
- 200 + 空 data：抛 ``ReadhubFetchError``（service 兜底）
- 4xx：抛 ``ReadhubFetchError``（不可重试）
- 5xx：重试 1 次后抛 ``ReadhubFetchError``
- timeout：重试 1 次后抛 ``ReadhubFetchError``（httpx.TimeoutException）
- normalize 字段缺关键字段（id/title/url/publishDate/siteName）→ 丢弃该条
- 缓存：5min TTL 命中 / 强制重抓
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from app.repositories import readhub_fetcher as rh


# ──────────────── 共用 fixture ────────────────


@pytest.fixture(autouse=True)
def _clear_rh_cache():
    """每个用例前后清空 readhub fetcher 进程内缓存（防 TTL 污染）。"""
    with rh._CACHE_LOCK:
        rh._CACHE.clear()
    yield
    with rh._CACHE_LOCK:
        rh._CACHE.clear()


def _patch_http(monkeypatch: pytest.MonkeyPatch, response_or_callable):
    """把 ``httpx.AsyncClient.get`` 替换为返回 response_or_callable。

    response_or_callable 可以是：
    - httpx.Response：所有调用都返回该响应
    - callable(client) → await response：每个调用走 callback
    """
    if isinstance(response_or_callable, httpx.Response):
        async def _fake_get(self, url, **kwargs):  # noqa: ANN001
            return response_or_callable
    else:
        async def _fake_get(self, url, **kwargs):  # noqa: ANN001
            return await response_or_callable(self, url, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)


def _make_response(status: int, body: Any) -> httpx.Response:
    """构造 httpx.Response（绕过真实网络）。"""
    import json
    text = json.dumps(body, ensure_ascii=False) if not isinstance(body, str) else body
    return httpx.Response(status_code=status, text=text)


def _sample_raw() -> list[dict]:
    """1 条 readhub raw 数据（schema 真实样本）。"""
    return [{
        "id": 263197,
        "title": "美联储官员暗示 11 月暂停加息",
        "summary": "美联储内部讨论 11 月暂停加息的可能，理由是通胀回落速度超预期。",
        "url": "https://wallstreetcn.com/articles/9999999",
        "mobileUrl": "https://m.wallstreetcn.com/articles/9999999",
        "siteName": "华尔街见闻",
        "language": "zh-cn",
        "authorName": "张三",
        "publishDate": "2026-10-19T08:30:00+08:00",
    }]


# ──────────────── normalize ────────────────


class TestNormalize:
    """``_normalize`` 字段映射与缺字段丢弃。"""

    def test_normal_full(self) -> None:
        """全字段都填 → 全字段都保留。"""
        raw = _sample_raw()[0]
        out = rh._normalize(raw)
        assert out is not None
        assert out["external_id"] == 263197
        assert out["title"] == "美联储官员暗示 11 月暂停加息"
        assert out["summary"].startswith("美联储内部")
        assert out["url"].startswith("https://")
        assert out["mobile_url"] is not None
        assert out["site_name"] == "华尔街见闻"
        assert out["language"] == "zh-cn"
        assert out["author_name"] == "张三"
        assert out["publish_date"] == datetime(2026, 10, 19, 0, 30, tzinfo=timezone.utc)

    def test_drop_missing_id(self) -> None:
        """id 缺失 → 整条丢弃。"""
        raw = _sample_raw()[0]
        raw["id"] = None
        assert rh._normalize(raw) is None

    def test_drop_missing_title(self) -> None:
        """title 空字符串 → 整条丢弃。"""
        raw = _sample_raw()[0]
        raw["title"] = "   "
        assert rh._normalize(raw) is None

    def test_drop_missing_url(self) -> None:
        """url 缺失 → 整条丢弃。"""
        raw = _sample_raw()[0]
        raw["url"] = ""
        assert rh._normalize(raw) is None

    def test_drop_missing_publish_date(self) -> None:
        """publishDate 解析失败 → 整条丢弃。"""
        raw = _sample_raw()[0]
        raw["publishDate"] = "not-a-date"
        assert rh._normalize(raw) is None

    def test_drop_missing_site_name(self) -> None:
        """siteName 缺失 → 整条丢弃。"""
        raw = _sample_raw()[0]
        raw["siteName"] = ""
        assert rh._normalize(raw) is None

    def test_optional_fields_normalized(self) -> None:
        """mobileUrl / authorName / language 全 None → 字段填 None（DB NULL 纪律）。"""
        raw = _sample_raw()[0]
        raw["mobileUrl"] = ""
        raw["authorName"] = ""
        raw["language"] = ""
        out = rh._normalize(raw)
        assert out is not None
        assert out["mobile_url"] is None
        assert out["author_name"] is None
        assert out["language"] is None


# ──────────────── parse_publish_date ────────────────


class TestParsePublishDate:
    """``_parse_publish_date`` ISO 8601 解析。"""

    def test_with_offset(self) -> None:
        """带 +08:00 offset → 转 UTC。"""
        dt = rh._parse_publish_date("2026-10-19T08:30:00+08:00")
        assert dt == datetime(2026, 10, 19, 0, 30, tzinfo=timezone.utc)

    def test_with_z_suffix(self) -> None:
        """Z 后缀（UTC）→ 直接转。"""
        dt = rh._parse_publish_date("2026-10-19T00:30:00Z")
        assert dt == datetime(2026, 10, 19, 0, 30, tzinfo=timezone.utc)

    def test_invalid_returns_none(self) -> None:
        """非法字符串 → None。"""
        assert rh._parse_publish_date("not-a-date") is None
        assert rh._parse_publish_date("") is None
        assert rh._parse_publish_date(None) is None

    def test_naive_assume_utc(self) -> None:
        """无 tz → 视为 UTC（容错）。"""
        dt = rh._parse_publish_date("2026-10-19T00:30:00")
        assert dt is not None
        assert dt.tzinfo is not None


# ──────────────── fetch_readhub_feed ────────────────


class TestFetchReadhubFeed:
    """端到端 httpx mock → fetch_readhub_feed。"""

    async def test_normal_200(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """200 + 1 条 → 1 条 normalize 返回。"""
        resp = _make_response(200, {"data": _sample_raw()})
        _patch_http(monkeypatch, resp)
        out = await rh.fetch_readhub_feed(use_cache=False)
        assert len(out) == 1
        assert out[0]["external_id"] == 263197

    async def test_empty_data_returns_empty_tuple(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """200 + data=[] → 返回空 tuple（service 层 ``refresh()`` 兜底为软失败）。

        fetcher 不抛错：readhub 空 data 是合法 HTTP 200，service 用 ``ok=False +
        error='readhub returned empty payload'`` 走 V0.84 保留末次数据 UX。
        """
        resp = _make_response(200, {"data": []})
        _patch_http(monkeypatch, resp)
        out = await rh.fetch_readhub_feed(use_cache=False)
        assert out == ()

    async def test_4xx_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """4xx → 抛 ReadhubFetchError（不可重试）。"""
        resp = _make_response(403, "Forbidden")
        _patch_http(monkeypatch, resp)
        with pytest.raises(rh.ReadhubFetchError, match="HTTP 403"):
            await rh.fetch_readhub_feed(use_cache=False)

    async def test_5xx_retries_then_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """5xx → 重试 1 次（2 次调用）后仍失败 → 抛错。"""
        call_count = {"n": 0}

        async def _make_get(self, url, **kwargs):  # noqa: ANN001
            call_count["n"] += 1
            return _make_response(503, "Service Unavailable")

        monkeypatch.setattr(httpx.AsyncClient, "get", _make_get)
        with pytest.raises(rh.ReadhubFetchError, match="HTTP 503"):
            await rh.fetch_readhub_feed(use_cache=False)
        # _RETRY_BACKOFFS = (0.0, 1.5) → 首次 + 1 次重试 = 2 次
        assert call_count["n"] == 2

    async def test_timeout_retries_then_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """httpx.TimeoutException → 重试 1 次后抛 ReadhubFetchError。"""
        call_count = {"n": 0}

        async def _make_get(self, url, **kwargs):  # noqa: ANN001
            call_count["n"] += 1
            raise httpx.ConnectTimeout("connect timeout")

        monkeypatch.setattr(httpx.AsyncClient, "get", _make_get)
        with pytest.raises(rh.ReadhubFetchError, match="network error"):
            await rh.fetch_readhub_feed(use_cache=False)
        assert call_count["n"] == 2

    async def test_invalid_json_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """200 + 非法 JSON → 抛 ReadhubFetchError。"""
        resp = _make_response(200, "not json {")
        _patch_http(monkeypatch, resp)
        with pytest.raises(rh.ReadhubFetchError, match="response parse error"):
            await rh.fetch_readhub_feed(use_cache=False)

    async def test_data_not_list_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """200 + data=字符串（不是 list）→ 抛错。"""
        resp = _make_response(200, {"data": "oops"})
        _patch_http(monkeypatch, resp)
        with pytest.raises(rh.ReadhubFetchError, match="not list"):
            await rh.fetch_readhub_feed(use_cache=False)

    async def test_partial_drop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """1 完整 + 1 缺字段 → 只保留完整的 1 条。"""
        raw = _sample_raw()
        bad = _sample_raw()[0].copy()
        bad["id"] = None  # 触发 drop
        resp = _make_response(200, {"data": raw + [bad]})
        _patch_http(monkeypatch, resp)
        out = await rh.fetch_readhub_feed(use_cache=False)
        assert len(out) == 1

    async def test_cache_hit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """第一次抓完写缓存，第二次（use_cache=True）直接命中（不调 httpx）。"""
        call_count = {"n": 0}

        async def _make_get(self, url, **kwargs):  # noqa: ANN001
            call_count["n"] += 1
            return _make_response(200, {"data": _sample_raw()})

        monkeypatch.setattr(httpx.AsyncClient, "get", _make_get)
        # 第一次写入
        first = await rh.fetch_readhub_feed(use_cache=False)
        assert len(first) == 1
        assert call_count["n"] == 1
        # 第二次 cache hit（不调 httpx）
        second = await rh.fetch_readhub_feed(use_cache=True)
        assert second == first
        assert call_count["n"] == 1

    async def test_force_ignores_cache(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``force=True``（use_cache=False 第二次）→ 强制重抓。"""
        call_count = {"n": 0}

        async def _make_get(self, url, **kwargs):  # noqa: ANN001
            call_count["n"] += 1
            return _make_response(200, {"data": _sample_raw()})

        monkeypatch.setattr(httpx.AsyncClient, "get", _make_get)
        await rh.fetch_readhub_feed(use_cache=False)
        await rh.fetch_readhub_feed(use_cache=False)
        assert call_count["n"] == 2
