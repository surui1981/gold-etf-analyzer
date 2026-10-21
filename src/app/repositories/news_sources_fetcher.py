"""新闻多源抓取：4 源链式 failover（V0.114.0）

背景
----
V0.102 至今只有 readhub 一个源 —— **单点无冗余**。本轮实测中 readhub 已超时
过一次，不是理论风险。V0.114.0 接入 3 个新源做链式 failover：任一源挂了，
下一个顶上。

数据源（字段形状均为 2026-10-22 实测确认，非文档推断）
-------------------------------------------------------
1. ★ 华尔街见闻 ``https://api-one.wallstcn.com/apiv1/content/lives``
   - ``?channel=global-channel&limit=N``（``channel`` 实测**确实**在过滤：
     各频道返回的 id 集合不同，不是摆设参数）
   - 匿名可访问，无需鉴权；响应 ``{"data": {"items": [...], "next_cursor": ...}}``
   - ⚠ **30 条里 22 条 ``title`` 是空串** —— 快讯只有正文 ``content_text``
     （纯文本，无 HTML）。标题必须从正文截取，否则 73% 的条目会因「无标题」被丢弃
   - ``uri`` 给原文链接；``display_time`` 是 unix 秒（int）

2. 金十数据 ``https://flash-api.jin10.com/get_flash_list``
   - ``?max_time=&channel=-8200&vip=1`` + 必须带 header
     ``x-app-id: bVBF4FyRTn5NJF5n`` / ``x-version: 1.0.0``
   - ⚠ ``max_time`` 的值是 ``YYYY-MM-DD HH:MM:SS``，**含空格** → 必须
     ``urllib.parse.urlencode``，否则 httpx 抛
     ``InvalidURL: URL can't contain control characters``
   - ``id`` 是 **20 位数字字符串**（``20261022052115590800``）→ 超出 int32，
     所以 ``news_feed_items.external_id`` 必须 BigInteger（本次迁移已改）
   - ``time`` 是 ``"YYYY-MM-DD HH:MM:SS"``，**不带时区** → 按 BJT 解释
     （金十是国内源，实测发布时间与 wallstcn 同一时刻）
   - ⚠ 约 **2/21 条是 PLUS 付费占位**：``data.lock=True`` + ``content=''``
     + ``voice_status='locked'``。这些条目**零信息量**，必须丢 —— 否则入库后
     是一堆空标题的空卡片
   - ⚠ ``data.content`` **可能含 HTML**（实测有 ``<br/>`` / ``<b>`` /
     ``<span class=...>``），入库前必须剥标签
   - ``data.title`` 实测 20/20 全空；``data.source_link`` 字段存在但实测恒为 None
   - **无 URL** ⇒ 卡片不可点（V0.77.1 不给假 affordance）

3. 东方财富 ``https://np-listapi.eastmoney.com/comm/web/getFastNewsList``
   - ⚠ **必须同时传 ``fastColumn`` 和 ``sortEnd``**，缺任一都会返回
     ``{"code":"0","message":"Required String parameter 'sortEnd' is not present",
     "data":null}``（2026-10-22 实测；这是近期新增的服务端校验）
   - ⚠ **成功码是 ``1`` 不是 ``0``，且是字符串** ``{"code":"1","message":"success"}``
     —— 用 `!= 1` 判会把成功判成失败（首次实跑即踩）
   - ``data.fastNewsList[]``；``code`` 是 18 位数字串（BigInteger 装得下）
   - ``title`` / ``summary`` 齐全；**完全没有任何 URL 字段**（实测 0/20）
   - ``showTime`` 同金十：``"YYYY-MM-DD HH:MM:SS"``，不带时区 → BJT

4. readhub（兜底，唯一保留在原文件不动）
   - 唯一提供 readhub 独占站点（格隆汇 7 / 财联社 2 / 同花顺财经 / techradar）
     的源，与 wallstcn 标题重合仅 2 条 ⇒ 是**真正独立的第 4 源**而非重复

failover 策略
------------
链式：wallstcn ★ → jin10 → eastmoney → readhub，**首个返回 ≥``MIN_ITEMS``
（10）条的源即返回**，不再往下试。

阈值取 10 的依据（实测 classify 后各源产量：wallstcn 20 / jin10 20 /
eastmoney 23）：10 远低于任一健康源的产量，但足以识别「HTTP 200 但返回空壳」
这类降级响应 —— 实测中 readhub 有 ``pageSize=50`` 却只返回 20 的前科，
不设阈值的话空壳响应会静默当成成功，failover 形同虚设。

为什么不做跨源内容去重：实测 wallstcn 与 readhub 标题重合仅 2 条，
去重的误杀风险远大于收益。
"""

