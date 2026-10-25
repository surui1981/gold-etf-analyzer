"""宏观因子的补充数据源：FRED（实际利率 / VIX）+ Yahoo（DXY）。

V0.118.0 新增。背景与动机
------------------------
V0.110.0 之前，宏观面 5 个因子里有 3 个是「无自动源」的：

============  ==========================  ==========================================
因子           原状态                      V0.118.0 状态
============  ==========================  ==========================================
``dxy``        ``STATIC_REF`` 96.5        Yahoo ``DX-Y.NYB``（同尺度）
              （2026-08-28 硬编码）        实测 2026-10-25 = 101.75
``vix``        ``STATIC_REF`` 18.5        FRED ``VIXCLS``（同尺度）
              （2026-08-28 硬编码）        实测 2026-10-22 = 19.03
``real10y``    ——（因子本身不存在）        FRED ``DFII10``（10Y TIPS 实际利率）
                                        实测 2026-10-22 = 2.64
============  ==========================  ==========================================

**尺度必须不变**：``dxy`` 的 best/worst 是 95/105（DXY 尺度），``vix`` 是 25/12
（VIX 尺度）。如果换成尺度不同的序列（例：FRED ``DTWEXBGS`` 广义美元指数 ≈ 121），
存量手动校准值与硬编码阈值会同时失效 —— 所以这里只挑**同尺度**的源。

数据源特征
----------
- **FRED**（``fred.stlouisfed.org/graph/fredgraph.csv``）：官方、免费、**零 KEY**，
  CSV 两列 ``observation_date,SERIES_ID``，缺值用 ``.`` 表示。支持 ``cosd/coed``
  参数限定日期区间。
- **Yahoo chart**（``query1.finance.yahoo.com/v8/finance/chart/``）：非官方但免费
  零 KEY，JSON 结构。每日 DXY 交易时段柱的 ``close`` 数组在**当日尚未收盘**时
  末位为 ``null`` —— 必须过滤，否则会写入一个 ``None`` 读数。

两个源都做了**模块级 TTL 缓存**（``_TTL_SECONDS``）：宏观面自身有 10 分钟结果缓存，
但 scheduler 的历史落表与回填脚本会直接调这里，多一层缓存避免重复打网络。
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

from app.utils.logger import get_logger

logger = get_logger(__name__)

#: FRED 序列 ID → 宏观因子 key（``real10y`` / ``vix``）
FRED_SERIES: dict[str, str] = {
    "DFII10": "real10y",  # 10 年期 TIPS 实际收益率（%）
    "VIXCLS": "vix",  # CBOE 波动率指数收盘价
}

#: Yahoo 指数代码 → 宏观因子 key（``dxy``）
YAHOO_SYMBOLS: dict[str, str] = {
    "DX-Y.NYB": "dxy",  # ICE 美元指数（DXY 本体）
}

#: 模块级 TTL 缓存（秒）—— key 为完整 URL
_TTL_SECONDS = 300
_CACHE: dict[str, tuple[float, object]] = {}

#: 网络超时（秒）
_TIMEOUT = 15


def clear_macro_sources_cache() -> None:
    """清空 FRED / Yahoo 的 URL 级 TTL 缓存（测试隔离 + 回填后强制刷新）。"""
    _CACHE.clear()


def _http_text(url: str, timeout: int = _TIMEOUT, user_agent: str | None = None) -> str:
    """通用 TEXT GET（零依赖 urllib）。

    ⚠️ **User-Agent 必须按源分别指定** —— 三个源的 UA 规则互相矛盾，实测如下
    （2026-10-25，每个源各测 2 次，结果稳定）：

    ==============  ==================  ==================  ==============
    源               ``Mozilla/5.0``     不发 UA             结论
    ==============  ==================  ==================  ==============
    FRED            **读超时**（15s）   ✅ 1.0s              不发 UA
    Yahoo chart     ✅ 0.5s             ❌ HTTP 403         必须 Mozilla
    美联储 H.15     ✅ 1.2s             ❌ HTTP 403         必须 Mozilla
    ==============  ==================  ==================  ==============

    FRED 的 WAF 有一份**客户端工具白名单**（curl / Wget / Go-http-client / Java /
    libwww-perl / python-requests / okhttp / python-urllib）。名单外的 UA 会被
    **挂起** —— 连接建立、但响应永不返回，表现为读超时而不是 403，很容易被误判成
    「网络抖动」。urllib 在不发 UA 时会用默认的 ``Python-urllib/3.x``，正好在名单里。
    """
    headers = {"Accept": "*/*"}
    if user_agent:
        headers["User-Agent"] = user_agent
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


#: 需要浏览器 UA 的源（Yahoo chart / 美联储 H.15）
BROWSER_UA = "Mozilla/5.0"


async def _fetch_text(
    url: str,
    timeout: int = _TIMEOUT,
    user_agent: str | None = None,
) -> str | None:
    """带 TTL 缓存的 TEXT GET；失败返回 ``None``（不抛异常 —— 数据源失败不能拖垮宏观面）。"""
    ck = (url, user_agent)
    hit = _CACHE.get(ck)
    if hit is not None and (time.time() - hit[0]) < _TTL_SECONDS:
        return str(hit[1])
    try:
        text = await asyncio.wait_for(
            asyncio.to_thread(_http_text, url, timeout, user_agent), timeout=timeout + 5
        )
    except Exception as exc:
        logger.warning("宏观数据源取数失败 (%s): %s", url[:120], exc)
        return None
    _CACHE[ck] = (time.time(), text)
    return text


# ───────────────────── 解析器（纯函数，便于单测） ─────────────────────


def parse_fred_csv(text: str) -> list[tuple[date, float]]:
    """解析 FRED CSV → ``[(日期, 数值), ...]``（升序）。

    CSV 形如 ``observation_date,SERIES_ID``；缺值用 ``.``（或空）表示 —— 直接跳过，
    **不做前值填充**：填充会把「当天没数据」伪装成「当天就是这个数」，
    滚动分位窗口里两者含义完全不同。
    """
    out: list[tuple[date, float]] = []
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error as exc:
        logger.warning("FRED CSV 解析失败: %s", exc)
        return out
    for row in rows[1:]:  # 跳过表头
        if len(row) < 2:
            continue
        raw_d, raw_v = row[0].strip(), row[1].strip()
        if not raw_d or not raw_v or raw_v == ".":
            continue
        try:
            d = datetime.strptime(raw_d, "%Y-%m-%d").date()
            v = float(raw_v)
        except ValueError:
            continue
        out.append((d, v))
    out.sort(key=lambda t: t[0])
    return out


def parse_yahoo_chart_json(text: str) -> list[tuple[date, float]]:
    """解析 Yahoo chart JSON → ``[(日期, 收盘价), ...]``（升序）。

    结构：``chart.result[0].timestamp[]`` + ``chart.result[0].indicators.quote[0].close[]``。
    两个数组**按位置对齐**，长度为同一值；当日未收盘时末位 ``close`` 为 ``null`` → 跳过。
    日期取 UTC 日期（美股日线柱的时间戳落在同一 UTC 日）。

    ⚠️ ``zip(..., strict=False)``：Yahoo 偶尔会返回长度不一致的两个数组
    （例如缺失某个交易日的 bar）。用 ``strict=True`` 会让整个序列抛异常
    ⇒ 因子直接回退静态值（**丢掉全部历史**）；截断只丢末尾一两根，更划算。
    """
    out: list[tuple[date, float]] = []
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("Yahoo chart JSON 解析失败: %s", exc)
        return out
    results = (payload.get("chart") or {}).get("result") or []
    if not results:
        return out
    res = results[0]
    stamps = res.get("timestamp") or []
    quotes = (res.get("indicators") or {}).get("quote") or []
    closes = (quotes[0] or {}).get("close") if quotes else None
    if not stamps or not closes:
        return out
    for ts, close in zip(stamps, closes, strict=False):
        if close is None:
            continue  # 当日未收盘 / 停牌
        try:
            d = datetime.fromtimestamp(int(ts), tz=timezone.utc).date()
            v = float(close)
        except (TypeError, ValueError, OSError, OverflowError):
            continue
        out.append((d, v))
    out.sort(key=lambda t: t[0])
    return out


# ───────────────────── 取数 ─────────────────────


def _fred_url(base: str, series_id: str, start: date | None, end: date | None) -> str:
    url = base.format(series_id=urllib.parse.quote(series_id))
    params = []
    if start is not None:
        params.append(f"cosd={start.isoformat()}")
    if end is not None:
        params.append(f"coed={end.isoformat()}")
    if params:
        url = f"{url}&{'&'.join(params)}"
    return url


async def fetch_fred_series(
    series_id: str,
    *,
    base_url: str,
    start: date | None = None,
    end: date | None = None,
) -> list[tuple[date, float]]:
    """取 FRED 序列全量（或区间）数据 → ``[(日期, 数值), ...]``（升序）。

    失败返回空列表（调用方决定回退策略）。

    ⚠️ 不发 User-Agent —— 见 ``_http_text`` docstring 里三个源 UA 规则的实测表。
    """
    url = _fred_url(base_url, series_id, start, end)
    text = await _fetch_text(url, user_agent=None)
    if text is None:
        return []
    series = parse_fred_csv(text)
    if not series:
        logger.warning("FRED %s 无有效数据点", series_id)
    return series


async def fetch_yahoo_daily(
    symbol: str,
    *,
    base_url: str,
    range_: str = "2y",
    interval: str = "1d",
) -> list[tuple[date, float]]:
    """取 Yahoo 日线 → ``[(日期, 收盘价), ...]``（升序）。失败返回空列表。

    ⚠️ 必须带浏览器 UA（不发 UA 直接 403）—— 见 ``_http_text`` docstring。
    """
    url = base_url.format(
        symbol=urllib.parse.quote(symbol),
        range=urllib.parse.quote(range_),
        interval=urllib.parse.quote(interval),
    )
    text = await _fetch_text(url, user_agent=BROWSER_UA)
    if text is None:
        return []
    series = parse_yahoo_chart_json(text)
    if not series:
        logger.warning("Yahoo %s 无有效数据点", symbol)
    return series


async def fetch_fred_latest(
    series_id: str,
    *,
    base_url: str,
    lookback_days: int = 30,
) -> tuple[float, date] | None:
    """取 FRED 序列的**最新一个**有效值 → ``(数值, 数据日期)``；无数据返回 ``None``。

    只拉最近 ``lookback_days`` 天，避免每次评估都下载全量历史。
    """
    series = await fetch_fred_series(
        series_id,
        base_url=base_url,
        start=date.today() - timedelta(days=lookback_days),
        end=date.today(),
    )
    if not series:
        return None
    d, v = series[-1]
    return v, d


async def fetch_yahoo_latest(
    symbol: str,
    *,
    base_url: str,
    range_: str = "1mo",
    interval: str = "1d",
) -> tuple[float, date] | None:
    """取 Yahoo 日线的**最新一个**有效收盘价 → ``(数值, 日期)``；无数据返回 ``None``。"""
    series = await fetch_yahoo_daily(symbol, base_url=base_url, range_=range_, interval=interval)
    if not series:
        return None
    d, v = series[-1]
    return v, d
