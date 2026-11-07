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
- **全球季度合计**（2014-2026，52 个季度）→ 最新报告的「按季合计」图
  （Q3 2026 = Chart 10；Q2 2026 = Chart 8）
- **国别明细（仅已上报口径）** → 最新报告的「按国家」图
  （Q2 2026 = Chart 9；Q3 2026 的同名图已改成**按区域**，没有国别明细）

报告版本探测（V0.121.4）
-----------------------
WGC 每年只发 q1/q2/q3 三版报告页（Q4 没有独立报告页，URL 直接 404）。
本模块**按「新 → 旧」依次试**，取第一个能解析出目标图的版本：
``[(今年 q3, q2, q1), (去年 q3, q2, q1)]``。

识别目标图**不能只看标题** —— 各版标题每季都改，而且同一版里
「按区域」「按国家」「按季度」三张图的标题都含 "central bank"：
- Q3 2026 Chart 2  "…supported by central bank buying"（需求构成，不是购金明细）
- Q3 2026 Chart 10 "Y-t-d central bank buying exceeds 2025 pace"（**按季合计**）
- Q3 2026 Chart 11 "Poland and China continue to drive reported central bank purchases"（**按区域**）
⇒ 判定顺序：标题关键字 → **结构签名**（series 名 / 类目轴）→ 两者都要过。

WGC XLSX 直链（``/download/file/...``）返回 403，需要浏览器 Cookie。
本 fetcher 走 HTML 嵌入的 chart JS 路径，绕开 XLSX 反爬。

手工补丁：UZB/IRN 等不在 WGC 国别图列表中的国家，从
``data/central_bank_manual_overrides.json`` 读取。

单位转换
---------
WGC chart 数据已是吨（tonnes），无需 oz→tonnes 转换。

设计取舍
--------
- 进程内 TTL 缓存 24h（手动刷新策略下避免每次请求都拉 WGC）。
- WGC 失败不回退到 Mock：央行购金是结构性真实数据，宁缺勿假。
- WGC Q4 报告 URL 模式不存在（404），H2 按国家数据无法获取；H2 仅保留合计行。
- **全球合计行（``AGGREGATE_ISO``）与各国行不可相加** —— 相加即「合计 + 明细」
  的重复计数（V0.121.4 实测：2026Q2 全表求和 336.7 = 合计 288.9 + 各国 47.8）。
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

#: 全球合计行的伪 ISO —— 它**不是国家**，是 WGC 的「全球合计」口径。
#:
#: ⚠️ 它与各国行**不可相加**：相加 = 「合计 + 明细」的重复计数。
#:    （V0.121.4 实测：2026Q2 全表求和 336.7 = 合计 288.9 + 各国 47.8。）
#:    任何按国家/按季求和的地方都必须先把它剔除。
AGGREGATE_ISO = "WGC_AGGR"

#: 候选报告版本（**新 → 旧**）。WGC 每年只发 q1/q2/q3 三版报告页，
#: Q4 没有独立报告页（URL 直接 404）⇒ 不列入候选。
_REPORT_QUARTERS = ("q3", "q2", "q1")

#: 「按季合计」图的标题关键字（各版标题不同，逐版累积）。
#: ⚠️ 只是**候选**——最终仍要过结构签名（series 是 Q1..Q4 / 类目是年份）。
_AGGREGATE_TITLE_KEYWORDS = (
    "central bank buying exceeds",  # Q3 2026 Chart 10
    "central bank buying rebounded",  # Q2 2026 Chart 8
    "central bank buying remained elevated",  # Q1 2026 Chart 9
    "quarterly central bank",
)

#: 「按国家」图的标题关键字（快路径；找不到再走结构扫描）。
_COUNTRY_TITLE_KEYWORDS = (
    "pole position",  # Q2 2026 Chart 9
    "reported data",
    "reported central bank purchases",  # Q3 2026 Chart 11 —— ⚠️ 那张是**区域**图
)

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
_OVERRIDES_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "central_bank_manual_overrides.json"
)


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


def _report_candidates(today: date | None = None) -> list[tuple[int, str]]:
    """候选 WGC 报告版本（**新 → 旧**）：[(2026, "q3"), (2026, "q2"), ...]。

    WGC 每年只发 q1/q2/q3 三版报告页（Q4 无独立报告页，URL 404），
    故候选 = 今年 3 版 + 去年 3 版。

    Args:
        today: 注入「今天」用（测试可固定时钟；生产不传）。
    """
    ref = today or date.today()
    return [(y, q) for y in (ref.year, ref.year - 1) for q in _REPORT_QUARTERS]


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
            if v in ('"null"', "null", "Null"):
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


