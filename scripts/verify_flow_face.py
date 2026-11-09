#!/usr/bin/env python3
"""资金流面的**可复算证据**脚本（V0.123.0）。

背景
----
V0.122.0 把 ``cot_gold_net`` 的符号从「+」改成「−」（拥挤度口径），
依据是「净多占 OI 的年内五分位，Q1（最不拥挤）比 Q5（最拥挤）的前瞻 60 交易日收益高 5.84pp」。
那个**单因子**结论用 ``scripts/verify_cot_sign.py`` 可以逐位复现。

但同一版材料里还有一条**composite 级**结论：

    「资金流面 composite：现状 前瞻/回看 +0.188/+0.214 → 改号后 +0.235/+0.120（前瞻主导）」

这条**复现不出来**，两个原因（本脚本 §2 会把两者都打印出来对照）：

1. **数据源坏了**：当时用的 ETF 份额序列是错的（13 年平铺在 ~1,180,000 万份，
   还带 6 个 ``inf`` 和一个 600,000 的地板值），而 ``gold_etf_flow`` 恰恰是
   资金流面**权重最大的因子（22%）** ⇒ composite 的一半重量压在一段噪声上。
2. **口径不对**：那条结论算在 **z 分数**口径上，而生产用的是
   **0-100 打分**口径（滚动分位带 + 截断）—— 两者不是同一个东西。

⇒ 本脚本按**服务真实口径**（滚动带 = ``get_window(days=window_days)`` 返回的
**全部日频行**、分数 = ``_friendly_score`` 的线性 + 截断）重算，并给出
**C5 候选读数**（共识度 / 离散度 / 拥挤度）的三问判决。

三问判据（沿用 ``docs/roadmap.md`` §C4）
--------------------------------------
任何一个「改进数值」的想法，先问三件事：

1. 在**年内去均值 + 非重叠采样 + 控制当期金价水平**之后还剩多少？（残余功效）
2. **前瞻/回看**比值 > 1.3 吗？（对称性 —— 只像回看的因子不是预测因子）
3. **三个子区间**同向吗？（不是某一段行情撑起来的）

三条过不了就不改。

用法
----
    # ① 取数（需联网：CFTC / 上交所 / FRED / Yahoo / 新浪）并落缓存
    PYTHONPATH=src:. python scripts/verify_flow_face.py --fetch --cache data/verify/flow_face_cache.pkl

    # ② 只做分析（不联网，读缓存）
    PYTHONPATH=src:. python scripts/verify_flow_face.py --cache data/verify/flow_face_cache.pkl

⚠ 本脚本**不在 CI 门禁集里**（依赖外网）；但它的**分析函数**有离线单测
（``tests/test_scripts/test_verify_flow_face.py``）⇒ 分析口径本身被 CI 守着。
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import pickle
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
# ⚠ 同目录模块（``_evidence_core``）—— 无论本脚本是「当脚本跑」还是
# 「被 importlib 按路径加载」（离线测试就是这么做的）都要能找到它。
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _evidence_core as core
import numpy as np
import pandas as pd

from app.config import get_settings
from app.repositories.macro_sources import fetch_yahoo_daily
from app.repositories.money_flow_sources import (
    GOLD_ETF_SYMBOL,
    fetch_cftc_gold_history,
    fetch_cn_margin_balances,
    fetch_cn_money_supply,
    fetch_sina_etf_closes,
    fetch_sse_etf_shares,
    fetch_us_net_liquidity_monthly,
    week_end_days,
)
from app.services.money_flow import MONEY_FLOW_FACTOR_RULES

#: 规则表 → {key: rule}（**服务唯一真源** —— 不在这里抄一份权重/方向）
RULES: dict[str, dict] = {r["key"]: r for r in MONEY_FLOW_FACTOR_RULES}
KEYS: list[str] = list(RULES)

#: 前瞻窗口（交易日）
H_FORWARD = 60
#: 分区间的年份切分（与 ``verify_cot_sign.py`` 的 SPANS 对齐，便于两份脚本互相印证）
SPANS = ((2015, 2018), (2019, 2022), (2023, 2026))
#: 对称性判据：|前瞻| / |回看| 必须 > 这个值
RATIO_GATE = 1.3
#: 比值判据的**退化保护**：|回看| 小于这个值时，比值没有意义（分母趋零 ⇒ 比值爆表）
RATIO_FLOOR = 0.05
#: 残余功效门槛（偏相关绝对值）
POWER_GATE = 0.15

#: 核心标的（用户拍板：COMEX/GLD 美元金价）；518880 人民币金价作交叉验证
TARGETS = ("GLD", "518880")


# ───────────────────────── 基础统计 ─────────────────────────
#
# ⚠ **实现已抽到 ``scripts/_evidence_core.py``**（V0.124.0）——
# 与宏观面证据脚本共用**同一份**口径，避免两边各写各的、悄悄漂开。
# 下面这些名字是本脚本的**公开 API**（V0.123.0 的离线测试直接按名字调）
# ⇒ 保留别名，行为逐位不变。

partial_corr = core.partial_corr
fisher_p = core.fisher_p
_within_year_rank = core.within_year_rank
_align_to_price = core.align_to_price
_change_points = core.change_points
_clip_to_observations = core.clip_to_observations
measure = core.measure
measure_spans = core.measure_spans
_quintile_by_order = core.quintile_by_order
_quintile_sample = core.quintile_sample
_agg_quintile = core.agg_quintile
quintile_spread = core.quintile_spread
observation_series = core.observation_series
consensus_readings = core.consensus_readings


def factor_on_calendar(
    factors: pd.DataFrame,
    cot: pd.DataFrame,
    key: str,
    cal: pd.DatetimeIndex,
) -> pd.Series:
    """把因子读数放到**目标自己的日历**上（as-of 语义，不回填未来）。

    ⚠ 日频表建在 518880（A 股）日历上 ⇒ 对美股标的会**滞后 1~2 天**：
    CFTC 的报告日可能落在 A 股休市日（服务当天就能读到新读数，
    日频表却要等下一个 A 股交易日才换值）⇒ 复合分与单因子证据都偏（V0.123.0 修）。

    - 两个 CFTC 因子：**直接**从周频观测前向填充（观测日就是报告日）；
    - 其余 4 个：观测日 ≈ 日频表的**值变化点** ⇒ 取变化点再前向填充。
    """
    if key == "cot_gold_net":
        obs = cot["pct"].sort_index()
    elif key == "cot_gold_flow":
        net = cot["net"].sort_index()
        obs = net - net.shift(4)
    else:
        obs = _change_points(factors[key])
    if obs.empty:
        return pd.Series(index=cal, dtype=float)
    return obs.reindex(cal, method="ffill")


# ───────────────────────── 服务真实打分 ─────────────────────────


def rolling_band(factors: pd.DataFrame, key: str, positive: bool) -> pd.Series:
    """服务口径的滚动分位带（实现见 ``_evidence_core``，规则表绑定资金流面）。"""
    return core.rolling_band(factors, key, positive, RULES[key])


def service_scores(
    factors: pd.DataFrame,
    flip_net: bool = False,
    band_source: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """服务真实打分（0-100，线性 + 截断）—— 与 ``_friendly_score`` 同型。

    Args:
        factors: 6 个因子的**日频原始值**（可以是某个标的自己的日历）。
        flip_net: 把 ``cot_gold_net`` 的符号翻回「+」（V0.122.0 之前的状态），
            用于对照。
        band_source: 滚动分位带的**样本来源**；默认与 ``factors`` 相同。
            生产口径下滚动带来自服务自己的因子历史（与目标标的无关），
            而「因子的当期读数」是**按标的日历 as-of** 的 ⇒ 两者日历可以不同。
    """
    return core.service_scores(
        factors,
        RULES,
        KEYS,
        flip_keys={"cot_gold_net"} if flip_net else None,
        band_source=band_source,
    )


def face_composite(scores: pd.DataFrame) -> pd.Series:
    """资金流面 composite（服务口径：因子分数 × 规则权重之和）。"""
    return core.face_composite(scores, RULES, KEYS)


# ───────────────────────── 单因子方向证据 ─────────────────────────
#
# ⚠ 五分位相关的实现（``_quintile_by_order`` / ``_quintile_sample`` /
# ``_agg_quintile`` / ``quintile_spread``）已随实现移入 ``_evidence_core``，
# 上面的别名保留本脚本的公开 API。


# ───────────────────────── C5 候选读数 ─────────────────────────


def crowding_readings(factors: pd.DataFrame, key: str = "cot_gold_net") -> dict[str, pd.Series]:
    """两种拥挤度读数（实现见 ``_evidence_core``，规则表绑定资金流面）。"""
    return core.crowding_readings(factors, key, RULES[key])


def three_question_verdict(m: dict, spans: list[float]) -> dict:
    """三问判据的机械判决 —— **实现已抽到 ``_evidence_core``**（与宏观面共用）。

    这里保留同名薄壳，是为了不破坏 V0.123.0 的公开 API
    （``tests/test_scripts/test_verify_flow_face.py`` 直接按名字调）。
    """
    return core.three_question_verdict(m, spans)


# ───────────────────────── 取数与缓存 ─────────────────────────


def build_daily_factors(
    *,
    cftc_points,
    sse_shares: dict[date, float],
    closes_518880: dict[date, float],
    us_liq_rows,
    cn_margin_rows,
    cn_money_rows,
    calendar: list[date],
    today: date,
) -> pd.DataFrame:
    """把 6 个源观测铺成**日频**因子序列（口径对齐 ``services/money_flow.py``）。

    每个因子落成一条日频线（真实库里就是每天写一行同一读数）⇒
    滚动分位带的窗口里**含重复值**，与 ``get_window`` 的返回一致。
    """
    cal = pd.DatetimeIndex([pd.Timestamp(d) for d in calendar])

    def asof(s: pd.Series) -> pd.Series:
        return s.reindex(cal, method="ffill")

    out = pd.DataFrame(index=cal)

    # ①/② CFTC：水平（占 OI %）与 4 周变化（周频观测 → 日频前向填充，不回填未来）
    cot = pd.DataFrame(
        [(p.obs_date, p.net_long, p.net_pct_oi) for p in cftc_points],
        columns=["d", "net", "pct"],
    )
    cot["d"] = pd.to_datetime(cot["d"])
    cot = cot.set_index("d").sort_index()
    cot["chg4"] = cot["net"] - cot["net"].shift(4)
    out["cot_gold_net"] = asof(cot["pct"])
    out["cot_gold_flow"] = asof(cot["chg4"])

    # ③ 黄金ETF 4 周累计净申赎（亿元）：周网格 + 28 天回退 ±7 天
    week_ends = week_end_days(calendar, today=today)
    close = pd.Series({pd.Timestamp(d): float(v) for d, v in closes_518880.items()}).sort_index()
    rows: dict[pd.Timestamp, float] = {}
    for end_day in week_ends:
        s_end = sse_shares.get(end_day)
        if s_end is None:
            continue
        target = end_day - timedelta(days=28)
        cands = sorted(
            (w for w in week_ends if abs((w - target).days) <= 7),
            key=lambda w: abs((w - target).days),
        )
        s_prev = next((sse_shares[w] for w in cands if w in sse_shares), None)
        if s_prev is None:
            continue
        ed = pd.Timestamp(end_day)
        c = close.reindex([ed]).dropna()
        if c.empty:
            continue
        rows[ed] = (s_end - s_prev) * float(c.iloc[0]) / 1e4
    out["gold_etf_flow"] = asof(pd.Series(rows, dtype=float))

    # ④ 美元净流动性 4 周变化（$M）：月末网格（源已是月末锚点 + 差值）
    us = pd.Series({pd.Timestamp(d): float(v) for d, v, _ in us_liq_rows}, dtype=float).sort_index()
    out["us_liq_net"] = asof(us)

    # ⑤ A股融资余额月环比（%）：沪深交集日期 + 完整月末（当月未过完 ⇒ 丢弃）
    by_day = {pd.Timestamp(d): float(v) for d, v in cn_margin_rows}
    m = pd.Series(by_day, dtype=float).sort_index()
    by_month: dict[tuple[int, int], tuple[pd.Timestamp, float]] = {}
    for d, v in m.items():
        key = (d.year, d.month)
        if key not in by_month or d > by_month[key][0]:
            by_month[key] = (d, v)
    months = sorted(k for k in by_month if k != (today.year, today.month))
    mar_rows: dict[pd.Timestamp, float] = {}
    for a, b in itertools.pairwise(months):
        va, vb = by_month[a][1], by_month[b][1]
        if va > 0:
            mar_rows[by_month[b][0]] = (vb / va - 1.0) * 100.0
    out["cn_margin_flow"] = asof(pd.Series(mar_rows, dtype=float))

    # ⑥ M1−M2 剪刀差（pp）：月末锚点
    gap_rows = {pd.Timestamp(d): float(m1) - float(m2) for d, m1, m2 in cn_money_rows}
    out["cn_money_gap"] = asof(pd.Series(gap_rows, dtype=float).sort_index())

    return out


async def fetch_all(years: int, today: date) -> dict:
    """联网取全部源数据（形状与 ``build_daily_factors`` 的入参一致）。"""
    cfg = get_settings()
    cftc_points = await fetch_cftc_gold_history(years=years)
    closes_518880 = await fetch_sina_etf_closes("sh518880")
    if not cftc_points or not closes_518880:
        raise RuntimeError("CFTC 或新浪收盘价取数失败 —— 无法构建历史")

    calendar = sorted(closes_518880)
    week_ends = week_end_days(calendar, today=today)
    sse_shares: dict[date, float] = {}
    for d in week_ends:
        v = await fetch_sse_etf_shares(GOLD_ETF_SYMBOL, d)
        if v is not None:
            sse_shares[d] = v
    us_liq_rows = await fetch_us_net_liquidity_monthly(today=today)
    cn_margin_rows = await fetch_cn_margin_balances()
    cn_money_rows = await fetch_cn_money_supply()
    gld = await fetch_yahoo_daily("GLD", base_url=cfg.yahoo_chart_url, range_="max", interval="1d")
    return {
        "cftc_points": cftc_points,
        "sse_shares": sse_shares,
        "closes_518880": closes_518880,
        "us_liq_rows": us_liq_rows,
        "cn_margin_rows": cn_margin_rows,
        "cn_money_rows": cn_money_rows,
        "calendar": calendar,
        "today": today,
        "gld": gld,
    }


def save_cache(
    path: Path, factors: pd.DataFrame, prices: dict, cot: pd.DataFrame, today: date
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        pickle.dump(
            {
                "built_at": date.today().isoformat(),
                "asof": today.isoformat(),
                "factors": factors,
                "prices": prices,
                "cot": cot,
            },
            fh,
        )


def load_cache(path: Path) -> dict:
    with path.open("rb") as fh:
        return pickle.load(fh)


# ───────────────────────── 输出 ─────────────────────────


def _fmt(m: dict) -> str:
    ratio = m["ratio"]
    rs = f"{ratio:>6.2f}" if np.isfinite(ratio) else "     —"
    return (
        f"pc_fwd {m['pc_fwd']:+.4f} (p={m['p_fwd']:.3f})  "
        f"pc_past {m['pc_past']:+.4f} (p={m['p_past']:.3f})  "
        f"比值 {rs}  n={m['n']}"
    )


def report(cache: dict) -> tuple[list[str], list[str]]:
    """打印全部证据，返回 ``(通过项, 失败项)``。"""
    factors: pd.DataFrame = cache["factors"]
    prices: dict[str, pd.Series] = cache["prices"]
    cot: pd.DataFrame = cache["cot"]
    # ⚠ 价格用**各自的原生日历**（GLD=美股、518880=A 股），
    # 因子由 ``_align_to_price`` 前向填充到该日历
    # （V0.123.0 修：此前把价格压到 518880 日历上 ⇒ GLD 的「60 交易日」其实是 60 个 A 股日）。
    px = {t: prices[t].sort_index() for t in TARGETS if t in prices}

    passed: list[str] = []
    failed: list[str] = []

    print("=" * 100)
    print(
        f"资金流面证据复算（缓存构建于 {cache.get('built_at', '?')}，as-of {cache.get('asof', '?')}）"
    )
    print("=" * 100)
    print("\n因子覆盖：")
    for k in KEYS:
        s = factors[k].dropna()
        if s.empty:
            print(f"   {k:<16} ⚠ 无数据")
            continue
        print(
            f"   {k:<16} n={len(s):>5}  {s.index[0].date()} → {s.index[-1].date()}  末值 {s.iloc[-1]:.4f}"
        )

    # 逐标的重建：因子读数按**标的自己的日历** as-of（服务当天就能读到的那一版），
    # 滚动分位带仍来自服务口径的因子历史（与标的无关）。
    tgt_data: dict[str, dict] = {}
    for tgt in px:
        cal = px[tgt].index
        f_t = pd.DataFrame({k: factor_on_calendar(factors, cot, k, cal) for k in KEYS})
        s_t = service_scores(f_t, band_source=factors)
        tgt_data[tgt] = {
            "f": f_t,
            "s": s_t,
            "comp": face_composite(s_t),
            "comp_flip": face_composite(service_scores(f_t, flip_net=True, band_source=factors)),
        }

    # ── §1 单因子方向（V0.122.0 的决策依据）──
    print("\n" + "=" * 100)
    print("§1  单因子方向证据：净多占 OI 的年内五分位（前瞻 60 交易日）")
    print("=" * 100)
    print(
        "   （口径与 verify_cot_sign.py::analyse **同型**：因子前向填充到标的自身日历、"
        "价格日历裁到「首观测~末观测」、只在样本内做年内五分位 ⇒ 两脚本同数字）"
    )
    spread_by_target: dict[str, dict] = {}
    for tgt in px:
        net_daily = tgt_data[tgt]["f"]["cot_gold_net"]
        res = quintile_spread(net_daily, px[tgt])
        if not res:
            print(f"   [{tgt}] 样本不足")
            continue
        spread_by_target[tgt] = res
        qs = "  ".join(f"Q{q}={res['quintile'][q]:+.3f}%" for q in sorted(res["quintile"]))
        print(f"   [{tgt}] n={res['n']}  {qs}")
        print(f"        ⇒ Q1 − Q5 = {res['spread']:+.3f} pp")
    print("\n   分区间（**全样本的同一套分组标签**再按年份切片 —— 与 analyse 同型）：")
    span_spreads: dict[str, list[float]] = {}
    for tgt in px:
        segs = []
        vals: list[float] = []
        samp = _quintile_sample(tgt_data[tgt]["f"]["cot_gold_net"], px[tgt], H_FORWARD)
        for span in SPANS:
            sub = samp[(samp["yr"] >= span[0]) & (samp["yr"] <= span[1])]
            r = _agg_quintile(sub)
            if r:
                vals.append(r["spread"])
                segs.append(f"{span[0]}-{span[1]}={r['spread']:+.3f}pp")
            else:
                segs.append(f"{span[0]}-{span[1]}=样本不足")
        span_spreads[tgt] = vals
        print(f"   [{tgt}] " + "  ".join(segs))

    # ── §2 composite（服务真实口径）──
    print("\n" + "=" * 100)
    print("§2  资金流面 composite（**服务真实打分口径**）")
    print("=" * 100)
    print(f"   {'变体':<26}{'标的':<9}{'h':>4}  证据")
    comp_ratios: dict[str, float] = {}
    comp_measures: dict[str, dict] = {}
    for label, field in (
        ("现状(cot=负,V0.122.0已上线)", "comp"),
        ("翻cot(=正,V0.122.0前)", "comp_flip"),
    ):
        for tgt in px:
            series = tgt_data[tgt][field]
            for h in (20, H_FORWARD):
                m = measure(series, px[tgt], h)
                comp_ratios[f"{label}|{tgt}|{h}"] = m["ratio"]
                print(f"   {label:<26}{tgt:<9}{h:>4}  {_fmt(m)}")
            comp_measures[f"{label}|{tgt}"] = {
                "m": measure(series, px[tgt], H_FORWARD),
                "spans": measure_spans(series, px[tgt], H_FORWARD),
            }
    print("\n   ⚠ 对照：V0.122.0 已发布的那组数字（z 分数口径 + 损坏的 ETF 份额序列）")
    print(
        "      现状 +0.188/+0.214 → 改号后 +0.235/+0.120 —— **本脚本复现不出来**（口径与数据都变了）"
    )

    # ── §3 C5 候选 ──
    print("\n" + "=" * 100)
    print("§3  C5 候选读数的三问判决（h=60）")
    print("=" * 100)
    verdicts: dict[str, dict] = {}
    for tgt in px:
        crowd = crowding_readings(tgt_data[tgt]["f"])
        cons = consensus_readings(tgt_data[tgt]["s"])
        candidates = {
            "consensus_dir 方向共识": cons["dir"],
            "consensus_agree 一致程度": cons["agree"],
            "dispersion 面内离散度": cons["dispersion"],
            "crowding_pctile 拥挤度分位": crowd["pctile"],
            "crowding_wmax 拥挤度水平": crowd["wmax"],
        }
        for label, series in candidates.items():
            m = measure(series, px[tgt], H_FORWARD)
            spans = measure_spans(series, px[tgt], H_FORWARD)
            v = three_question_verdict(m, spans)
            verdicts[f"{label}|{tgt}"] = v
            flags = (
                ("✅" if v["q1_power"] else "❌")
                + ("✅" if v["q2_symmetry"] else "❌")
                + ("✅" if v["q3_spans"] else "❌")
            )
            seg_txt = "  ".join(f"{s:+.4f}" if np.isfinite(s) else "   —" for s in spans)
            print(f"   {label:<24}[{tgt}] {flags}  {_fmt(m)}   三段 {seg_txt}")
    print("   （三问：①残余功效 ②前瞻/回看比值 > 1.3 ③三子区间同向）")

    # ── §4 拥挤度是不是金价水平代理 ──
    print("\n" + "=" * 100)
    print("§4  拥挤度是不是「当期金价水平的代理」？（同一分组，不同依赖变量口径）")
    print("=" * 100)
    for tgt in px:
        m = measure(tgt_data[tgt]["f"]["cot_gold_net"], px[tgt], H_FORWARD)
        raw_corr = m["raw_corr"]
        print(f"   [{tgt}] 组内秩 vs 去均值前瞻收益：raw corr {raw_corr:+.4f}")
        print(
            f"            控制当期金价水平后：偏相关 {m['pc_fwd']:+.4f} (p={m['p_fwd']:.3f}, n={m['n']})"
        )
        if not np.isfinite(m["pc_fwd"]) or not np.isfinite(m["p_fwd"]) or m["p_fwd"] >= 0.05:
            print("            ⇒ 偏相关**不显著**（p≥0.05）⇒ 独立于金价水平的前瞻力未获证实。")
        elif np.isfinite(raw_corr) and raw_corr * m["pc_fwd"] < 0:
            print(
                "            ⇒ raw 与偏相关**符号相反** ⇒ 拥挤度的效应主要经由「价格已经涨了多少」传导，"
            )
            print("              不是独立于金价水平的前瞻信息。")
        else:
            print("            ⇒ raw 与偏相关同号且显著 ⇒ 效应不完全是金价水平代理。")

    # ── 判据 ──
    print("\n" + "=" * 100)
    print("判据（退出码依据 —— 文档必须与之一致）")
    print("=" * 100)
    gld = "GLD"
    if gld in spread_by_target:
        res = spread_by_target[gld]
        seg_spans = span_spreads.get(gld, [])
        pos = sum(1 for s in seg_spans if s > 0)
        if res["spread"] > 0 and pos >= 2:
            print(
                f"✅ A1 拥挤度符号方向成立（Q1−Q5 = {res['spread']:+.3f}pp，{pos}/{len(seg_spans)} 段为正）⇒ V0.122.0 的符号修复保留"
            )
            passed.append("A1 拥挤度符号方向")
        else:
            print(
                f"❌ A1 拥挤度符号方向不成立（Q1−Q5 = {res['spread']:+.3f}pp，{pos}/{len(seg_spans)} 段为正）⇒ 文档要改"
            )
            failed.append("A1 拥挤度符号方向")
    comp_pass = []
    near = []
    for k, v in comp_measures.items():
        verdict = three_question_verdict(v["m"], v["spans"])
        if verdict["passed"]:
            comp_pass.append(k)
        elif verdict["ratio_usable"] and v["m"]["ratio"] > 1.0:
            near.append(
                f"{k} 比值 {v['m']['ratio']:.2f}（门槛 {RATIO_GATE}）"
                f"，|pc_fwd|={abs(v['m']['pc_fwd']):.3f}（门槛 {POWER_GATE}，p={v['m']['p_fwd']:.3f}）"
                f" ⇒ 第{'①' if not verdict['q1_power'] else '②'}问不过"
            )
    if not comp_pass:
        detail = ("；" + "；".join(near)) if near else ""
        print(
            "✅ A2 资金流面 composite 不具备可证明的前瞻力"
            "（两种符号 × 两个标的，三问全不过：功效 / 比值 > 1.3 / 三段同向）" + detail
        )
        passed.append("A2 composite 无前瞻力")
    else:
        print(f"❌ A2 composite 出现了前瞻力（{comp_pass}）⇒ 文档要改")
        failed.append("A2 composite 无前瞻力")
    for name, v in verdicts.items():
        if v["passed"]:
            print(f"ℹ C5 候选机械上通过三问：{name}")
            print(
                "    （三问只是**必要条件**：是否值得入库还要看①是不是新信息"
                "②是否与在册因子重复③效应量是否够大）"
            )
        else:
            miss = []
            if not v["q1_power"]:
                miss.append("①功效")
            if not v["q2_symmetry"]:
                miss.append("②比值" + ("（分母趋零⇒不可判）" if not v["ratio_usable"] else ""))
            if not v["q3_spans"]:
                miss.append("③分段")
            print(f"   · {name}：不过 {'/'.join(miss)}")
    return passed, failed


# ───────────────────────── 入口 ─────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description="资金流面证据复算")
    ap.add_argument("--cache", default="data/verify/flow_face_cache.pkl", help="缓存文件路径")
    ap.add_argument("--fetch", action="store_true", help="联网取数并重建缓存（不分析）")
    ap.add_argument("--years", type=int, default=12, help="CFTC 回看自然年个数")
    ap.add_argument("--asof", default="", help="as-of 日期（YYYY-MM-DD），默认今天")
    args = ap.parse_args()

    today = date.fromisoformat(args.asof) if args.asof else date.today()
    cache_path = Path(args.cache)

    if args.fetch:
        print(f"联网取数中（CFTC {args.years} 年 + 上交所周网格 + FRED + 汇率）……", flush=True)
        src = asyncio.run(fetch_all(args.years, today))
        factors = build_daily_factors(
            cftc_points=src["cftc_points"],
            sse_shares=src["sse_shares"],
            closes_518880=src["closes_518880"],
            us_liq_rows=src["us_liq_rows"],
            cn_margin_rows=src["cn_margin_rows"],
            cn_money_rows=src["cn_money_rows"],
            calendar=src["calendar"],
            today=today,
        )
        prices = {
            "GLD": pd.Series(
                {pd.Timestamp(d): float(v) for d, v in src["gld"]}, dtype=float
            ).sort_index(),
            "518880": pd.Series(
                {pd.Timestamp(d): float(v) for d, v in src["closes_518880"].items()},
                dtype=float,
            ).sort_index(),
        }
        cot = (
            pd.DataFrame(
                [(pd.Timestamp(p.obs_date), p.net_pct_oi) for p in src["cftc_points"]],
                columns=["d", "pct"],
            )
            .set_index("d")
            .sort_index()
        )
        save_cache(cache_path, factors, prices, cot, today)
        print(f"✅ 缓存已写入 {cache_path}")
        return 0

    if not cache_path.exists():
        print(f"❌ 缓存不存在：{cache_path}\n   先跑 --fetch（或指定 --cache 指向已有缓存）")
        return 1

    cache = load_cache(cache_path)
    _passed, failed = report(cache)
    print(f"\n结果：{len(_passed)} passed" + (f"，{len(failed)} failed" if failed else ""))
    for f in failed:
        print(f"❌ {f}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
