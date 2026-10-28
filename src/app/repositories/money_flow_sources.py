"""资金流面的数据源（V0.120.0）。

6 个因子、5 个数据源，全部**实测可用**（2026-10-27 逐个跑通）：

======================  ==================  ==========================
因子                     源                   实测最新
======================  ==================  ==========================
``cot_gold_net``        CFTC 分类持仓年报    2026-10-20 净多占 OI 25.90%
``cot_gold_flow``       同上（派生 4 周变化）  -23,183 张
``gold_etf_flow``       **上交所官方 ETF 份额**  近 4 周累计净申赎
``us_liq_net``          FRED WALCL/TGA/RRP   4 周变化 +14,170 $M（月末锚点）
``cn_margin_flow``      akshare 沪深融资余额  月环比 -5.65%
``cn_money_gap``        akshare 央行 M1/M2    剪刀差 -4.0 pp
======================  ==================  ==========================

关于黄金 ETF 份额的口径修正（V0.120.0 实测发现）
------------------------------------------------
计划初稿打算用「成交量 ÷ 换手率」**重建**份额（东财 kline 只有成交额和换手率），
并据此判定信噪比约 1、不可用。实测时发现**上交所有官方每日 ETF 份额接口**
（``query.sse.com.cn`` 的 ``COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L``），
直接给出 ``TOT_VOL``（基金份额，单位万份）——

- 2026-10-22：1,221,434.08 万份
- 2026-10-26：1,206,314.08 万份（较 4 天前 **净赎回 5,120 万份**）

⇒ 重建口径整条废弃：官方份额**没有 ±0.2% 的量化误差**，也不需要排除未收盘 bar
（份额是交易所结算后的存量，本来就不含盘中噪声）。这是「先实测再定口径」
直接改掉设计的例子 —— 计划里的「信噪比≈1 不可用」结论建立在错的源上。

其余口径提醒
------------
- **CFTC**：分类持仓（disaggregated）年报 ``fut_disagg_txt_YYYY.zip``，
  包内文件名是 ``f_year.txt``（逗号分隔 + 引号）。管理基金（Managed Money）
  的多空才是「投机盘」口径 —— 商业套保（Producer）不是。
- **美元净流动性** = WALCL − WTREGEN − RRPONTSYD（美联储总资产 − 国库券 − 逆回购）。
  用 **4 周变化**而非 1 周：1 周变化被 TGA 季度末摆动主导（实测 P10/P90 ±9 万 $M，
  当期值已跌出分位带）。
  ⚠️ **观测网格是月频**（月末锚点 + as-of 取值），尽管源数据是周更（H.4.1 每周三）：
  本因子取的是「4 周变化」，相邻两次观测**重叠 3/4** ⇒ 按周落表会让有效样本数
  只剩名义值的 1/4（同一个量被重复计入滚动分位窗口）。
- **A 股融资余额**：沪深两市「融资余额」相加（元），取**月末**值算环比。
- **M1/M2 剪刀差**：M1 同比 − M2 同比（百分点）。akshare 的
  ``macro_china_money_supply`` 返回**最新在前**（索引 0 是当月），别用 ``tail``。
"""

from __future__ import annotations

import asyncio
import csv
import io
import itertools
import json
import time
import urllib.request
import zipfile
from bisect import bisect_right
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.utils.logger import get_logger

logger = get_logger(__name__)


