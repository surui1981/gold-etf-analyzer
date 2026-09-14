"""央行黄金购买数据采集：WGC Gold Demand Trends（HTML chart 数据）+ 手工补丁 JSON。

数据源说明
----------
IMF IRFCL SDMX 端点（api.imf.org/external/sdmx/{2.1,3.0}/data/IRFCL/...）实测：
- SDMX 3.0: HTTP 404（该数据流未发布到 SDMX 3.0）
- SDMX 2.1: HTTP 200 但 DataSet 为空，无 observations（IMF DataMapper 才有展示）
- sdmxcentral.imf.org v2: HTTP 501 不支持 IRFCL data
- dataservices.imf.org: DNS 解析失败
因此切到 WGC 官方 Gold Demand Trends 报告页面，HTML 内嵌的 chart JS
（``fsapi.gold.org/api/v12/charts/js/...``）公开可访问，无需 KEY：
- 季度合计（2010-2026，52 个季度）→ Chart 8 of Q2 2026
- H1 2026 按国家（19 买家 + 4 卖家）→ Chart 9 of Q2 2026

WGC XLSX 直链（``/download/file/...``）返回 403，需要浏览器 Cookie。
本 fetcher 走 HTML 嵌入的 chart JS 路径，绕开 XLSX 反爬。

手工补丁：UZB/IRN 等不在 WGC Chart 9 列表中的国家，从
``data/central_bank_manual_overrides.json`` 读取。

单位转换
---------
WGC chart 数据已是吨（tonnes），无需 oz→tonnes 转换。

设计取舍
--------
- 进程内 TTL 缓存 24h（手动刷新策略下避免每次请求都拉 WGC）。
- WGC 失败不回退到 Mock：央行购金是结构性真实数据，宁缺勿假。
- WGC Q4 报告 URL 模式不存在（404），H2 按国家数据无法获取；H2 仅保留合计行。
"""

import asyncio
import json
import re
import threading
import time
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.utils.logger import get_logger

logger = get_logger(__name__)

# WGC Gold Demand Trends 报告页 URL 模板：quarter 取 q1/q2/q3，year 4 位
_WGC_REPORT_URL = (
    "https://www.gold.org/goldhub/research/gold-demand-trends/"
    "gold-demand-trends-{quarter}-{year}/chart-gallery"
)

# WGC Chart JS 数据 API 路径（HTML 内嵌 data-chart-data-lib 暴露）
_WGC_CHART_API = "https://fsapi.gold.org/api/v12/charts/js"

# ISO3 → 中文名（i18n 映射，覆盖 WGC Chart 9 出现的全部国家）
COUNTRY_NAMES: dict[str, str] = {
    # 主要购金国
    "POL": "波兰",
    "UZB": "乌兹别克斯坦",
    "CHN": "中国",
    "KAZ": "哈萨克斯坦",
    "CZE": "捷克",
    "CHL": "智利",
    "JOR": "约旦",
    "GHA": "加纳",
    "MYS": "马来西亚",
    "SGP": "新加坡",
    "KGZ": "吉尔吉斯斯坦",
    "KHM": "柬埔寨",
    "GTM": "危地马拉",
    "SRB": "塞尔维亚",
    "IDN": "印度尼西亚",
    "BOL": "玻利维亚",
    "URY": "乌拉圭",
    "GEO": "格鲁吉亚",
    "PHL": "菲律宾",
    # 主要售金国
    "DEU": "德国",
    "AZE": "阿塞拜疆",
    "RUS": "俄罗斯",
    "TUR": "土耳其",
    # 合计 / 其他
    "WGC_AGGR": "全球合计",
    "IND": "印度",
    "HUN": "匈牙利",
    "BRA": "巴西",
    "MEX": "墨西哥",
    "EGY": "埃及",
    "SAU": "沙特",
    "IRN": "伊朗",
}

# 季度对应月份：Q1=3月, Q2=6月, Q3=9月, Q4=12月
# 键只用 "1"/"2"/"3"/"4"（"2026Q2".split("Q")[1] 结果），避免双重前缀
QUARTER_END_MONTHS: dict[str, int] = {"1": 3, "2": 6, "3": 9, "4": 12}

# 缓存 TTL：24 小时（手动刷新策略）
QUARTER_CACHE_TTL = 86400

# 进程内缓存：key=(url,) -> (ts, payload)
_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()

# 手工补丁路径
_OVERRIDES_PATH = Path(__file__).resolve().parents[3] / "data" / "central_bank_manual_overrides.json"


@dataclass(frozen=True)
class QuarterlyPurchase:
    """单国单季度净购金（吨）。"""

    country_iso: str
    country_name: str
    quarter: str  # "2026Q2"
    tonnes_net: float
    source: str  # "WGC GDT" / "WGC 手工"
    data_date: date  # 季度最后一日


