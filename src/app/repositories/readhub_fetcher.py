"""readhub 财经新闻流抓取器（V0.102 / V0.107.1 / V0.108.0 站点黑白名单）

数据源
------
- readhub 内部 API（前端 hydrate 用），非官方但匿名稳定，4h 一次抓取
- 端点：``GET https://api.readhub.cn/news``（仅 ``/news`` 不带 ``/finance`` 子
  路径——``/finance`` 只是一级 URL 上的静态目录，API 只暴露 /news 流）
- 响应 schema::

    {
      "data": [
        {
          "id": 263197,                    # int，dedup 主键
          "title": "...",
          "summary": "...",
          "url": "https://wallstreetcn.com/...",  # 原文链接
          "mobileUrl": "https://m.wallstreetcn.com/...",
          "siteName": "华尔街见闻",
          "language": "zh-cn",
          "authorName": "...",
          "publishDate": "2026-10-19T01:00:00+08:00"
        },
        ...
      ],
      "pageSize": 50,
      "totalItems": 64378,
      "totalPages": 12876,
      "lastCursor": 263178
    }

设计要点
--------
- 进程内 5 分钟 fetcher cache：避免 scheduler 4h 唤醒 + 手动 ``refresh`` 在
  同一时刻撞车；并降低对 readhub 的请求频次（实测无 429，但以防万一）
- 抓取错误（timeout / 5xx / JSON 解析失败）→ 抛 ``ReadhubFetchError``，
  由 service 捕获 + 走「保留末次」 UX 路径（参考 V0.84 freshness 降级）
- V0.107.1 page_size 20→50（readhub max 100；实测 P99 <2s）：抓 1 次够 cover
  4h 周期；不支持分页深抓（分页 cursor 用 base64 编码 + 服务端校验字段，
  逆向成本远高于价值）
- V0.107.1 ``_normalize`` 末段拦截 ``category == '其他'`` —— 不写入 DB；
  service 层另有二次 gate（defense-in-depth）
- V0.108.0 站点黑白名单（用户方案 B）：
  - ``SITE_BLOCKLIST``：确证聚合噪声源，``_normalize`` 入口硬删（即使摘要
    本身能分类）。实测 30 天窗口「新浪科技」26 条里 4 条是地方新闻 / 文艺
    活动（重阳节文明实践、高速隧道贯通、获奖座谈会），信噪比 26:1，不值得为
    它开白名单豁免。
  - 白名单**不**在 fetcher 做：优质站点的「即使摘要为空也该保留」需求由
    ``news_classifier`` 把站名写进关键词字典实现（站名即关键词），复用现有
    classify 通路，零新增逻辑。
- **不**做实体抽取 / 情感——留给后续能力（plan §排除已声明）
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from app.repositories.news_classifier import classify
from app.utils.logger import get_logger

logger = get_logger(__name__)

# readhub 内部 API（前端 hydrate 用，匿名稳定）
_API_URL = "https://api.readhub.cn/news"
_DEFAULT_PAGE_SIZE = 50  # V0.107.1：20→50（readhub max 100；实测 P99 <2s）
_HTTP_TIMEOUT_SECONDS = 30.0
_RETRY_BACKOFFS: tuple[float, ...] = (0.0, 1.5)  # 第 1 次失败后等 1.5s 重试
_FETCHER_CACHE_TTL = 300  # 5 分钟（避免 scheduler + 手动 refresh 撞车）

# V0.108.0 站点黑名单（用户方案 B）：聚合类噪声源，_normalize 入口硬删。
# 收录纪律 —— 必须同时满足：
#   1. 该源在 30 天窗口样本量 ≥ 10 条（样本太少的源交给 classify 兜底）
#   2. 抽样 ≥5 条里，与「财经 / 科技 / 创投 / 商业」无关的比例 ≥ 60%
#   3. 不是任何优质垂直媒体的转载源
# 「澎湃新闻」实测 3 条全为优质（量子网络相位锁定等）→ **不**拉黑；
# 「techradar / 9to5Mac」虽有广告/促销内容，但主体是有效科技新闻 → **不**拉黑。
SITE_BLOCKLIST: frozenset[str] = frozenset(
    {
        "新浪科技",  # 26 条中 ~4 条地方新闻 / 文艺活动，ETF 类有效内容仅 1 条
        "maomu.com",  # 加密推广 spam（样本量小但内容 100% 无效）
    }
)


class ReadhubFetchError(RuntimeError):
    """readhub 抓取失败（timeout / 5xx / 解析错误 / 业务异常）。"""


@dataclass(frozen=True)
class ReadhubItem:
    """readhub 单条新闻（已 normalize）。"""

    external_id: int
    title: str
    summary: str
    url: str
    mobile_url: str | None
    site_name: str
    language: str | None
    author_name: str | None
    publish_date: datetime


# 进程内 fetcher cache：key=("readhub",) -> (ts, tuple[dict, ...])
# 缓存存储已经是 normalize 后的 dict（NewsFeedItem 字段映射），
# 直接喂给 NewsFeedRepository.upsert_bulk，省一遍转换。
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


def _parse_publish_date(raw: str | None) -> datetime | None:
    """readhub 返回 ISO 8601 + tz offset；解析失败 → None（保留 NULL 纪律）。"""
    if not raw:
        return None
    try:
        # fromisoformat 在 3.11+ 支持 'Z' 后缀；readhub 给的是 '+08:00'，直接吃
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    # 缺 tz 信息的退回 UTC（readhub 实际都给，但容错）
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _normalize(raw: dict[str, Any]) -> dict | None:
    """把 readhub 单条 dict 转 NewsFeedItem 字段 dict；缺关键字段则丢弃。

    Returns:
        正常 dict；缺 external_id / title / url / publish_date → None（丢弃该条）。
        V0.107.1 新增：``classify(...) == '其他'`` 也返 None（fetcher 层弃入，
        不写入 DB；另有 service 二次 gate 兜底）。
        V0.108.0 新增：``site_name in SITE_BLOCKLIST`` 也返 None（聚合噪声源
        硬删，优先于 classify）。
    """
    ext_id = raw.get("id")
    title = (raw.get("title") or "").strip()
    url = (raw.get("url") or "").strip()
    pub_raw = raw.get("publishDate")
    site = (raw.get("siteName") or "").strip()
    pub_dt = _parse_publish_date(pub_raw)
    if not isinstance(ext_id, int) or not title or not url or not pub_dt or not site:
        logger.debug(
            "readhub item dropped: id=%r title=%r url=%r site=%r pub=%r",
            ext_id,
            bool(title),
            bool(url),
            bool(site),
            bool(pub_dt),
        )
        return None
    # V0.108.0：站点黑名单硬删（优先于 classify —— 新浪科技这类聚合源即使
    # 单条内容碰巧能分类，也不进 4 类流）
    if site in SITE_BLOCKLIST:
        logger.debug("readhub item dropped (site blacklisted): id=%r site=%r", ext_id, site)
        return None
    # V0.105：入库即分类（关键词规则；upsert 时已分类行不变更）
    category = classify(title, (raw.get("summary") or "").strip(), site)
    # V0.107.1：fetcher 层弃入「其他」——不写入 DB
    if category == "其他":
        logger.debug("readhub item dropped (category=其他): id=%r", ext_id)
        return None
    return {
        "external_id": ext_id,
        "title": title,
        "summary": (raw.get("summary") or "").strip(),
        "url": url,
        "mobile_url": (raw.get("mobileUrl") or "").strip() or None,
        "site_name": site[:64],  # String(64) 截断保护
        "language": (raw.get("language") or "").strip()[:8] or None,
        "author_name": (raw.get("authorName") or "").strip()[:128] or None,
        "publish_date": pub_dt,
        "category": category,
        # fetched_at 用 SQL DEFAULT now；source = 'readhub' 走 server_default
    }


async def fetch_readhub_feed(
    *,
    page_size: int = _DEFAULT_PAGE_SIZE,
    use_cache: bool = True,
) -> tuple[dict, ...]:
    """抓取 readhub 最新财经新闻。

    Args:
        page_size: 一次抓取条数（默认 50，readhub max 100；V0.107.1 20→50）
        use_cache: True → 5min TTL 命中直接返回；False → 强制重抓

    Returns:
        已 normalize 的 dict 元组（可直接喂 ``NewsFeedRepository.upsert_bulk``）。
        V0.107.1：``_normalize`` 已弃入 ``category='其他'``，本函数返回的元组
        **不会**含 category='其他'。
        抓取失败 → 抛 ``ReadhubFetchError``（由 service 兜底）

    Raises:
        ReadhubFetchError: 网络失败 / HTTP 非 2xx / 解析失败
    """
    key = ("readhub", page_size)
    if use_cache:
        cached = _cache_get(key)
        if cached is not None:
            logger.debug("readhub fetcher cache HIT (page_size=%d)", page_size)
            return cached

    last_exc: Exception | None = None
    for attempt, backoff in enumerate(_RETRY_BACKOFFS):
        if backoff:
            await asyncio.sleep(backoff)
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
                resp = await client.get(
                    _API_URL,
                    params={"pageSize": page_size},
                    headers={
                        "User-Agent": "gold-etf-analyzer/V0.108.0",
                        "Accept": "application/json",
                    },
                )
            if resp.status_code == 200:
                data = resp.json()
                items_raw = data.get("data") or []
                if not isinstance(items_raw, list):
                    raise ReadhubFetchError(
                        f"readhub response 'data' not list: {type(items_raw).__name__}"
                    )
                normalized: list[dict] = []
                for raw in items_raw:
                    if not isinstance(raw, dict):
                        continue
                    rec = _normalize(raw)
                    if rec is not None:
                        normalized.append(rec)
                out = tuple(normalized)
                _cache_set(key, out)
                logger.info(
                    "readhub fetched: %d raw → %d normalized (page_size=%d, attempt=%d)",
                    len(items_raw),
                    len(out),
                    page_size,
                    attempt,
                )
                return out
            # 5xx / 429 → 重试；4xx 业务错误直接抛
            if 500 <= resp.status_code < 600 or resp.status_code == 429:
                last_exc = ReadhubFetchError(
                    f"readhub HTTP {resp.status_code}: {resp.text[:200]}"
                )
                continue
            raise ReadhubFetchError(
                f"readhub HTTP {resp.status_code}: {resp.text[:200]}"
            )
        except ReadhubFetchError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            last_exc = ReadhubFetchError(f"readhub network error: {exc}")
            logger.warning(
                "readhub fetch attempt %d network error: %s", attempt, exc
            )
            continue
        except (json.JSONDecodeError, KeyError) as exc:
            raise ReadhubFetchError(f"readhub response parse error: {exc}") from exc

    raise last_exc if last_exc else ReadhubFetchError("readhub fetch failed (unknown)")
