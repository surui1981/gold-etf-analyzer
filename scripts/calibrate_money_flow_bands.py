#!/usr/bin/env python
"""资金流面阈带标定脚本（V0.120.0）。

用**真实历史**算出 6 个资金流因子的 P10 / P90 阈带，输出 JSON。
这些值就是 ``services/money_flow.py::MONEY_FLOW_FACTOR_RULES`` 里
``best`` / ``worst`` 的来源（冷启动期、滚动分位样本不足时的静态兜底）。

跑法::

    .venv/bin/python scripts/calibrate_money_flow_bands.py --out /tmp/bands.json

⚠ 脚本会**打外网**（CFTC / FRED / 上交所 / akshare），跑一次约 3~5 分钟。
"""

from __future__ import annotations

import argparse
import io
import itertools
import json
import sys
import time
import urllib.request
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
SSE_HEADERS = {"Referer": "https://www.sse.com.cn/", "User-Agent": BROWSER_UA}
SSE_URL = (
    "https://query.sse.com.cn/commonQuery.do?isPagination=true&pageHelp.pageSize=10000"
    "&pageHelp.pageNo=1&pageHelp.beginPage=1&pageHelp.cacheSize=1&pageHelp.endPage=1"
    "&sqlId=COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L&STAT_DATE={d}"
)
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
CFTC_URL = "https://www.cftc.gov/files/dea/history/fut_disagg_txt_{y}.zip"

ETF_SYMBOL = "518880"


def _get(url: str, headers: dict | None = None, timeout: int = 40) -> bytes:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def pct(sorted_values: list[float], p: float) -> float:
    """线性插值 percentile（与 numpy.percentile(method='linear') 一致）。"""
    n = len(sorted_values)
    if n == 0:
        return float("nan")
    if n == 1:
        return float(sorted_values[0])
    rank = (p / 100.0) * (n - 1)
    lo = int(rank)
    hi = min(lo + 1, n - 1)
    frac = rank - lo
    return float(sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac)


def band(values: list[float]) -> dict:
    s = sorted(values)
    return {
        "n": len(s),
        "min": round(s[0], 4),
        "p10": round(pct(s, 10), 4),
        "p50": round(pct(s, 50), 4),
        "p90": round(pct(s, 90), 4),
        "max": round(s[-1], 4),
    }


def week_end_days(trading_days: list[date], today: date | None = None) -> list[date]:
    """每个**已过完的周**的最后一个交易日（与 ``app.repositories.money_flow_sources``
    里的同名函数同款）—— 周频因子的采样网格。

    ⚠️ 网格必须与实时采集一致（那里也锚在周末日上）：
    若这里用「每 7 个交易日」、那里用「最新交易日」，两张网格会并存。
    """
    today = today or date.today()
    offset = (today.weekday() - 4) % 7 or 7
    last_friday = today - timedelta(days=offset)
    by_week: dict[tuple[int, int], date] = {}
    for d in trading_days:
        iso = d.isocalendar()
        key = (iso[0], iso[1])
        if key not in by_week or d > by_week[key]:
            by_week[key] = d
    ends = [
        last_day
        for (year, week), last_day in by_week.items()
        if date.fromisocalendar(year, week, 5) <= last_friday
    ]
    return sorted(ends)