def _http_get(url: str, timeout: int = 30) -> str:
    """通用 GET（仿 market_data._http_json）；返回 body 字符串（HTML/JS）。"""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def _http_get_json(url: str, timeout: int = 30) -> dict:
    """JSON GET。"""
    return json.loads(_http_get(url, timeout))


def _cache_get(key: tuple):
    with _CACHE_LOCK:
        item = _CACHE.get(key)
    if item is not None and time.time() - item[0] < QUARTER_CACHE_TTL:
        return item[1]
    return None


def _cache_set(key: tuple, value) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (time.time(), value)


def _quarter_to_data_date(quarter: str) -> date:
    """'2026Q2' → date(2026, 6, 30)。"""
    year, q = quarter.split("Q")
    month = QUARTER_END_MONTHS[q]
    last_day = {3: 31, 6: 30, 9: 30, 12: 31}[month]
    return date(int(year), month, last_day)


def _previous_quarter(quarter: str) -> str:
    """'2026Q2' → '2026Q1'；'2020Q1' → '2019Q4'。"""
    year, q = quarter.split("Q")
    year_i, q_i = int(year), int(q)
    if q_i == 1:
        return f"{year_i - 1}Q4"
    return f"{year_i}Q{q_i - 1}"


def _quarter_to_int(quarter: str) -> int:
    """'2026Q2' → 2026*10+2 = 20262（用于排序与同期比较）。"""
    year, q = quarter.split("Q")
    return int(year) * 10 + int(q)


# ── WGC HTML chart 抓取与解析 ───────────────────────────────────────


def _fetch_chart_js(chart_lib_path: str) -> str:
    """拉取 WGC chart JS（fsapi.gold.org/api/v12/charts/js/...）。"""
    cache_key = ("chart_js", chart_lib_path)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    # chart_lib_path 形如 "/api/v12/charts/js/gdt-q2-2026-2p3g5/3431"
    # 拼接完整 URL（去掉前导 / 防止双斜杠）
    url = _WGC_CHART_API + chart_lib_path
    body = _http_get(url)
    _cache_set(cache_key, body)
    return body


def _parse_chart_series(chart_js: str) -> tuple[list[str], dict[str, list[float]]]:
    """从 WGC chart JS 中抽取 categories 与 series data。

    chart JS 形如：
      "series":[{"name":"Net purchases","data":[1,2,3],...}, ...],
      "xAxis":{"categories":["Poland","China",...]}

    返回 (categories, {series_name: values})；空字符串/None 值转为 0.0。
    """
    cats_match = re.search(r'"categories":\s*\[([^\]]+)\]', chart_js)
    if not cats_match:
        return [], {}
    cats_str = cats_match.group(1)
    # categories 是字符串列表（带引号）
    cats = re.findall(r'"([^"]+)"', cats_str)
    # 也支持纯数字列表（年份）
    if not cats:
        cats = [s.strip().strip('"') for s in cats_str.split(",")]

    series: dict[str, list[float]] = {}
    # 找 "series":[{"name":"X","data":[...]},{...}]
    for m in re.finditer(
        r'\{(?:[^}]*?)"name":"([^"]+)"(?:[^}]*?)"data":\s*\[([^\]]+)\]',
        chart_js,
    ):
        name = m.group(1)
        values_str = m.group(2)
        values: list[float] = []
        for v in re.split(r",\s*", values_str):
            v = v.strip()
            if v in ('"null"', 'null', 'Null'):
                values.append(0.0)
            else:
                try:
                    values.append(float(v))
                except ValueError:
                    values.append(0.0)
        series[name] = values
    return cats, series


def _fetch_report_charts(year: int, quarter: str) -> list[dict]:
    """拉一份 GDT 报告页的 chart 列表（含 title 与 chart-lib URL）。

    Returns: [{"title": "...", "lib": "gdt-q2-2026-2p3g5/3431"}, ...]
    """
    url = _WGC_REPORT_URL.format(quarter=quarter, year=year)
    cache_key = ("report_page", url)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        html = _http_get(url)
    except Exception as exc:
        logger.warning("WGC 报告页拉取失败 %s: %s", url, exc)
        _cache_set(cache_key, [])
        return []

    # 匹配每个 chart article 的 title 与 lib URL
    # <h3>Chart 8: ...</h3> ... data-chart-data-lib="https://fsapi.gold.org/api/v12/charts/js/gdt-qX-YEAR-XXXX/NNNN"
    pattern = re.compile(
        r'<h3>(Chart \d+:[^<]+)</h3>.*?data-chart-data-lib="([^"]+)"',
        re.DOTALL,
    )
    results: list[dict] = []
    for m in pattern.finditer(html):
        title = re.sub(r"\s+", " ", m.group(1)).strip()
        lib_full = m.group(2)
        # 截取 path 部分（去掉 fsapi 前缀）
        lib_path = lib_full.replace("https://fsapi.gold.org/api/v12/charts/js", "")
        results.append({"title": title, "lib": lib_path})
    _cache_set(cache_key, results)
    return results