from __future__ import annotations

import asyncio
import html as html_lib
import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, NamedTuple

import httpx

from app.repositories.news_classifier import classify
from app.repositories.readhub_fetcher import (
    SITE_BLOCKLIST,
    ReadhubFetchError,
    fetch_readhub_feed,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ────────────── 常量 ──────────────

_BJT = timezone(timedelta(hours=8))

_HTTP_TIMEOUT_SECONDS = 30.0
_RETRY_BACKOFFS: tuple[float, ...] = (0.0, 1.5)
_FETCHER_CACHE_TTL = 300  # 5 分钟（与 readhub_fetcher 一致，避免 scheduler + 手动 refresh 撞车）

# failover 阈值：实测任一健康源 classify 后 ≥20 条，10 足以识别「200 但空壳」
MIN_ITEMS = 10

_WALLSTCN_URL = "https://api-one.wallstcn.com/apiv1/content/lives"
_JIN10_URL = "https://flash-api.jin10.com/get_flash_list"
_EASTMONEY_URL = "https://np-listapi.eastmoney.com/comm/web/getFastNewsList"

# 各源的展示名 → 同时写入 site_name（参与关键词分类的站名兜底）
_SITE_NAMES = {
    "wallstcn": "华尔街见闻",
    "jin10": "金十数据",
    "eastmoney": "东方财富快讯",
    "readhub": "readhub",
}

_UA = "gold-etf-analyzer/V0.114.0"

# HTML 标签：先按块级标签补空格，再删其余标签，避免 <b>a</b><b>b</b> → "ab"
_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_TAG_RE = re.compile(r"<\s*br\s*/?\s*>|<\s*/\s*(?:p|div|li|tr)\s*>", re.IGNORECASE)
_WS_RE = re.compile(r"[ \t　]+")


class NewsSourceError(RuntimeError):
    """全部新闻源都失败（网络 / HTTP / 解析 / 业务码非成功）。

    由 ``fetch_news_feed`` 在**所有**源都拿不到足量数据时抛出；service 层捕获后
    走「保留末次数据」UX（V0.84），**不**让 500 冒到用户可见路径。
    """


class NewsFetchResult(NamedTuple):
    """failover 的产出：条目 + 哪个源赢了。

    ``source`` 单独返回（而不是让调用方从 ``items[0]["source"]`` 反推），
    是为了让 refresh 响应能显示「上次数据来自华尔街见闻」—— failover 是否
    真的在工作，是需要能被观测的。
    """

    items: tuple[dict, ...]
    source: str


# ────────────── 共享 HTTP / 缓存 ──────────────

_CACHE: dict[tuple, tuple[float, tuple[dict, ...]]] = {}
_CACHE_LOCK = threading.Lock()


def _cache_get(key: tuple) -> tuple[dict, ...] | None:
    with _CACHE_LOCK:
        item = _CACHE.get(key)
    if item is not None and time.time() - item[0] < _FETCHER_CACHE_TTL:
        return item[1]
    return None


def _cache_set(key: tuple, value: tuple[dict, ...]) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (time.time(), value)


async def _fetch_json(
    url: str,
    *,
    source: str,
    params: dict | None = None,
    headers: dict | None = None,
) -> Any:
    """GET + 解析 JSON；5xx / 429 / 网络错误按 ``_RETRY_BACKOFFS`` 重试。

    4xx 业务错误（含「缺必填参数」类 200-with-error-body）直接抛，不重试 ——
    参数错了重试多少次都一样，重试只会把 failover 拖慢。

    Raises:
        NewsSourceError: 网络失败 / HTTP 非 2xx / JSON 解析失败
    """
    last_exc: Exception | None = None
    for attempt, backoff in enumerate(_RETRY_BACKOFFS):
        if backoff:
            await asyncio.sleep(backoff)
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
                resp = await client.get(
                    url,
                    params=params,
                    headers={"User-Agent": _UA, "Accept": "application/json", **(headers or {})},
                )
            if resp.status_code == 200:
                try:
                    return resp.json()
                except (json.JSONDecodeError, ValueError) as exc:
                    raise NewsSourceError(
                        f"{source} response parse error: {exc}; body={resp.text[:200]!r}"
                    ) from exc
            if 500 <= resp.status_code < 600 or resp.status_code == 429:
                last_exc = NewsSourceError(f"{source} HTTP {resp.status_code}: {resp.text[:200]}")
                logger.warning("%s attempt %d: HTTP %s", source, attempt, resp.status_code)
                continue
            raise NewsSourceError(f"{source} HTTP {resp.status_code}: {resp.text[:200]}")
        except NewsSourceError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            last_exc = NewsSourceError(f"{source} network error: {exc}")
            logger.warning("%s attempt %d network error: %s", source, attempt, exc)
            continue
    raise last_exc if last_exc else NewsSourceError(f"{source} fetch failed (unknown)")


def _strip_html(raw: str) -> str:
    """剥 HTML 标签 + 反转义 + 压空白（金十 content 实测含 ``<br/>`` 等标签）。"""
    if not raw:
        return ""
    text = _BLOCK_TAG_RE.sub(" ", raw)
    text = _TAG_RE.sub("", text)
    text = html_lib.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def _parse_bjt(raw: str | None) -> datetime | None:
    """``"2026-10-22 05:29:06"`` → 带 BJT tzinfo 的 datetime。

    ⚠ 金十 / 东财的时间串**不带时区**。按 BJT 解释（两者都是国内源，实测
    发布时刻与同为国内源的 wallstcn 对齐）。解析失败 → None（保留 NULL 纪律，
    不猜默认时刻）。
    """
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw.strip(), fmt).replace(tzinfo=_BJT)
        except ValueError:
            continue
    return None


