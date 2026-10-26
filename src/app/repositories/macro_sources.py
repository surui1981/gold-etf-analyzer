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
import calendar
import csv
import io
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

from app.utils.logger import get_logger

logger = get_logger(__name__)

#: FRED 序列 ID → 宏观因子 key（``real10y`` / ``vix``）—— **日频**序列
FRED_SERIES: dict[str, str] = {
    "DFII10": "real10y",  # 10 年期 TIPS 实际收益率（%）
    "VIXCLS": "vix",  # CBOE 波动率指数收盘价
}

#: FRED **低频**序列 → (因子 key, 回看天数, 观测期类型)
#:
#: 低频序列与日频序列有两处不同，混用会静默取不到值：
#: ① ``fetch_fred_latest`` 默认只回看 30 天 —— 季度/年度序列在这个窗口里
#:    **一条数据都没有**，必须按序列给足回看天数；
#: ② 观测日不是「当天」而是**观测期的期初**（FRED 季度序列用季初日期，
#:    年度序列用年初日期）—— 拿它当「数据日期」会让滞后天数凭空多出
#:    一整个季度/一年，必须归一到**期末**。
#:
#: ==================  ======================  ======  ==========
#: 序列                 因子                     回看    期型
#: ==================  ======================  ======  ==========
#: ``GFDEGDQ188S``     美国政府债务/GDP（CBO）   200 天  quarterly
#: ``GGGDTACNA188N``   中国政府债务/GDP（IMF）   900 天  annual
#: ==================  ======================  ======  ==========
FRED_PERIODIC_SERIES: dict[str, tuple[str, int, str]] = {
    # 美国联邦债务/GDP（季度，Q = quarterly；注意 ``GFDEGDN188S`` 是无效 ID）
    "GFDEGDQ188S": ("us_gov_debt", 200, "quarterly"),
    # 中国一般政府总债务/GDP（IMF WEO 年度，N = annual）
    "GGGDTACNA188N": ("cn_gov_debt", 900, "annual"),
}

#: Yahoo 指数代码 → 宏观因子 key（``dxy``）
YAHOO_SYMBOLS: dict[str, str] = {
    "DX-Y.NYB": "dxy",  # ICE 美元指数（DXY 本体）
}

#: Eurostat「季度一般政府债务」数据集（``na_item=GD`` / ``sector=S13`` / ``unit=PC_GDP``）
EUROSTAT_GOV_DEBT_DATASET = "GOV_10Q_GGDEBT"
#: Eurostat「欧洲」默认地理口径：欧盟 27 国
EUROSTAT_GOV_DEBT_GEO = "EU27_2020"

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


# ───────────────────── 观测期归一（低频因子专用） ─────────────────────


def _days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def _add_months(d: date, months: int) -> date:
    """加月份（自动处理月末，如 1-31 + 1 月 → 2-28/29）。"""
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    return date(y, m, min(d.day, _days_in_month(y, m)))


def fred_period_end(obs: date, period: str) -> date:
    """把 FRED 低频序列的**观测期期初日期**换算成**期末日期**。

    FRED 的季度/年度序列用期初日期标注观测（``2026-01-01`` = 2026Q1），
    期末才是这个读数真正「代表」的那一天。归一后：

    - 前端的滞后天数才对得上（否则凭空多算一整个季度/一年）；
    - 三个低频因子的 ``data_date`` 口径统一（都是 ISO 期末日），
      ``Date.parse`` 能解析（``Date.parse('2026-Q2')`` 是 ``NaN``）。

    ``period`` 取 ``"quarterly"`` / ``"annual"``；其他值原样返回。
    """
    if period == "quarterly":
        return _add_months(obs, 3) - timedelta(days=1)
    if period == "annual":
        return _add_months(obs, 12) - timedelta(days=1)
    return obs


def eurostat_period_end(label: str) -> date | None:
    """Eurostat 期间标签 → 期末日期。

    ``"2026-Q2"`` → ``2026-06-30``；``"2026"`` → ``2026-12-31``；
    ``"2026-Q1"`` → ``2026-03-31``。无法解析返回 ``None``。
    """
    label = (label or "").strip()
    m = re.fullmatch(r"(\d{4})-Q([1-4])", label)
    if m:
        year, q = int(m.group(1)), int(m.group(2))
        month = q * 3
        return date(year, month, _days_in_month(year, month))
    m = re.fullmatch(r"(\d{4})", label)
    if m:
        year = int(m.group(1))
        return date(year, 12, 31)
    return None


# ───────────────────── Eurostat 解析（JSON-stat） ─────────────────────