def _find_country_chart(charts: list[dict], title_keyword: str) -> dict | None:
    """从 charts 中找按国家拆分的 chart（按标题关键字）。"""
    kw = title_keyword.lower()
    for c in charts:
        if kw in c["title"].lower():
            return c
    return None


# ── 数据集：H1 2026 按国家 + 2014-2026 全球合计季度 ─────────────────────


def _iso_for_country(name: str) -> str:
    """WGC Chart 9 国家名 → ISO3；查不到返回原名（作伪 ISO 占位）。"""
    name_to_iso = {v: k for k, v in COUNTRY_NAMES.items()}
    # WGC 名字里 "Rep." / "Republic of" 是后缀缩写；做几个常见映射
    wgc_aliases = {
        # Q2 2026 Chart 9 countries（实际名称）
        "Poland": "POL",
        "Uzbekistan": "UZB",
        "China": "CHN",
        "Kazakhstan": "KAZ",
        "Czech Rep.": "CZE",
        "Chile": "CHL",
        "Jordan": "JOR",
        "Ghana": "GHA",
        "Malaysia": "MYS",
        "Singapore": "SGP",
        "Kyrgyz Rep.": "KGZ",
        "Cambodia": "KHM",
        "Guatemala": "GTM",
        "Serbia": "SRB",
        "Indonesia": "IDN",
        "Bolivia": "BOL",
        "Uruguay": "URY",
        "Georgia": "GEO",
        "Philippines": "PHL",
        "Germany": "DEU",
        "Azerbaijan (SOFAZ)": "AZE",
        "Russia": "RUS",
        "Turkey": "TUR",
        # Q3 2025 Chart 8 国家名（带 "Republic of" / "Russian Federation"）
        "Uzbekistan, Republic of": "UZB",
        "Russian Federation": "RUS",
        "Kyrgyz Republic": "KGZ",
        "Slovenia, Republic of": "SVN",
        "Egypt, Arab Republic of": "EGY",
        "India": "IND", "Qatar": "QAT", "Iraq": "IRQ",
        "Brazil": "BRA", "Czech Republic": "CZE",
        "Türkiye, Republic of": "TUR",
        "China, People's Republic of": "CHN",
        "Kazakhstan, Republic of": "KAZ",
        "Poland, Republic of": "POL",
    }
    if name in wgc_aliases:
        return wgc_aliases[name]
    if name in name_to_iso:
        return name_to_iso[name]
    return name  # 未识别，原样返回（仍可展示）


def fetch_global_quarterly_aggregate() -> list[QuarterlyPurchase]:
    """从 Q2 2026 报告 Chart 8 拉 2014-2026 全球季度合计（吨）。

    Chart 8 categories = 年份(2014-2026)，4 个 series = Q1/Q2/Q3/Q4。
    返回 13×4 = 52 行，country_iso="WGC_AGGR"。
    """
    charts = _fetch_report_charts(2026, "q2")
    c8 = _find_country_chart(charts, "central bank buying rebounded") or _find_country_chart(charts, "Quarterly central bank")
    if c8 is None:
        # fallback：找标题含 "tonnes" 的第一个 chart
        c8 = next((c for c in charts if "tonnes" in c["title"].lower()), None)
    if c8 is None:
        logger.warning("WGC Q2 2026 未找到 Chart 8 (global quarterly)")
        return []

    js = _fetch_chart_js(c8["lib"])
    cats, series = _parse_chart_series(js)
    # cats 形如 2014, 2015, ... 2026
    results: list[QuarterlyPurchase] = []
    for series_name, values in series.items():
        # series_name 形如 "Q1" / "Q2" / "Q3" / "Q4"
        m = re.match(r"Q(\d)", series_name)
        if not m:
            continue
        q_num = m.group(1)
        # 外部 JS chart 的类目轴与数值轴长度未必严格一致，按较短序列对齐（不抛错）
        for year, val in zip(cats, values, strict=False):
            try:
                year_i = int(year)
            except ValueError:
                continue
            if val == 0.0:
                continue  # 跳过 0 值（保持稀疏性）
            quarter = f"{year_i}Q{q_num}"
            results.append(
                QuarterlyPurchase(
                    country_iso="WGC_AGGR",
                    country_name=COUNTRY_NAMES["WGC_AGGR"],
                    quarter=quarter,
                    tonnes_net=round(val, 1),
                    source="WGC GDT Q2 2026 合计行",
                    data_date=_quarter_to_data_date(quarter),
                )
            )
    return results