def _build(
    *,
    source: str,
    external_id: int,
    title: str,
    summary: str,
    url: str | None,
    site_name: str,
    publish_dt: datetime,
    language: str | None = "zh-cn",
    author_name: str | None = None,
    mobile_url: str | None = None,
) -> dict | None:
    """组装 NewsFeedItem 字段 dict + 分类 + 弃入判定。

    弃入条件（两条，各自的原因已实测确认）：
    - ``category == '其他'`` —— V0.107.1 起的既有纪律，4 类流不要噪声
    - ``site_name in SITE_BLOCKLIST`` —— V0.108.0 起的既有纪律

    Returns:
        完整 dict；被弃入则 None。
    """
    if site_name in SITE_BLOCKLIST:
        logger.debug("%s item dropped (site blacklisted): id=%s", source, external_id)
        return None
    category = classify(title, summary, site_name)
    if category == "其他":
        logger.debug("%s item dropped (category=其他): id=%s", source, external_id)
        return None
    return {
        "external_id": external_id,
        "source": source,
        "title": title,
        "summary": summary,
        "url": url,  # None = 来源没给链接（V0.77.1：UI 渲染成不可点纯文本）
        "mobile_url": mobile_url,
        "site_name": site_name[:64],
        "language": (language or "")[:8] or None,
        "author_name": (author_name or "")[:128] or None,
        "publish_date": publish_dt,
        "category": category,
        # fetched_at 走 SQL DEFAULT now()
    }


# ────────────── 源 1：华尔街见闻（★ 首选） ──────────────

_TITLE_SNIPPET_LEN = 60


def _normalize_wallstcn(raw: dict[str, Any]) -> dict | None:
    """华尔街见闻单条 → NewsFeedItem dict；缺关键字段则丢弃。

    ⚠ 核心：**``title`` 实测 30 条里 22 条为空串**（快讯只有正文）。必须回退到
    ``content_text`` —— 否则 73% 的条目会因「无标题」被丢，白白浪费首选源。
    """
    ext_id = raw.get("id")
    if not isinstance(ext_id, int):
        return None
    content = (raw.get("content_text") or "").strip()
    title = (raw.get("title") or "").strip()
    # 标题回退：正文首句（无句号截断到 60 字）。用标题时仍把全文放 summary
    if not title:
        title = content[:_TITLE_SNIPPET_LEN]
    if not title:
        logger.debug("wallstcn item dropped: id=%s 无 title 且无 content_text", ext_id)
        return None
    display_time = raw.get("display_time")
    pub_dt = (
        datetime.fromtimestamp(display_time, tz=timezone.utc)
        if isinstance(display_time, int)
        else None
    )
    if pub_dt is None:
        logger.debug("wallstcn item dropped: id=%s 无 display_time", ext_id)
        return None
    author = raw.get("author")
    author_name = (author or {}).get("display_name") if isinstance(author, dict) else None
    return _build(
        source="wallstcn",
        external_id=ext_id,
        title=title,
        summary=content,
        url=(raw.get("uri") or "").strip() or None,
        site_name=_SITE_NAMES["wallstcn"],
        publish_dt=pub_dt,
        author_name=author_name,
    )