def _is_aggregate_chart(chart: dict) -> bool:
    """结构签名：这张 chart 是不是「按季合计」图？

    签名 = **series 名是 Q1..Q4**（4 条季度序列）且 **类目轴是年份**。

    为什么必须结构判定：同一版报告里标题都含 "central bank" 的图有好几张
    （Q3 2026 的 Chart 2 / 10 / 11），只靠标题会取错图 ——
    取错图不会报错，只会**静默给出另一个口径的数**。
    """
    js = _fetch_chart_js(chart["lib"])
    cats, series = _parse_chart_series(js)
    if not series or not cats:
        return False
    if not all(re.fullmatch(r"Q[1-4]", name) for name in series):
        return False
    return all(re.fullmatch(r"\d{4}", c) for c in cats)


def _is_country_level_chart(chart: dict) -> bool:
    """结构签名：这张 chart 是不是「按国家」图？

    签名 = **series 名含 Net purchases / Net sales**（WGC 国别图的固定命名），
    且类目轴**不是**年份。

    ⚠️ Q3 2026 的 Chart 11 标题写着 "reported central bank purchases"，
    但它是**按区域**（Asia / Europe / ...），series 是 "China" / "Rest of Asia"…
    ⇒ 标题过不了这一关，会被正确地排除。
    """
    js = _fetch_chart_js(chart["lib"])
    cats, series = _parse_chart_series(js)
    if not series or not cats:
        return False
    names = {name.lower() for name in series}
    if not names & {"net purchases", "net sales"}:
        return False
    return not all(re.fullmatch(r"\d{4}", c) for c in cats)


def _find_aggregate_chart(charts: list[dict]) -> dict | None:
    """找「按季合计」图：标题关键字 → 结构签名兜底。"""
    for kw in _AGGREGATE_TITLE_KEYWORDS:
        c = _find_country_chart(charts, kw)
        if c is not None and _is_aggregate_chart(c):
            return c
    # 兜底：标题含 central bank 且结构是「按季合计」
    for c in charts:
        if "central bank" in c["title"].lower() and _is_aggregate_chart(c):
            return c
    return None


def _find_country_level_chart(charts: list[dict]) -> dict | None:
    """找「按国家」图：标题关键字 → 结构签名兜底。"""
    for kw in _COUNTRY_TITLE_KEYWORDS:
        c = _find_country_chart(charts, kw)
        if c is not None and _is_country_level_chart(c):
            return c
    # 兜底：逐张图验结构（标题每季都改，不能只信标题）
    for c in charts:
        if _is_country_level_chart(c):
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
        "India": "IND",
        "Qatar": "QAT",
        "Iraq": "IRQ",
        "Brazil": "BRA",
        "Czech Republic": "CZE",
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


def fetch_global_quarterly_aggregate(
    today: date | None = None,
) -> list[QuarterlyPurchase]:
    """从**最新可用**的 GDT 报告拉全球季度合计（吨）。

    报告版本按「新 → 旧」试（q3 → q2 → q1，今年 → 去年），取第一个能解析出
    「按季合计」图的版本。目标图的结构：categories = 年份(2014-2026)，
    4 个 series = Q1/Q2/Q3/Q4 ⇒ 最多 13×4 = 52 行。

    返回行的 ``country_iso`` = :data:`AGGREGATE_ISO`（``WGC_AGGR``）——
    它是**全球合计口径**，与各国行不可相加。

    注意：最新报告会**回溯修订**历史季度（实测 Q3 2026 版把 2026Q1 由
    56.5 改成 57.7、2026Q2 由 288.9 改成 296.3）⇒ 取最新版本才是真值。
    """
    for year, quarter in _report_candidates(today):
        charts = _fetch_report_charts(year, quarter)
        if not charts:
            continue
        chart = _find_aggregate_chart(charts)
        if chart is None:
            logger.info("WGC GDT %s %s 未找到「按季合计」图", quarter.upper(), year)
            continue

        js = _fetch_chart_js(chart["lib"])
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
            for year_str, val in zip(cats, values, strict=False):
                try:
                    year_i = int(year_str)
                except ValueError:
                    continue
                if val == 0.0:
                    continue  # 跳过 0 值（保持稀疏性）
                quarter_label = f"{year_i}Q{q_num}"
                results.append(
                    QuarterlyPurchase(
                        country_iso=AGGREGATE_ISO,
                        country_name=COUNTRY_NAMES[AGGREGATE_ISO],
                        quarter=quarter_label,
                        tonnes_net=round(val, 1),
                        source=f"WGC GDT {quarter.upper()} {year} 合计行",
                        data_date=_quarter_to_data_date(quarter_label),
                    )
                )
        if results:
            logger.info(
                "WGC 全球季度合计：取自 GDT %s %s（%d 个季度）",
                quarter.upper(),
                year,
                len(results),
            )
            return results
    logger.warning("WGC 各报告版本均未取到「按季合计」图")
    return []


#: 报告版本 → 该版国别图覆盖的季度数（y-t-d 累计到第几季）
_COVERAGE_QUARTERS = {"q1": 1, "q2": 2, "q3": 3}

#: 覆盖季度的口径标签（写进 source，便于分辨「H1」还是「YTD」）
_COVERAGE_LABEL = {1: "Q1", 2: "H1", 3: "YTD"}