def _month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def month_end_days(observation_days: list[date], today: date | None = None) -> list[date]:
    """每个**已过完的月**的月末锚点（与 ``app.repositories.money_flow_sources``
    里的同名函数同款）—— 月频因子的采样网格。

    ⚠️ 网格必须与实时采集一致（那里也锚在月末上）：
    若这里按周采样、那里按月采样，两张网格会并存 ⇒ 同一个月被计入两次。
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
            break
        ends.append(end)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return ends


def asof_series(points: list[tuple[date, float]]):
    """返回「取 d 当天或之前最近一条观测值」的查表函数（points 须升序）。"""
    dates = [d for d, _ in points]
    values = [v for _, v in points]

    def _asof(d: date) -> float | None:
        idx = -1
        for i, x in enumerate(dates):
            if x <= d:
                idx = i
            else:
                break
        return values[idx] if idx >= 0 else None

    return _asof


# ───────────────────── 1. CFTC 黄金投机净多 ─────────────────────


def calc_cftc() -> dict:
    frames = []
    for year in range(2019, date.today().year + 1):
        cache = Path(f"/tmp/cftc_gold_{year}.csv")
        if cache.exists():
            frames.append(pd.read_csv(cache))
            continue
        raw = _get(CFTC_URL.format(y=year), headers={"User-Agent": BROWSER_UA})
        zf = zipfile.ZipFile(io.BytesIO(raw))
        # CFTC 的年度包里是 ``f_year.txt``（逗号分隔 + 引号），不是 .csv
        name = next(n for n in zf.namelist() if n.lower().endswith((".csv", ".txt")))
        with zf.open(name) as f:
            one = pd.read_csv(io.BytesIO(f.read()), encoding="latin-1", low_memory=False)
        # 只留黄金那几十行再缓存 —— 全量 18MB 存磁盘没必要
        keep = one[one["CFTC_Contract_Market_Code"] == "088691"].copy()
        keep.to_csv(cache, index=False)
        frames.append(keep)
        time.sleep(0.4)
    rd = pd.concat(frames, ignore_index=True)
    g = rd.copy()
    # 列名是 ``As_of_Date_In_Form_YYMMDD``（YYMMDD），不是 ``As_of Date``
    g["d"] = pd.to_datetime(g["As_of_Date_In_Form_YYMMDD"], format="%y%m%d")
    g = g.sort_values("d")
    g["net"] = g["M_Money_Positions_Long_All"] - g["M_Money_Positions_Short_All"]
    g["oi"] = g["Open_Interest_All"]
    g["net_pct_oi"] = g["net"] / g["oi"] * 100.0
    g["chg4"] = g["net"] - g["net"].shift(4)
    out = {
        "weeks": len(g),
        "first": str(g["d"].iloc[0].date()),
        "last": str(g["d"].iloc[-1].date()),
        "cot_gold_net": band(g["net_pct_oi"].dropna().tolist()),
        "cot_gold_flow": band(g["chg4"].dropna().tolist()),
        "latest": {
            "date": str(g["d"].iloc[-1].date()),
            "net": int(g["net"].iloc[-1]),
            "oi": int(g["oi"].iloc[-1]),
            "net_pct_oi": round(float(g["net_pct_oi"].iloc[-1]), 4),
            "chg4": int(g["chg4"].iloc[-1]) if pd.notna(g["chg4"].iloc[-1]) else None,
        },
    }
    # 近 8 周明细（供人工核对方向）
    out["recent"] = [
        {
            "date": str(r["d"].date()),
            "net": int(r["net"]),
            "net_pct_oi": round(float(r["net_pct_oi"]), 3),
            "chg4": None if pd.isna(r["chg4"]) else int(r["chg4"]),
        }
        for _, r in g.tail(8).iterrows()
    ]
    return out


# ───────────────────── 2. FRED 美元净流动性 ─────────────────────


def fred_series(sid: str) -> list[tuple[date, float]]:
    text = _get(FRED_URL.format(sid=sid)).decode("utf-8", "ignore")
    out = []
    for line in text.splitlines()[1:]:
        parts = line.split(",")
        if len(parts) < 2:
            continue
        raw_v = parts[1].strip()
        if not raw_v or raw_v == ".":
            continue
        try:
            out.append((date.fromisoformat(parts[0].strip()), float(raw_v)))
        except ValueError:
            continue
    return out


def calc_us_liq() -> dict:
    """美元净流动性 —— **月频**观测（与实时采集同款：月末锚点 + as-of 取值）。

    ⚠️ 源数据是周更，但本因子取的是「4 周变化」⇒ 相邻两次观测重叠 3/4。
    按周采样会让有效样本数只剩名义值的 1/4 ⇒ 静态带会**过窄**（看起来样本很多，
    其实高度重叠）。所以静态带必须与实时采集同网格（月末）。
    """
    walcl = dict(fred_series("WALCL"))
    tga = dict(fred_series("WTREGEN"))
    rrp = dict(fred_series("RRPONTSYD"))
    rrp_dates = sorted(rrp)

    def _rrp_asof(d: date) -> float | None:
        cand = [x for x in rrp_dates if x <= d]
        return rrp[cand[-1]] if cand else None

    points: list[tuple[date, float]] = []
    for d in sorted(set(walcl) & set(tga)):
        r = _rrp_asof(d)
        if r is None:
            continue
        points.append((d, walcl[d] - tga[d] - r))
    if len(points) < 2:
        return {"obs": len(points), "us_liq_net": band([])}

    asof = asof_series(points)
    ends = month_end_days([d for d, _ in points], today=date.today())
    monthly: list[tuple[date, float]] = []
    for prev_end, end in itertools.pairwise(ends):
        cur_v = asof(end)
        prev_v = asof(prev_end)
        if cur_v is None or prev_v is None:
            continue
        monthly.append((end, cur_v - prev_v))
    vals = [v for _, v in monthly]
    return {
        "obs": len(points),
        "months": len(monthly),
        "last_date": str(monthly[-1][0]) if monthly else None,
        "last_netliq": round(points[-1][1], 1),
        "us_liq_net": band(vals),
        # 与滚动分位窗口一致（60 个月）—— 静态兜底带应贴近滚动带
        "us_liq_net_60m": band(vals[-60:]),
        "latest": {
            "month_end": str(monthly[-1][0]) if monthly else None,
            "change": round(monthly[-1][1], 1) if monthly else None,
        },
    }


# ───────────────────── 3. 黄金 ETF 4 周累计净申赎 ─────────────────────


def sse_shares(d: date) -> float | None:
    """上交所官方 ETF 基金份额（万份）。"""
    try:
        raw = _get(SSE_URL.format(d=d.isoformat()), headers=SSE_HEADERS)
        payload = json.loads(raw)
    except Exception as exc:
        print(f"  SSE {d} 失败: {exc}", file=sys.stderr)
        return None
    result = payload.get("result")
    if not result:
        return None
    for row in result:
        if row.get("SEC_CODE") == ETF_SYMBOL:
            return float(row["TOT_VOL"])
    return None


def calc_etf() -> dict:
    import akshare as ak

    px = ak.fund_etf_hist_sina(symbol="sh518880")
    closes = {}
    trading_days = []
    for _, r in px.iterrows():
        d = r["date"]
        d = d.date() if hasattr(d, "date") else date.fromisoformat(str(d))
        closes[d] = float(r["close"])
        trading_days.append(d)
    trading_days = sorted(trading_days)

    # 采样点必须落在**交易日**上 —— 上交所接口对非交易日返回 result=null。
    # 网格锚在 **ISO 周的最后一个交易日**（与实时采集 / 回填同款）。
    today = date.today()
    start = today - timedelta(days=3 * 365)
    sample_dates = [d for d in week_end_days(trading_days, today=today) if d >= start]
    if not sample_dates:
        return {"samples": 0, "gold_etf_flow": band([])}

    shares: dict[date, float] = {}
    for sd in sample_dates:
        v = sse_shares(sd)
        if v is not None:
            shares[sd] = v
        time.sleep(0.2)
    print(f"  SSE 采样 {len(shares)}/{len(sample_dates)} 个日期有数据", file=sys.stderr)

    flows = []
    for sd, sh in sorted(shares.items()):
        prev = sd - timedelta(days=28)
        cand = [k for k in shares if abs((k - prev).days) <= 7]
        if not cand:
            continue
        p = min(cand, key=lambda k: abs((k - prev).days))
        near = [k for k in closes if abs((k - sd).days) <= 5]
        if not near:
            continue
        close = closes[min(near, key=lambda k: abs((k - sd).days))]
        d_wan = sh - shares[p]
        flows.append(d_wan * close / 1e4)  # 万份 × 元/份 → 亿元
    return {
        "samples": len(shares),
        "gold_etf_flow": band(flows),
        "latest_shares_wan": shares.get(max(shares)) if shares else None,
    }


# ───────────────────── 4/5. A股融资余额 & M1-M2 剪刀差 ─────────────────────


def calc_cn() -> dict:
    import akshare as ak

    sh = ak.macro_china_market_margin_sh()
    sz = ak.macro_china_market_margin_sz()
    sh["日期"] = pd.to_datetime(sh["日期"])
    sz["日期"] = pd.to_datetime(sz["日期"])
    m = sh.merge(sz, on="日期", suffixes=("_sh", "_sz"))
    m["total"] = m["融资余额_sh"] + m["融资余额_sz"]
    m = m.sort_values("日期")
    monthly = m.set_index("日期")["total"].resample("ME").last().dropna()
    # ⚠️ 丢掉**还没过完**的当月：它的「月末值」其实是月内至今值，
    # 与历史行的「月末 vs 月末」不是同一个量（实时采集也只取已过完的月份）。
    today = date.today()
    if (
        len(monthly)
        and monthly.index[-1].year == today.year
        and monthly.index[-1].month == today.month
    ):
        monthly = monthly.iloc[:-1]
    mom = (monthly / monthly.shift(1) - 1) * 100.0
    mom = mom.dropna()

    ms = ak.macro_china_money_supply()
    ms["月份"] = ms["月份"].astype(str)
    ms["年"] = ms["月份"].str[:4].astype(int)
    ms["月"] = ms["月份"].str[5:7].astype(int)
    ms = ms.sort_values(["年", "月"])  # akshare 返回**最新在前**，这里转升序
    m1 = ms["货币(M1)-同比增长"].astype(float)
    m2 = ms["货币和准货币(M2)-同比增长"].astype(float)
    gap = pd.DataFrame({"年": ms["年"], "gap": (m1 - m2)}).dropna()
    gap = gap[gap["年"] >= 2015]

    return {
        "cn_margin_flow": band(mom.tolist()),
        # 与滚动分位窗口一致（60 个月）—— 静态兜底带应贴近滚动带
        "cn_margin_flow_60m": band(mom.tolist()[-60:]),
        "margin_months": len(mom),
        "cn_money_gap": band(gap["gap"].tolist()),
        "cn_money_gap_60m": band(gap["gap"].tolist()[-60:]),
        "money_supply_months": len(gap),
        "latest": {
            "margin_total_yi": round(float(monthly.iloc[-1]) / 1e8, 1),
            "margin_mom_pct": round(float(mom.iloc[-1]), 4),
            "gap_pp": round(float(gap["gap"].iloc[-1]), 4),
            "gap_month": f"{int(gap['年'].iloc[-1])}",
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/money_flow_bands.json")
    args = ap.parse_args()

    out: dict = {}
    print("[1/4] CFTC …", file=sys.stderr)
    out["cot"] = calc_cftc()
    print("[2/4] FRED 美元净流动性 …", file=sys.stderr)
    out["us_liq"] = calc_us_liq()
    print("[3/4] 上交所 ETF 份额 …", file=sys.stderr)
    out["etf"] = calc_etf()
    print("[4/4] A股融资余额 + M1/M2 …", file=sys.stderr)
    out["cn"] = calc_cn()

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