async def fetch_wallstcn_feed(
    *, limit: int = 30, use_cache: bool = True
) -> tuple[dict, ...]:
    """抓华尔街见闻快讯（首选源）。

    Args:
        limit: 一次抓取条数（实测上限 100，30 够 cover 4h 周期）
        use_cache: True → 5min TTL 命中直接返回

    Raises:
        NewsSourceError: 网络失败 / HTTP 非 2xx / 解析失败 / ``items`` 非 list
    """
    key = ("wallstcn", limit)
    if use_cache:
        cached = _cache_get(key)
        if cached is not None:
            logger.debug("wallstcn fetcher cache HIT (limit=%d)", limit)
            return cached

    payload = await _fetch_json(
        _WALLSTCN_URL,
        source="wallstcn",
        params={"channel": "global-channel", "limit": limit},
    )
    items_raw = (payload or {}).get("data", {}).get("items") if isinstance(payload, dict) else None
    if not isinstance(items_raw, list):
        raise NewsSourceError(
            f"wallstcn response data.items not list: {type(items_raw).__name__}"
        )
    out = tuple(
        rec
        for rec in (_normalize_wallstcn(r) for r in items_raw if isinstance(r, dict))
        if rec is not None
    )
    _cache_set(key, out)
    logger.info("wallstcn fetched: %d raw → %d normalized", len(items_raw), len(out))
    return out


# ────────────── 源 2：金十数据 ──────────────


def _normalize_jin10(raw: dict[str, Any]) -> dict | None:
    """金十单条 → NewsFeedItem dict。

    ⚠ 两条实测坑：
    1. **VIP 付费占位条**：``data.lock=True`` + ``content=''`` +
       ``voice_status='locked'``（实测 21 条里 2 条）。零信息量，必须丢。
    2. **content 可能含 HTML**（实测有 ``<br/>`` / ``<b>`` / ``<span>``），
       入库前剥标签，否则 UI 渲染出字面 ``&lt;b&gt;``。
    """
    ext_id_raw = raw.get("id")
    try:
        # 20 位数字串 → int64 装得下；转成 int 是为了跟 NewsFeedItem.external_id 对齐
        ext_id = int(ext_id_raw)
    except (TypeError, ValueError):
        logger.debug("jin10 item dropped: id=%r 非数字", ext_id_raw)
        return None
    data = raw.get("data")
    if not isinstance(data, dict):
        logger.debug("jin10 item dropped: id=%s data 非 dict", ext_id)
        return None
    if data.get("lock"):
        logger.debug("jin10 item dropped (VIP 占位): id=%s", ext_id)
        return None
    content = _strip_html(data.get("content") or "")
    title = _strip_html(data.get("title") or "")
    if not title:
        title = content[:_TITLE_SNIPPET_LEN]
    if not title:
        logger.debug("jin10 item dropped: id=%s 无 title 且无 content", ext_id)
        return None
    pub_dt = _parse_bjt(raw.get("time"))
    if pub_dt is None:
        logger.debug("jin10 item dropped: id=%s 时间 %r 不可解析", ext_id, raw.get("time"))
        return None
    return _build(
        source="jin10",
        external_id=ext_id,
        title=title,
        summary=content,
        # ⚠ 金十快讯无链接。source_link 字段实测恒为 None，但仍按「有就用」处理
        url=(data.get("source_link") or "").strip() or None,
        site_name=_SITE_NAMES["jin10"],
        publish_dt=pub_dt,
    )