def _json_stat_records(payload: dict) -> list[tuple[dict, object]]:
    """JSON-stat 响应 → ``[(维度组合 dict, 值), ...]``。

    Eurostat 的 dissemination API 返回 JSON-stat 2.0：``id`` 是维度名列表、
    ``size`` 是各维度基数、``value`` 用**扁平下标**（行优先）编码。
    下标要按 ``size`` 逐位拆开才能还原成维度组合。

    ⚠ ``category.index`` 有两种形态：单值维度是 dict（``{"GD": 0}``），
    多值维度是 list（``["2026-Q1", "2026-Q2"]``）—— 两种都要能处理。
    """
    ids = payload.get("id") or []
    size = payload.get("size") or []
    if len(ids) != len(size):
        return []
    cats: list[list[str]] = []
    for dim in ids:
        cat = ((payload.get("dimension") or {}).get(dim) or {}).get("category") or {}
        idx = cat.get("index")
        if isinstance(idx, dict):
            order: list[str] = [""] * len(idx)
            for code, pos in idx.items():
                if isinstance(pos, int) and 0 <= pos < len(order):
                    order[pos] = code
        elif isinstance(idx, list):
            order = list(idx)
        else:
            order = []
        cats.append(order)
    out: list[tuple[dict, object]] = []
    for flat, val in (payload.get("value") or {}).items():
        try:
            rem = int(flat)
        except (TypeError, ValueError):
            continue
        coords: list[int] = []
        for s in reversed(size):
            coords.append(rem % s)
            rem //= s
        coords.reverse()
        rec = {ids[i]: cats[i][coords[i]] for i in range(len(ids)) if coords[i] < len(cats[i])}
        out.append((rec, val))
    return out


def parse_eurostat_gov_debt(text: str) -> list[tuple[str, float]]:
    """解析 Eurostat「季度一般政府债务」→ ``[(期间标签, 值), ...]``（期间升序）。

    只取 ``na_item=GD``（一般政府总债务）/ ``sector=S13``（一般政府）/
    ``unit=PC_GDP``（占 GDP 百分比）三条同时成立的记录。

    缺值处理：Eurostat 用 ``status`` 标注（``"p"``=暂定 / ``"e"``=预估），
    值为 ``None`` 或非数字的一律跳过 —— **不向前填充**（同 ``parse_fred_csv``
    的理由：填充会把「这一期没数据」伪装成「这一期就是这个数」）。
    """
    out: list[tuple[str, float]] = []
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("Eurostat JSON 解析失败: %s", exc)
        return out
    for rec, val in _json_stat_records(payload):
        if rec.get("na_item") != "GD" or rec.get("sector") != "S13":
            continue
        if rec.get("unit") != "PC_GDP":
            continue
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            continue
        label = str(rec.get("time") or "")
        if not label:
            continue
        out.append((label, float(val)))
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


async def fetch_fred_periodic_latest(
    series_id: str,
    *,
    base_url: str,
    lookback_days: int,
    period: str,
) -> tuple[float, date] | None:
    """取 FRED **低频**序列的最新值，并把观测日归一到**期末**。

    → ``(数值, 期末日期)``；无数据返回 ``None``。

    ``lookback_days`` 必须给足（季度 200 天 / 年度 900 天）—— 默认的 30 天窗口
    对低频序列**一条数据都取不到**（静默返回 None ⇒ 因子掉进静态兜底）。
    """
    series = await fetch_fred_series(
        series_id,
        base_url=base_url,
        start=date.today() - timedelta(days=lookback_days),
        end=date.today(),
    )
    if not series:
        return None
    obs, v = series[-1]
    return v, fred_period_end(obs, period)


async def fetch_eurostat_gov_debt(
    *,
    base_url: str,
    geo: str = EUROSTAT_GOV_DEBT_GEO,
    periods: int = 2,
) -> tuple[float, date] | None:
    """取 Eurostat 季度一般政府债务/GDP → ``(数值, 期末日期)``；无数据返回 ``None``。

    ``periods`` 取最近 N 期（默认 2）：最新一期可能是暂定值或缺值，
    多取一期兜底 —— 但**只用最新那个有值的**（不向前填充）。

    ⚠ Eurostat 无 UA 限制（实测 2026-10-26：Python-urllib / Mozilla / 无 UA
    三种都 200），与 FRED（不发 UA 才对）相反。
    """
    url = (
        f"{base_url.format(dataset=urllib.parse.quote(EUROSTAT_GOV_DEBT_DATASET))}"
        f"?format=JSON&lang=en&geo={urllib.parse.quote(geo)}&unit=PC_GDP"
        f"&na_item=GD&sector=S13&lastTimePeriod={max(1, int(periods))}"
    )
    text = await _fetch_text(url, user_agent=None)
    if text is None:
        return None
    series = parse_eurostat_gov_debt(text)
    if not series:
        logger.warning("Eurostat %s/%s 无有效数据点", EUROSTAT_GOV_DEBT_DATASET, geo)
        return None
    label, value = series[-1]
    period_end = eurostat_period_end(label)
    if period_end is None:
        logger.warning("Eurostat 期间标签无法解析: %s", label)
        return None
    return value, period_end