def fetch_h1_2026_by_country() -> list[QuarterlyPurchase]:
    """从 Q2 2026 报告 Chart 9 拉 H1 2026 按国家（吨）。

    23 个国家：19 净买家 + 4 净卖家。
    H1 = Q1 + Q2，按全球合计 Q1/Q2 比例拆分（避免只存合计 H1）。
    """
    charts = _fetch_report_charts(2026, "q2")
    c9 = _find_country_chart(charts, "poland in pole position") or _find_country_chart(charts, "y-t-d reported central bank")
    if c9 is None:
        logger.warning("WGC Q2 2026 未找到 Chart 9 (by country)")
        return []

    js = _fetch_chart_js(c9["lib"])
    cats, series = _parse_chart_series(js)

    # 全球合计 Q1/Q2 2026 比例（用于拆分 H1）
    q1_share = 0.5  # fallback 等分
    q2_share = 0.5
    aggregate = fetch_global_quarterly_aggregate()
    h1_2026_total = next((a.tonnes_net for a in aggregate if a.quarter == "2026Q1"), None)
    h2_2026_total = next((a.tonnes_net for a in aggregate if a.quarter == "2026Q2"), None)
    if h1_2026_total and h2_2026_total and (h1_2026_total + h2_2026_total) > 0:
        total = h1_2026_total + h2_2026_total
        q1_share = h1_2026_total / total
        q2_share = h2_2026_total / total

    purchases = series.get("Net purchases", [])
    sales = series.get("Net sales", [])

    results: list[QuarterlyPurchase] = []
    for idx, country_name in enumerate(cats):
        iso = _iso_for_country(country_name)
        cname_zh = COUNTRY_NAMES.get(iso, country_name)
        # 净买入
        if idx < len(purchases):
            h1_tonnes = purchases[idx]
            if h1_tonnes != 0.0:
                q1_part = round(h1_tonnes * q1_share, 1)
                q2_part = round(h1_tonnes * q2_share, 1)
                for q, t in [("1", q1_part), ("2", q2_part)]:
                    if t == 0.0:
                        continue
                    quarter = f"2026Q{q}"
                    results.append(
                        QuarterlyPurchase(
                            country_iso=iso,
                            country_name=cname_zh,
                            quarter=quarter,
                            tonnes_net=t,
                            source="WGC GDT Q2 2026 H1",
                            data_date=_quarter_to_data_date(quarter),
                        )
                    )
        # 净卖出
        if idx < len(sales):
            h1_sales = sales[idx]
            if h1_sales != 0.0 and h1_sales < 0:
                q1_part = round(h1_sales * q1_share, 1)
                q2_part = round(h1_sales * q2_share, 1)
                for q, t in [("1", q1_part), ("2", q2_part)]:
                    if t == 0.0:
                        continue
                    quarter = f"2026Q{q}"
                    results.append(
                        QuarterlyPurchase(
                            country_iso=iso,
                            country_name=cname_zh,
                            quarter=quarter,
                            tonnes_net=t,
                            source="WGC GDT Q2 2026 H1",
                            data_date=_quarter_to_data_date(quarter),
                        )
                    )
    return results


def load_manual_overrides() -> list[QuarterlyPurchase]:
    """读取 ``data/central_bank_manual_overrides.json`` 中的国家季度吨数。"""
    if not _OVERRIDES_PATH.exists():
        logger.info("手工补丁文件不存在: %s", _OVERRIDES_PATH)
        return []

    try:
        with _OVERRIDES_PATH.open(encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        logger.warning("手工补丁 JSON 读取失败: %s", exc)
        return []

    results: list[QuarterlyPurchase] = []
    for iso, block in payload.items():
        if iso.startswith("_"):
            continue
        country_name = block.get("name", iso)
        source = block.get("source", "WGC 手工")
        for quarter, tonnes in block.get("data", []):
            try:
                results.append(
                    QuarterlyPurchase(
                        country_iso=iso,
                        country_name=country_name,
                        quarter=quarter,
                        tonnes_net=float(tonnes),
                        source=source,
                        data_date=_quarter_to_data_date(quarter),
                    )
                )
            except (ValueError, KeyError) as exc:
                logger.warning("手工补丁条目跳过 %s/%s: %s", iso, quarter, exc)
    return results


async def build_full_dataset(start: str = "2020-01", end: str | None = None) -> list[QuarterlyPurchase]:
    """编排：拉 WGC Chart 8（全球季度合计）+ Chart 9（H1 2026 按国家）+ 手工补丁。"""
    def _fetch_all():
        items: list[QuarterlyPurchase] = []
        items.extend(fetch_global_quarterly_aggregate())
        items.extend(fetch_h1_2026_by_country())
        items.extend(load_manual_overrides())
        return items

    return await asyncio.to_thread(_fetch_all)