async def fetch_jin10_feed(*, use_cache: bool = True) -> tuple[dict, ...]:
    """抓金十数据快讯。

    ⚠ 必须带 ``x-app-id`` / ``x-version`` header（服务端校验，缺失会被拒）；
    ⚠ ``max_time`` 的值含空格，httpx 的 ``params`` 会自动 urlencode —— 若改成
    手拼 URL 就会撞 ``InvalidURL: URL can't contain control characters``。

    Raises:
        NewsSourceError: 网络失败 / HTTP 非 2xx / 解析失败 / ``data`` 非 list
    """
    key = ("jin10",)
    if use_cache:
        cached = _cache_get(key)
        if cached is not None:
            logger.debug("jin10 fetcher cache HIT")
            return cached

    payload = await _fetch_json(
        _JIN10_URL,
        source="jin10",
        params={"max_time": "", "channel": "-8200", "vip": "1"},
        headers={"x-app-id": "bVBF4FyRTn5NJF5n", "x-version": "1.0.0"},
    )
    if isinstance(payload, dict) and payload.get("status") not in (200, "200"):
        raise NewsSourceError(
            f"jin10 business status={payload.get('status')}: {payload.get('message')}"
        )
    items_raw = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items_raw, list):
        raise NewsSourceError(f"jin10 response data not list: {type(items_raw).__name__}")
    out = tuple(
        rec
        for rec in (_normalize_jin10(r) for r in items_raw if isinstance(r, dict))
        if rec is not None
    )
    _cache_set(key, out)
    logger.info("jin10 fetched: %d raw → %d normalized", len(items_raw), len(out))
    return out


# ────────────── 源 3：东方财富 ──────────────


def _normalize_eastmoney(raw: dict[str, Any]) -> dict | None:
    """东方财富单条 → NewsFeedItem dict。

    ⚠ 唯一坑：**完全没有 URL 字段**（实测 0/20 条有任何 url 字段）⇒ url 恒 None。
    """
    ext_id_raw = raw.get("code")
    try:
        ext_id = int(ext_id_raw)
    except (TypeError, ValueError):
        logger.debug("eastmoney item dropped: code=%r 非数字", ext_id_raw)
        return None
    title = _strip_html(raw.get("title") or "")
    summary = _strip_html(raw.get("summary") or "")
    if not title:
        logger.debug("eastmoney item dropped: code=%s 无 title", ext_id)
        return None
    pub_dt = _parse_bjt(raw.get("showTime"))
    if pub_dt is None:
        logger.debug(
            "eastmoney item dropped: code=%s showTime=%r 不可解析", ext_id, raw.get("showTime")
        )
        return None
    return _build(
        source="eastmoney",
        external_id=ext_id,
        title=title,
        summary=summary or title,
        url=None,  # 东财快讯不提供链接（实测 0/20）
        site_name=_SITE_NAMES["eastmoney"],
        publish_dt=pub_dt,
    )


async def fetch_eastmoney_feed(
    *, page_size: int = 20, use_cache: bool = True
) -> tuple[dict, ...]:
    """抓东方财富快讯。

    ⚠ 两个 2026-10-22 实测才发现的服务端约束（缺任一都只返回
    ``data=null`` 且 ``code=0``，看起来像「没数据」而不是「参数错」）：
    - ``fastColumn`` 与 ``sortEnd`` **必须同时传**
    - **成功码是 ``1``**，不是 0

    Raises:
        NewsSourceError: 网络失败 / HTTP 非 2xx / 解析失败 / 业务码非 1 / data 非 dict
    """
    key = ("eastmoney", page_size)
    if use_cache:
        cached = _cache_get(key)
        if cached is not None:
            logger.debug("eastmoney fetcher cache HIT (page_size=%d)", page_size)
            return cached

    payload = await _fetch_json(
        _EASTMONEY_URL,
        source="eastmoney",
        params={
            "client": "web",
            "biz": "web_news_col",
            "fastColumn": "102",
            "sortEnd": "",
            "pageIndex": "1",
            "pageSize": str(page_size),
            "req_trace": "newsfeed",
            "fields": (
                "code,showTime,title,mediaName,summary,image,uniqueUrl,"
                "urlPrefix,urlWap,uniqueUrlWap"
            ),
            "types": "1,20",
        },
    )
    if not isinstance(payload, dict):
        raise NewsSourceError(f"eastmoney response not dict: {type(payload).__name__}")
    # ⚠ 成功码是 **1**（不是 0），且实测是**字符串** "1" —— `!= 1` 会把成功
    # 判成失败（首次实跑就踩了）。缺参数时返回 code="0" + data=null。
    if str(payload.get("code")) != "1":
        raise NewsSourceError(
            f"eastmoney business code={payload.get('code')}: {payload.get('message')}"
        )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise NewsSourceError(f"eastmoney response data not dict: {type(data).__name__}")
    items_raw = data.get("fastNewsList")
    if not isinstance(items_raw, list):
        raise NewsSourceError(
            f"eastmoney response data.fastNewsList not list: {type(items_raw).__name__}"
        )
    out = tuple(
        rec
        for rec in (_normalize_eastmoney(r) for r in items_raw if isinstance(r, dict))
        if rec is not None
    )
    _cache_set(key, out)
    logger.info("eastmoney fetched: %d raw → %d normalized", len(items_raw), len(out))
    return out