def week_end_days(
    trading_days: Iterable[date],
    today: date | None = None,
) -> list[date]:
    """每个**已过完的周**的最后一个交易日（周频因子的观测锚点）。

    ⚠️ 为什么不用「每 7 个交易日」：周频因子的观测日必须**稳定**。

    实时采集每天都会跑。若窗口末日跟着「最新交易日」走，历史表里就会一天一行 ——
    而 4 周累计窗口在相邻几天里几乎是同一个数 ⇒ **同一周被重复计入**
    滚动分位窗口 ⇒ 样本量虚高、近期状态被过度加权。
    锚在「每周最后一个交易日」上，实时采集与回填落在**同一张网格**上，
    每个观测周期恰好一行。

    ⚠️「已过完」的判定：某一周的**周五**是否已经过去（严格早于今天）。
    - 周五当天的收盘数据在盘中还没定 ⇒ 本周不算完；
    - 周六/周日则本周已定 ⇒ 锚点 = 周五（或假期缩短后的最后交易日）。

    这样锚点在**一周内不会移动**（本周的锚点要等周五过了才出现），
    跨周才前进一格 ⇒ 正好是「周频」。

    Args:
        trading_days: 交易日序列（升序或乱序都行）。
        today: 「今天」；默认取系统日期。

    Returns:
        升序的周末日列表（每个已过完的周一个）。
    """
    today = today or date.today()
    # 「今天」之前最近的一个周五（strictly before）——
    # 周五当天不算（盘中数据未定），所以偏移为 0 时取 7 天。
    offset = (today.weekday() - 4) % 7 or 7
    last_friday = today - timedelta(days=offset)

    by_week: dict[tuple[int, int], date] = {}
    for d in trading_days:
        iso = d.isocalendar()
        key = (iso[0], iso[1])
        if key not in by_week or d > by_week[key]:
            by_week[key] = d
    ends: list[date] = []
    for (year, week), last_day in by_week.items():
        friday = date.fromisocalendar(year, week, 5)
        if friday <= last_friday:
            ends.append(last_day)
    return sorted(ends)


def _month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def month_end_days(
    observation_days: Iterable[date],
    today: date | None = None,
) -> list[date]:
    """每个**已过完的月**的月末锚点（月频因子的观测网格）。

    与 :func:`week_end_days` 同款：**观测锚点由日历决定**，不随最新数据推进。

    ⚠️ 为什么月频因子不能「跟着最新观测走」：
    每日调度一天写一行 ⇒ 同一个月被重复计入滚动分位窗口 ⇒ 样本量虚高、
    当月被过度加权。更糟的是，若因子本身是「变化量」（如 4 周变化），
    相邻两次观测**重叠 3/4** ⇒ 有效样本数只有名义值的 1/4。

    ⚠️「已过完」的判定：月末是否**早于**当月的最后一天。
    当月的「月末」其实是月内至今 ⇒ 与历史行的「月末 vs 月末」不是同一个量。

    锚点是**日历月末**（不要求当天真的有观测）—— 观测值按「该月末当天或之前
    最近的一条」取值（as-of），所以月末落在周末/假期上也没关系。

    Args:
        observation_days: 源数据的观测日序列（升序或乱序都行；只用来定起点与上界）。
        today: 「今天」；默认取系统日期。

    Returns:
        升序的月末列表（每个已过完的月一个）。
    """
    today = today or date.today()
    days = sorted(set(observation_days))
    if not days:
        return []
    cur_end = _month_end(today.year, today.month)
    ends: list[date] = []
    year, month = days[0].year, days[0].month
    while True:
        end = _month_end(year, month)
        if end >= cur_end:
            # 当月还没过完（或已到今天所在月的月末）⇒ 停
            break
        ends.append(end)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return ends


def asof_series(
    points: list[tuple[date, float]],
) -> Callable[[date], float | None]:
    """返回一个「取 d 当天或之前最近一条观测值」的查表函数。

    ``points`` 必须按日期升序。月末锚点常常落在周末/假期上（当天没有观测），
    所以取「月末当天或之前最近的一条」。
    """

    dates = [d for d, _ in points]
    values = [v for _, v in points]

    def _asof(d: date) -> float | None:
        idx = bisect_right(dates, d) - 1
        if idx < 0:
            return None
        return values[idx]

    return _asof


#: 需要浏览器 UA 的源（上交所 / CFTC）
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

# ───────────────────── CFTC ─────────────────────

#: CFTC 分类持仓（disaggregated）年度压缩包
CFTC_DISAGG_URL = "https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip"

