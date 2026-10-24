"""4 源新闻抓取器单测（V0.114.0）

覆盖
----
**各源 normalize 的实测坑**（这些坑都是 2026-10-22 真实打接口才发现的，
用真实响应形状做 fixture，不是照文档编的）：

- wallstcn：``title`` 空串（30 条里 22 条）→ 必须回退 ``content_text``；
  ``display_time`` 缺失 → 丢弃
- jin10：VIP 付费占位条（``data.lock=True`` + ``content=''``）→ 丢弃；
  ``content`` 含 HTML → 剥标签；``id`` 是 20 位数字串 → 转 int；
  ``time`` 不带时区 → 按 BJT 解释
- eastmoney：完全无 URL 字段 → ``url`` 恒 None；``code`` 是数字串 → 转 int；
  ``showTime`` 不带时区 → 按 BJT

**failover 链**：首个足量即止 / 首选挂→降级 / 量不足→降级（防 200 但空壳）/
全挂抛错 / 全部量不足也抛错。

**精度**：金十 id 超出 JS 安全整数范围 → ``js_safe_id`` 必须转字符串。

HTTP 一律 mock，不打真实网络。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest

from app.repositories import news_sources_fetcher as nsf
from app.schemas.news_feed import js_safe_id

BJT = timezone(timedelta(hours=8))


# ──────────────── 共用 fixture ────────────────


@pytest.fixture(autouse=True)
def _clear_cache():
    """每个用例前后清空 fetcher 进程内缓存（防 TTL 污染）。"""
    with nsf._CACHE_LOCK:
        nsf._CACHE.clear()
    yield
    with nsf._CACHE_LOCK:
        nsf._CACHE.clear()


def _make_response(status: int, body: Any) -> httpx.Response:
    text = json.dumps(body, ensure_ascii=False) if not isinstance(body, str) else body
    return httpx.Response(status_code=status, text=text)


def _patch_http(monkeypatch: pytest.MonkeyPatch, response):
    async def _fake_get(self, url, **kwargs):
        return response

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)


def _wallstcn_item(**over) -> dict:
    """一条真实形状的华尔街见闻快讯（实测响应 items[] 的字段子集）。"""
    base = {
        "id": 3182985,
        "title": "",
        "content_text": "纳斯达克指数收涨1%，黄金ETF资金净流入创新高。",
        "uri": "https://wallstreetcn.com/livenews/3182985",
        "display_time": 1792618346,  # == 2026-10-22 05:32:26 BJT
        "author": {"display_name": "华尔街见闻"},
    }
    base.update(over)
    return base


def _jin10_item(**over) -> dict:
    base = {
        "id": "20261022052906788800",
        "time": "2026-10-22 05:29:06",
        "important": 0,
        "data": {"content": "美联储官员暗示 11 月暂停加息，黄金ETF资金净流入创新高。", "title": ""},
    }
    base.update(over)
    return base


def _eastmoney_item(**over) -> dict:
    base = {
        "code": "202610223903075155",
        "showTime": "2026-10-22 05:25:30",
        "title": "特斯拉转向AI与机器人赛道 三季度支出大幅低于市场预期",
        "summary": "特斯拉第三财季总资本支出达47.3亿美元，远低于华尔街一致预期。",
    }
    base.update(over)
    return base


# ──────────────── wallstcn normalize ────────────────


class TestNormalizeWallstcn:
    def test_empty_title_falls_back_to_content_text(self) -> None:
        """实测 30 条里 22 条 title 为空 —— 必须回退，否则首选源丢 73% 条目。"""
        rec = nsf._normalize_wallstcn(_wallstcn_item(title=""))
        assert rec is not None
        assert rec["title"].startswith("纳斯达克指数")
        assert rec["summary"].startswith("纳斯达克指数")

    def test_title_present_is_kept_and_body_goes_to_summary(self) -> None:
        rec = nsf._normalize_wallstcn(_wallstcn_item(title="自定义标题"))
        assert rec is not None
        assert rec["title"] == "自定义标题"
        assert rec["summary"].startswith("纳斯达克指数")

    def test_uri_becomes_url_and_source_tagged(self) -> None:
        rec = nsf._normalize_wallstcn(_wallstcn_item())
        assert rec is not None
        assert rec["url"] == "https://wallstreetcn.com/livenews/3182985"
        assert rec["source"] == "wallstcn"
        assert rec["site_name"] == "华尔街见闻"

    def test_missing_display_time_dropped(self) -> None:
        item = _wallstcn_item()
        del item["display_time"]
        assert nsf._normalize_wallstcn(item) is None

    def test_non_int_id_dropped(self) -> None:
        assert nsf._normalize_wallstcn(_wallstcn_item(id="3182985")) is None

    def test_empty_title_and_body_dropped(self) -> None:
        assert nsf._normalize_wallstcn(_wallstcn_item(title="", content_text="")) is None


# ──────────────── jin10 normalize ────────────────


class TestNormalizeJin10:
    def test_vip_locked_placeholder_dropped(self) -> None:
        """实测 21 条里 2 条是 PLUS 付费占位（lock=True + content 空）。"""
        item = _jin10_item(data={"content": "", "lock": True, "vip_desc": "PLUS专享快讯"})
        assert nsf._normalize_jin10(item) is None

    def test_empty_content_dropped(self) -> None:
        assert nsf._normalize_jin10(_jin10_item(data={"content": "   "})) is None

    def test_html_stripped_from_content(self) -> None:
        """实测 content 含 <br/> / <b> / <span class=...>，不剥会渲染出字面标签。"""
        raw = "【俄乌跟踪】<br/><b>冲突情况：</b><span class='x'>进展</span>"
        rec = nsf._normalize_jin10(_jin10_item(data={"content": raw}))
        assert rec is not None
        assert "<" not in rec["title"]
        assert "<b>" not in rec["summary"]
        assert "冲突情况" in rec["summary"]
        assert "进展" in rec["summary"]

    def test_id_string_converted_to_int(self) -> None:
        rec = nsf._normalize_jin10(_jin10_item())
        assert rec is not None
        assert rec["external_id"] == 20261022052906788800
        assert isinstance(rec["external_id"], int)

    def test_time_without_tz_interpreted_as_bjt(self) -> None:
        """金十时间串不带时区 → 按 BJT。差 8 小时就是整天的错位。"""
        rec = nsf._normalize_jin10(_jin10_item(time="2026-10-22 05:29:06"))
        assert rec is not None
        assert rec["publish_date"] == datetime(2026, 10, 22, 5, 29, 6, tzinfo=BJT)

    def test_url_is_none_no_link_field(self) -> None:
        rec = nsf._normalize_jin10(_jin10_item())
        assert rec is not None
        assert rec["url"] is None

    def test_non_numeric_id_dropped(self) -> None:
        assert nsf._normalize_jin10(_jin10_item(id="abc")) is None

    def test_unparsable_time_dropped(self) -> None:
        assert nsf._normalize_jin10(_jin10_item(time="not-a-time")) is None


# ──────────────── eastmoney normalize ────────────────


class TestNormalizeEastmoney:
    def test_code_string_converted_to_int(self) -> None:
        rec = nsf._normalize_eastmoney(_eastmoney_item())
        assert rec is not None
        assert rec["external_id"] == 202610223903075155
        assert rec["source"] == "eastmoney"

    def test_url_always_none(self) -> None:
        """实测 0/20 条有任何 URL 字段 —— url 恒 None，UI 渲染不可点纯文本。"""
        rec = nsf._normalize_eastmoney(_eastmoney_item())
        assert rec is not None
        assert rec["url"] is None

    def test_show_time_without_tz_interpreted_as_bjt(self) -> None:
        rec = nsf._normalize_eastmoney(_eastmoney_item())
        assert rec is not None
        assert rec["publish_date"] == datetime(2026, 10, 22, 5, 25, 30, tzinfo=BJT)

    def test_missing_title_dropped(self) -> None:
        assert nsf._normalize_eastmoney(_eastmoney_item(title="")) is None

    def test_summary_falls_back_to_title(self) -> None:
        rec = nsf._normalize_eastmoney(_eastmoney_item(summary=""))
        assert rec is not None
        assert rec["summary"] == rec["title"]


# ──────────────── 共用工具 ────────────────


class TestHelpers:
    @pytest.mark.parametrize(
        ("raw", "want"),
        [
            ("<br/>", ""),
            ("甲<br/>乙", "甲 乙"),
            ("<b>粗体</b>", "粗体"),
            ("a &amp; b", "a & b"),
            ("<b>a</b><b>b</b>", "ab"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_strip_html(self, raw: str | None, want: str) -> None:
        assert nsf._strip_html(raw) == want

    @pytest.mark.parametrize(
        ("raw", "want"),
        [
            ("2026-10-22 05:29:06", datetime(2026, 10, 22, 5, 29, 6, tzinfo=BJT)),
            ("2026-10-22T05:29:06", datetime(2026, 10, 22, 5, 29, 6, tzinfo=BJT)),
            ("bad", None),
            ("", None),
            (None, None),
        ],
    )
    def test_parse_bjt(self, raw: str | None, want: datetime | None) -> None:
        assert nsf._parse_bjt(raw) == want

    def test_jin10_and_wallstcn_timestamps_agree(self) -> None:
        """两源同一事件的时间必须落在同一时刻附近，否则时间线会乱序。"""
        wall = nsf._normalize_wallstcn(_wallstcn_item())
        # 金十同一事件的时刻换算成 unix 后对比（容差 1h：两端抓取必然有先后）
        got = nsf._parse_bjt("2026-10-22 05:29:06")
        assert wall is not None and got is not None
        assert abs((wall["publish_date"] - got).total_seconds()) < 3600


# ──────────────── 精度：JS 安全整数 ────────────────


class TestJsSafeId:
    def test_small_ids_stay_numbers(self) -> None:
        """不破坏既有契约：readhub / 华尔街见闻的 id 仍是 JSON 数字。"""
        assert js_safe_id(1001) == 1001
        assert isinstance(js_safe_id(1001), int)

    @pytest.mark.parametrize("value", [2**53 - 1, 1001, 0, -1001])
    def test_within_safe_range_stays_int(self, value: int) -> None:
        assert isinstance(js_safe_id(value), int)

    @pytest.mark.parametrize("value", [2**53, 20261022052906788800, -(2**53) - 1])
    def test_beyond_safe_range_becomes_str(self, value: int) -> None:
        """金十 id ≈2.0e19，超出 JS MAX_SAFE_INTEGER 2249 倍，必须转字符串。

        不转的话 JSON.parse 会静默舍入成 ...7000，页面再 POST 回去就收藏到
        一个不存在的行 —— 不报错、不显形、只在真实数据上发生。
        """
        assert js_safe_id(value) == str(value)
        assert isinstance(js_safe_id(value), str)

    def test_roundtrip_through_json_is_lossless(self) -> None:
        original = 20261022052906788800
        out = json.loads(json.dumps({"v": js_safe_id(original)}))["v"]
        assert str(out) == str(original)


# ──────────────── HTTP 层 ────────────────


class TestFetchFunctions:
    async def test_wallstcn_fetch_normalizes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_http(
            monkeypatch,
            _make_response(200, {"code": 0, "data": {"items": [_wallstcn_item()]}}),
        )
        out = await nsf.fetch_wallstcn_feed(use_cache=False)
        assert len(out) == 1
        assert out[0]["source"] == "wallstcn"

    async def test_jin10_fetch_sends_required_headers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """缺 x-app-id / x-version 会被服务端拒 —— 头必须带上。"""
        seen: dict = {}

        async def _fake_get(self, url, **kwargs):
            seen.update(kwargs.get("headers") or {})
            return _make_response(200, {"status": 200, "data": [_jin10_item()]})

        monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
        await nsf.fetch_jin10_feed(use_cache=False)
        assert seen.get("x-app-id") == "bVBF4FyRTn5NJF5n"
        assert seen.get("x-version") == "1.0.0"

    async def test_jin10_business_error_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_http(monkeypatch, _make_response(200, {"status": 403, "message": "denied"}))
        with pytest.raises(nsf.NewsSourceError, match="business status"):
            await nsf.fetch_jin10_feed(use_cache=False)

    async def test_eastmoney_success_code_is_string_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """实测 code 是**字符串** "1"。用 `!= 1` 判会把成功判成失败（踩过）。"""
        _patch_http(
            monkeypatch,
            _make_response(200, {"code": "1", "data": {"fastNewsList": [_eastmoney_item()]}}),
        )
        out = await nsf.fetch_eastmoney_feed(use_cache=False)
        assert len(out) == 1

    async def test_eastmoney_missing_sortend_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """缺 sortEnd 时服务端返回 code="0" + data=null —— 必须当失败，不能当空。"""
        _patch_http(
            monkeypatch,
            _make_response(
                200,
                {
                    "code": "0",
                    "message": "Required String parameter 'sortEnd' is not present",
                    "data": None,
                },
            ),
        )
        with pytest.raises(nsf.NewsSourceError, match="business code"):
            await nsf.fetch_eastmoney_feed(use_cache=False)

    async def test_eastmoney_sends_sortend_and_fastcolumn(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """这两个参数缺任一都会静默拿到 data=null（2026-10 实测新增校验）。"""
        seen: dict = {}

        async def _fake_get(self, url, **kwargs):
            seen.update(kwargs.get("params") or {})
            return _make_response(200, {"code": "1", "data": {"fastNewsList": [_eastmoney_item()]}})

        monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
        await nsf.fetch_eastmoney_feed(use_cache=False)
        assert "sortEnd" in seen
        assert "fastColumn" in seen

    async def test_cache_hit_avoids_http(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = {"n": 0}

        async def _fake_get(self, url, **kwargs):
            calls["n"] += 1
            return _make_response(200, {"code": 0, "data": {"items": [_wallstcn_item()]}})

        monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
        await nsf.fetch_wallstcn_feed(use_cache=True)
        await nsf.fetch_wallstcn_feed(use_cache=True)
        assert calls["n"] == 1

    async def test_force_bypasses_cache(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = {"n": 0}

        async def _fake_get(self, url, **kwargs):
            calls["n"] += 1
            return _make_response(200, {"code": 0, "data": {"items": [_wallstcn_item()]}})

        monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
        await nsf.fetch_wallstcn_feed(use_cache=True)
        await nsf.fetch_wallstcn_feed(use_cache=False)
        assert calls["n"] == 2


# ──────────────── failover 链 ────────────────


@pytest.fixture
def _chain(monkeypatch: pytest.MonkeyPatch):
    """临时替换模块级 SOURCES，返回 setter。"""
    original = nsf.SOURCES

    def _set(new_sources):
        monkeypatch.setattr(nsf, "SOURCES", tuple(new_sources))
        return tuple(new_sources)

    yield _set
    monkeypatch.setattr(nsf, "SOURCES", original)


def _ok_fetch(n: int):
    async def _f(**_kwargs):
        return tuple({"external_id": i, "source": "x"} for i in range(n))

    return _f


def _boom_fetch(msg: str = "注入故障"):
    async def _f(**_kwargs):
        raise nsf.NewsSourceError(msg)

    return _f


class TestFailover:
    async def test_first_source_wins(self, _chain) -> None:
        _chain([nsf.NewsSource("a", _ok_fetch(20)), nsf.NewsSource("b", _boom_fetch())])
        result = await nsf.fetch_news_feed(use_cache=False)
        assert result.source == "a"
        assert len(result.items) == 20

    async def test_falls_through_when_source_raises(self, _chain) -> None:
        _chain([nsf.NewsSource("a", _boom_fetch()), nsf.NewsSource("b", _ok_fetch(15))])
        result = await nsf.fetch_news_feed(use_cache=False)
        assert result.source == "b"

    async def test_falls_through_when_source_too_thin(self, _chain) -> None:
        """量不足必须降级 —— 否则「HTTP 200 但返回空壳」会静默当成成功，
        failover 形同虚设（readhub 有 pageSize=50 只返 20 的前科）。"""
        _chain([nsf.NewsSource("a", _ok_fetch(1)), nsf.NewsSource("b", _ok_fetch(12))])
        result = await nsf.fetch_news_feed(use_cache=False)
        assert result.source == "b"

    async def test_raises_when_all_fail(self, _chain) -> None:
        _chain(
            [nsf.NewsSource("a", _boom_fetch("挂了A")), nsf.NewsSource("b", _boom_fetch("挂了B"))]
        )
        with pytest.raises(nsf.NewsSourceError) as ei:
            await nsf.fetch_news_feed(use_cache=False)
        # 错误串必须含每源原因，否则日志里看不出是哪个源先挂的
        assert "挂了A" in str(ei.value)
        assert "挂了B" in str(ei.value)

    async def test_raises_when_all_too_thin(self, _chain) -> None:
        """全部量不足也必须抛错，不能返回半吊子数据。"""
        _chain([nsf.NewsSource("a", _ok_fetch(1)), nsf.NewsSource("b", _ok_fetch(0))])
        with pytest.raises(nsf.NewsSourceError, match="too thin"):
            await nsf.fetch_news_feed(use_cache=False)

    async def test_unexpected_exception_does_not_break_chain(self, _chain) -> None:
        async def _weird(**_kwargs):
            raise ValueError("完全意料之外的异常")

        _chain([nsf.NewsSource("a", _weird), nsf.NewsSource("b", _ok_fetch(11))])
        result = await nsf.fetch_news_feed(use_cache=False)
        assert result.source == "b"

    def test_chain_order_is_wallstcn_first(self) -> None:
        """首选源顺序是产品决策：华尔街见闻有 URL、条数最多，排第一。"""
        assert [s.key for s in nsf.SOURCES] == [
            "wallstcn",
            "jin10",
            "eastmoney",
            "readhub",
        ]

    def test_min_items_below_measured_yields(self) -> None:
        """实测各源 classify 后产量 16-21；阈值必须显著低于它们才算真 failover。"""
        assert nsf.MIN_ITEMS < 16