# ────────────── 源 4：readhub（兜底，复用既有 fetcher） ──────────────


async def _fetch_readhub_via_chain(*, use_cache: bool) -> tuple[dict, ...]:
    """readhub 走它自己的 ``fetch_readhub_feed``（含既有 cache / 重试 / 黑白名单）。

    该函数**一行未改**（28 个既有测试依赖其行为），仅作为链末位参与 failover。
    它的 ``ReadhubFetchError`` 在这里被转成 ``NewsSourceError``，让调用方只需
    认一种异常类型。
    """
    try:
        return await fetch_readhub_feed(use_cache=use_cache)
    except ReadhubFetchError as exc:
        raise NewsSourceError(f"readhub: {exc}") from exc


# ────────────── failover 链 ──────────────


class NewsSource(NamedTuple):
    """注册表一项。``key`` 与 ``site_name`` 一起写进 normalize 产物。"""

    key: str
    fetch: Any


SOURCES: tuple[NewsSource, ...] = (
    NewsSource("wallstcn", lambda **kw: fetch_wallstcn_feed(**kw)),
    NewsSource("jin10", lambda **kw: fetch_jin10_feed(**kw)),
    NewsSource("eastmoney", lambda **kw: fetch_eastmoney_feed(**kw)),
    NewsSource("readhub", lambda **kw: _fetch_readhub_via_chain(**kw)),
)


async def fetch_news_feed(*, use_cache: bool = True) -> NewsFetchResult:
    """链式 failover 抓新闻：首个返回 ≥``MIN_ITEMS`` 条的源即止。

    逐源尝试，任一源抛错或返回量不足都**记录后继续**下一源 —— 这是 failover
    的全部意义：单源挂了不能变成「今日要闻空白」。

    Args:
        use_cache: False → 每个源都强制重抓（手动 refresh 用）

    Returns:
        ``NewsFetchResult(items, source)``，``source`` 是赢的那个源的 key

    Raises:
        NewsSourceError: **全部**源都失败 / 都返回不足量数据（错误串列出每源原因，
            便于从日志一眼看出是哪几个源同时挂了）
    """
    failures: list[str] = []
    thin: list[str] = []
    for src in SOURCES:
        try:
            items = await src.fetch(use_cache=use_cache)
        except NewsSourceError as exc:
            logger.warning("news source %s failed, trying next: %s", src.key, exc)
            failures.append(f"{src.key}: {exc}")
            continue
        except Exception as exc:  # 兜底：任何意外都不让它中断整条链
            logger.error("news source %s unexpected error: %s", src.key, exc)
            failures.append(f"{src.key}: unexpected {exc}")
            continue
        if len(items) >= MIN_ITEMS:
            logger.info(
                "news source %s WON with %d items (chain position %d)",
                src.key,
                len(items),
                [s.key for s in SOURCES].index(src.key) + 1,
            )
            return NewsFetchResult(items=items, source=src.key)
        logger.warning(
            "news source %s returned only %d items (< MIN_ITEMS=%d), trying next",
            src.key,
            len(items),
            MIN_ITEMS,
        )
        thin.append(f"{src.key}: {len(items)} < {MIN_ITEMS}")

    detail = "; ".join(failures + thin) or "no sources configured"
    raise NewsSourceError(f"all news sources unavailable or too thin: {detail}")