#: 黄金（COMEX 期货）合约代码 —— CFTC 的「市场代码」，不是交易所代码
CFTC_GOLD_MARKET_CODE = "088691"

#: CFTC 源标识
CFTC_SOURCE = "CFTC 分类持仓"

#: 年度包缓存有效期（秒）—— 年度文件每周追加一次，6 小时足够新鲜
_CFTC_TTL = 6 * 3600
_CFTC_CACHE: dict[int, tuple[float, list[CotPoint]]] = {}


@dataclass(frozen=True)
class CotPoint:
    """CFTC 黄金投机（管理基金）持仓的一周观测。"""

    obs_date: date
    net_long: int
    """管理基金多空净持仓（张）"""
    open_interest: int
    """该合约总持仓（张）"""
    net_pct_oi: float
    """净多占总持仓比例（%）"""


def _http_bytes(url: str, headers: dict | None = None, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _parse_cftc_gold(text: str) -> list[CotPoint]:
    """从分类持仓 CSV 文本里抽出黄金（``088691``）的每周观测。

    用标准库 ``csv`` 逐行扫，不用 pandas —— 年度包 18MB / 60 万行，
    pandas 全量载入既慢又占内存，而真正要的只有黄金那几十行。
    """
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return []
    idx = {name: i for i, name in enumerate(header)}
    need = (
        "CFTC_Contract_Market_Code",
        "As_of_Date_In_Form_YYMMDD",
        "M_Money_Positions_Long_All",
        "M_Money_Positions_Short_All",
        "Open_Interest_All",
    )
    missing = [c for c in need if c not in idx]
    if missing:
        logger.warning("CFTC 分类持仓缺列 %s（跳过该年度文件）", missing)
        return []
    out: list[CotPoint] = []
    for row in reader:
        if len(row) <= idx["Open_Interest_All"]:
            continue
        if row[idx["CFTC_Contract_Market_Code"]].strip() != CFTC_GOLD_MARKET_CODE:
            continue
        try:
            obs = datetime.strptime(row[idx["As_of_Date_In_Form_YYMMDD"]], "%y%m%d").date()
            long_ = int(float(row[idx["M_Money_Positions_Long_All"]] or 0))
            short_ = int(float(row[idx["M_Money_Positions_Short_All"]] or 0))
            oi = int(float(row[idx["Open_Interest_All"]] or 0))
        except (ValueError, TypeError):
            continue
        net = long_ - short_
        out.append(
            CotPoint(
                obs_date=obs,
                net_long=net,
                open_interest=oi,
                net_pct_oi=(net / oi * 100.0) if oi else 0.0,
            )
        )
    out.sort(key=lambda p: p.obs_date)
    return out


def _cftc_year(year: int) -> list[CotPoint]:
    """取某一年份的黄金观测（带进程内缓存）。"""
    hit = _CFTC_CACHE.get(year)
    if hit is not None and (time.time() - hit[0]) < _CFTC_TTL:
        return hit[1]
    url = CFTC_DISAGG_URL.format(year=year)
    raw = _http_bytes(url, headers={"User-Agent": BROWSER_UA}, timeout=90)
    zf = zipfile.ZipFile(io.BytesIO(raw))
    names = [n for n in zf.namelist() if n.lower().endswith((".csv", ".txt"))]
    if not names:
        logger.warning("CFTC %s 年度包里没有数据文件: %s", year, zf.namelist())
        return []
    with zf.open(names[0]) as f:
        text = f.read().decode("latin-1", "ignore")
    points = _parse_cftc_gold(text)
    _CFTC_CACHE[year] = (time.time(), points)
    return points


async def fetch_cftc_gold_positions(min_points: int = 8) -> list[CotPoint]:
    """CFTC 黄金投机净持仓周度序列（升序）。

    只取**本年 + 上年**两个年度包：4 周变化需要最近 5 周观测，
    跨年时（1 月初）必须把上一年也带上。``min_points`` 不足时自动补上一年。
    """
    try:
        return await asyncio.to_thread(_cftc_gold_positions_sync, min_points)
    except Exception as exc:
        logger.warning("CFTC 取数失败: %s", exc)
        return []


def _cftc_gold_positions_sync(min_points: int) -> list[CotPoint]:
    today = date.today()
    points = list(_cftc_year(today.year))
    if len(points) < min_points:
        points = list(_cftc_year(today.year - 1)) + points
    return points


async def fetch_cftc_gold_history(years: int = 3) -> list[CotPoint]:
    """CFTC 黄金投机净持仓的**多年**周度序列（升序、按观测日去重）。

    与 :func:`fetch_cftc_gold_positions` 的区别：后者只取「本年 + 上年」
    （够算一次 4 周变化），而**滚动分位回填**需要 104 周（728 天）的历史 ——
    窗口不够 ⇒ 样本不足 ⇒ 阈值永远退回静态阈带。

    ``years`` 是回看的**自然年**个数（含当年）。每个年度包 18MB，
    所以别一次要太多年 —— 回填 728 天只要 3 年即可。
    """
    try:
        return await asyncio.to_thread(_cftc_gold_history_sync, years)
    except Exception as exc:
        logger.warning("CFTC 多年历史取数失败: %s", exc)
        return []


def _cftc_gold_history_sync(years: int) -> list[CotPoint]:
    today = date.today()
    merged: dict[date, CotPoint] = {}
    for y in range(today.year - years + 1, today.year + 1):
        for p in _cftc_year(y):
            merged[p.obs_date] = p
    return [merged[d] for d in sorted(merged)]


# ───────────────────── 上交所 ETF 份额 ─────────────────────

#: 上交所 ETF 基金规模（基金份额）查询
SSE_ETF_SCALE_URL = (
    "https://query.sse.com.cn/commonQuery.do?isPagination=true&pageHelp.pageSize=10000"
    "&pageHelp.pageNo=1&pageHelp.beginPage=1&pageHelp.cacheSize=1&pageHelp.endPage=1"
    "&sqlId=COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L&STAT_DATE={stat_date}"
)
SSE_HEADERS = {"Referer": "https://www.sse.com.cn/", "User-Agent": BROWSER_UA}

#: 上交所源标识
SSE_SOURCE = "上交所 ETF 份额"

#: 黄金 ETF（华安黄金 ETF）代码
GOLD_ETF_SYMBOL = "518880"

#: SSE 份额接口缓存（秒）—— 每日更新一次，1 小时足够
_SSE_TTL = 3600
_SSE_CACHE: dict[tuple[str, str], tuple[float, float | None]] = {}


def _sse_shares_sync(symbol: str, on: date) -> float | None:
    key = (symbol, on.isoformat())
    hit = _SSE_CACHE.get(key)
    if hit is not None and (time.time() - hit[0]) < _SSE_TTL:
        return hit[1]
    url = SSE_ETF_SCALE_URL.format(stat_date=on.isoformat())
    try:
        raw = _http_bytes(url, headers=SSE_HEADERS, timeout=40)
        payload = json.loads(raw)
    except Exception as exc:
        logger.warning("上交所 ETF 份额取数失败 (%s): %s", on, exc)
        return None
    result = payload.get("result")
    value: float | None = None
    if result:
        for row in result:
            if row.get("SEC_CODE") == symbol:
                try:
                    value = float(row["TOT_VOL"])
                except (KeyError, TypeError, ValueError):
                    value = None
                break
    _SSE_CACHE[key] = (time.time(), value)
    return value


async def fetch_sse_etf_shares(symbol: str, on: date) -> float | None:
    """上交所官方 ETF 基金份额（**万份**）；无数据返回 ``None``。

    ``on`` 必须是**交易日**（非交易日该接口返回 ``result: null``）。
    """
    try:
        return await asyncio.to_thread(_sse_shares_sync, symbol, on)
    except Exception as exc:
        logger.warning("上交所 ETF 份额取数失败: %s", exc)
        return None


# ───────────────────── 新浪 ETF 收盘价 ─────────────────────

#: 新浪 ETF 源标识
SINA_SOURCE = "新浪 ETF 收盘价"


async def fetch_sina_etf_closes(symbol: str = "sh518880") -> dict[date, float]:
    """新浪 ETF 日线收盘价 → ``{日期: 收盘价}``；失败返回空字典。

    只用来把「份额变化」换算成「金额变化」（净申赎金额 = Δ份额 × 收盘价）。
    """
    try:
        return await asyncio.to_thread(_sina_closes_sync, symbol)
    except Exception as exc:
        logger.warning("新浪 ETF 收盘价取数失败: %s", exc)
        return {}


def _sina_closes_sync(symbol: str) -> dict[date, float]:
    import akshare as ak

    df = ak.fund_etf_hist_sina(symbol=symbol)
    out: dict[date, float] = {}
    for _, row in df.iterrows():
        try:
            d = row["date"]
            d = d.date() if hasattr(d, "date") else date.fromisoformat(str(d))
            out[d] = float(row["close"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


# ───────────────────── 美元净流动性（FRED） ─────────────────────

#: 净流动力的三个 FRED 序列：美联储总资产 − 国库券 − 逆回购
US_LIQ_SERIES: tuple[str, ...] = ("WALCL", "WTREGEN", "RRPONTSYD")

#: 美元净流动性源标识
US_LIQ_SOURCE = "FRED WALCL-WTREGEN-RRPONTSYD"


async def fetch_us_net_liquidity_monthly(
    today: date | None = None,
) -> list[tuple[date, float, date]]:
    """美元净流动力的**月频**观测 → ``[(月末锚点, 与上月末的差值, 上月末锚点), ...]``。

    净流动性 = WALCL（美联储总资产）− WTREGEN（国库券）− RRPONTSYD（逆回购）。

    ⚠️ **观测网格是月频**（每个已过完的月一行），不是周频：
    源数据本身是周更（H.4.1 每周三），但本因子取的是「4 周变化」——
    相邻两次观测**重叠 3/4** ⇒ 按周落表会让有效样本数只剩名义值的 1/4
    （同一个量被重复计入滚动分位窗口，与 §4.1 的「按观测数而不是日历天」同源）。
    ⇒ 改成月末锚点：每个月一行，相邻两个月的变化窗口 ≈ 4.4 周。

    Args:
        today: 「今天」；默认取系统日期。决定哪个月算「已过完」。
    """
    from app.config import get_settings
    from app.repositories.macro_sources import fetch_fred_series

    cfg = get_settings()
    series: dict[str, dict[date, float]] = {}
    for sid in US_LIQ_SERIES:
        rows = await fetch_fred_series(sid, base_url=cfg.fred_csv_url)
        if not rows:
            logger.warning("FRED %s 无数据，us_liq_net 暂缺", sid)
            return []
        series[sid] = dict(rows)

    walcl = series["WALCL"]
    tga = series["WTREGEN"]
    rrp = series["RRPONTSYD"]
    rrp_dates = sorted(rrp)

    def _rrp_asof(d: date) -> float | None:
        cand = [x for x in rrp_dates if x <= d]
        if not cand:
            return None
        return rrp[cand[-1]]

    points: list[tuple[date, float]] = []
    for d in sorted(set(walcl) & set(tga)):
        r = _rrp_asof(d)
        if r is None:
            continue
        points.append((d, walcl[d] - tga[d] - r))
    if len(points) < 2:
        return []

    asof = asof_series(points)
    ends = month_end_days([d for d, _ in points], today=today)
    out: list[tuple[date, float, date]] = []
    for prev_end, end in itertools.pairwise(ends):
        cur_v = asof(end)
        prev_v = asof(prev_end)
        if cur_v is None or prev_v is None:
            continue
        out.append((end, cur_v - prev_v, prev_end))
    return out


# ───────────────────── A 股融资余额 ─────────────────────

#: 沪深交易所融资余额源标识
MARGIN_SOURCE = "akshare 沪深融资余额"


async def fetch_cn_margin_balances() -> list[tuple[date, float]]:
    """沪深两市「融资余额」合计日频序列 → ``[(日期, 余额元), ...]``（升序）。

    失败返回空列表。上交所 + 深交所各一次调用（两个独立接口）。
    """
    try:
        return await asyncio.to_thread(_cn_margin_sync)
    except Exception as exc:
        logger.warning("A股融资余额取数失败: %s", exc)
        return []


def _parse_ymd(value) -> date | None:
    """把 akshare 返回的日期列解析成 ``date``。

    ⚠ 不用 pandas：``check_deps.py`` 要求 src/ 里出现的每个三方 import 都**显式**
    声明在 pyproject 依赖里，而 pandas 只是 akshare 的传递依赖（本仓库不直接依赖它）。
    akshare 的「日期」列实测是 object 类型的 ``"2010-03-31"`` 字符串，
    但不同接口可能给 ``date``/``datetime`` 对象 —— 三种都兼容。
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _cn_margin_sync() -> list[tuple[date, float]]:
    import akshare as ak

    sh = ak.macro_china_market_margin_sh()
    sz = ak.macro_china_market_margin_sz()
    # 两个交易所各自建 {日期: 融资余额} 映射再取交集 ——
    # 不用 DataFrame.merge（那会把 pandas 拖进 src/ 的直接依赖）。
    sh_map: dict[date, float] = {}
    for d, v in zip(sh["日期"], sh["融资余额"], strict=True):
        day = _parse_ymd(d)
        if day is not None:
            sh_map[day] = float(v)
    sz_map: dict[date, float] = {}
    for d, v in zip(sz["日期"], sz["融资余额"], strict=True):
        day = _parse_ymd(d)
        if day is not None:
            sz_map[day] = float(v)
    common = sorted(set(sh_map) & set(sz_map))
    return [(d, sh_map[d] + sz_map[d]) for d in common]


# ───────────────────── 中国 M1 / M2 ─────────────────────

#: 央行货币供应量源标识
MONEY_SUPPLY_SOURCE = "央行 M1/M2"


async def fetch_cn_money_supply() -> list[tuple[date, float, float]]:
    """中国 M1/M2 同比 → ``[(月末日, M1同比%, M2同比%), ...]``（升序）。

    ⚠ akshare 的 ``macro_china_money_supply`` 返回**最新在前**（索引 0 是当月），
    且「月份」列是 ``"2026年09月份"`` 形式 —— 这里统一解析成**月末日**并转升序。
    """
    try:
        return await asyncio.to_thread(_money_supply_sync)
    except Exception as exc:
        logger.warning("央行 M1/M2 取数失败: %s", exc)
        return []


def _money_supply_sync() -> list[tuple[date, float, float]]:
    import akshare as ak

    df = ak.macro_china_money_supply()
    out: list[tuple[date, float, float]] = []
    for _, row in df.iterrows():
        label = str(row["月份"])
        # "2026年09月份" → (2026, 9)
        try:
            body = label.replace("月份", "").replace("年", "-").replace("月", "")
            year_s, month_s = body.split("-")
            year, month = int(year_s), int(month_s)
        except (AttributeError, ValueError):
            continue
        if month == 12:
            month_end = date(year, 12, 31)
        else:
            month_end = date(year, month + 1, 1) - timedelta(days=1)
        try:
            m1 = float(row["货币(M1)-同比增长"])
            m2 = float(row["货币和准货币(M2)-同比增长"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append((month_end, m1, m2))
    out.sort(key=lambda t: t[0])
    return out


def clear_money_flow_sources_cache() -> None:
    """清空本模块的进程内缓存（测试隔离 / 强制刷新）。"""
    _CFTC_CACHE.clear()
    _SSE_CACHE.clear()