def fetch_2026_by_country(today: date | None = None) -> list[QuarterlyPurchase]:
    """拉 2026 年**已上报**（reported）的国家级净购金（吨）。

    ⚠️ 口径：WGC 的国别图只发**年初至今累计**（y-t-d）值，不发单季值；
    这里按全球合计各季占比把它拆到各季 —— 是**估算**，不是 WGC 直接发布的
    季度值（source 里标注了报告版本，别当成「官方季度值」用）。

    报告版本按「新 → 旧」试，取第一个带**国别**图的版本：

    - Q3 2026 Chart 11 标题写着 "…reported central bank purchases"，
      但它是**按区域**（Asia / Europe / Americas / Middle East / Africa / Other，
      series 是 China / Rest of Asia / Poland …）⇒ 结构签名判定会把它排除；
    - 因此**最新可用的国别图仍是 Q2 2026 Chart 9**（"Reported data puts Poland
      in pole position y-t-d"，覆盖 H1 = Q1+Q2，23 国：19 净买家 + 4 净卖家）。
    """
    for year, quarter in _report_candidates(today):
        charts = _fetch_report_charts(year, quarter)
        if not charts:
            continue
        chart = _find_country_level_chart(charts)
        if chart is None:
            logger.info(
                "WGC GDT %s %s 无国别明细图（该版只有区域图或未发布）",
                quarter.upper(),
                year,
            )
            continue

        js = _fetch_chart_js(chart["lib"])
        cats, series = _parse_chart_series(js)

        # 覆盖季度（q2 版覆盖 Q1+Q2，q3 版覆盖 Q1+Q2+Q3）
        n_cov = _COVERAGE_QUARTERS.get(quarter, 2)
        covered = [f"{year}Q{i}" for i in range(1, n_cov + 1)]

        # 全球合计各季占比（用于把 y-t-d 拆到各季）；缺失则等分兜底
        shares = _global_quarter_shares(covered, today)
        source = f"WGC GDT {quarter.upper()} {year} {_COVERAGE_LABEL.get(n_cov, 'YTD')}"

        purchases = series.get("Net purchases", [])
        sales = series.get("Net sales", [])

        results: list[QuarterlyPurchase] = []
        for idx, country_name in enumerate(cats):
            iso = _iso_for_country(country_name)
            cname_zh = COUNTRY_NAMES.get(iso, country_name)
            for values, only_negative in ((purchases, False), (sales, True)):
                if idx >= len(values):
                    continue
                ytd_tonnes = values[idx]
                if ytd_tonnes == 0.0:
                    continue
                if only_negative and ytd_tonnes > 0:
                    continue  # 净卖出序列只取负值
                for quarter_label, share in zip(covered, shares, strict=True):
                    part = round(ytd_tonnes * share, 1)
                    if part == 0.0:
                        continue
                    results.append(
                        QuarterlyPurchase(
                            country_iso=iso,
                            country_name=cname_zh,
                            quarter=quarter_label,
                            tonnes_net=part,
                            source=source,
                            data_date=_quarter_to_data_date(quarter_label),
                        )
                    )
        if results:
            return results
    return []


def _global_quarter_shares(quarters: list[str], today: date | None = None) -> list[float]:
    """全球合计各季占「覆盖期合计」的比例；缺数据则等分兜底。

    例：2026Q1=57.7 / 2026Q2=296.3 ⇒ [0.163, 0.837]。
    """
    n = len(quarters)
    fallback = [1.0 / n] * n
    aggregate = {r.quarter: r.tonnes_net for r in fetch_global_quarterly_aggregate(today=today)}
    values = [aggregate.get(q, 0.0) for q in quarters]
    total = sum(values)
    if total <= 0:
        return fallback
    return [v / total for v in values]


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


async def build_full_dataset(
    start: str = "2020-01", end: str | None = None
) -> list[QuarterlyPurchase]:
    """编排：拉 WGC 全球季度合计 + 手工补丁 + WGC 国别明细。

    ⚠️ 两者的口径**不同**，不可相加：
    - 全球合计（WGC_AGGR）= WGC 对全部央行的**估算**（含未披露国家的估算）；
    - 国别明细 = **已上报**（reported）国家的实际披露值。

    ⚠️ **手工补丁排在国别明细之前**（V0.121.4 修）：
    upsert 是「同键后写覆盖」，所以列表里**靠后**的才生效。
    原来手工补丁排在最后 ⇒ 它会覆盖 WGC 自己的国别数据 ——
    实测 UZB 2026 H1：WGC Chart 9 = **41.4 吨**，手工估读 = 4 吨
    （差 10 倍）。现在改成「手工补丁只填空缺，WGC 有数时以 WGC 为准」。
    """

    def _fetch_all():
        items: list[QuarterlyPurchase] = []
        items.extend(fetch_global_quarterly_aggregate())
        items.extend(load_manual_overrides())
        items.extend(fetch_2026_by_country())
        return items

    return await asyncio.to_thread(_fetch_all)
