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
import math
import pickle
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

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
from app.services.macro_thresholds import _percentile
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


def partial_corr(x, y, ctrl, min_samples: int = 8) -> tuple[float, int]:
    """控制 ``ctrl`` 之后 x 与 y 的偏相关。

    做法：x、y 各自对 ``[1, ctrl]`` 做 OLS 回归取残差，再对残差求相关
    （= 相关分析里的「控制变量」标准做法）。
    """
    d = pd.DataFrame({"x": x, "y": y, "c": ctrl}).dropna()
    if len(d) < min_samples:
        return float("nan"), len(d)
    X = np.column_stack([np.ones(len(d)), d["c"].to_numpy(float)])
    rx = d["x"].to_numpy(float) - X @ np.linalg.lstsq(X, d["x"].to_numpy(float), rcond=None)[0]
    ry = d["y"].to_numpy(float) - X @ np.linalg.lstsq(X, d["y"].to_numpy(float), rcond=None)[0]
    if np.std(rx) < 1e-12 or np.std(ry) < 1e-12:
        return float("nan"), len(d)
    return float(np.corrcoef(rx, ry)[0, 1]), len(d)


def fisher_p(r: float, n: int) -> float:
    """相关系数的双尾 p 值（Fisher z 变换）。"""
    if not np.isfinite(r) or n < 5 or abs(r) >= 1:
        return float("nan")
    z = 0.5 * math.log((1 + r) / (1 - r)) * math.sqrt(n - 3)
    return float(2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2)))))


def _within_year_rank(s: pd.Series) -> pd.Series:
    """年内秩（百分位）—— 去掉年度共振。"""
    return s.groupby(s.index.year).rank(pct=True)


def _align_to_price(series: pd.Series, px: pd.Series) -> pd.Series:
    """把因子序列对齐到**价格日历**（前向填充，不回填未来）。

    ⚠ 因子与价格的日历**不一样**（518880 是 A 股日历、GLD 是美股日历）⇒
    直接 ``pd.DataFrame({"c": series, "px": px})`` 会取**并集**，
    于是 ``shift(-60)`` 数的是「并集行数」而不是「60 个交易日」
    ⇒ 前瞻窗口长度飘忽（V0.123.0 修）。
    """
    return series.reindex(px.index, method="ffill")


def _change_points(s: pd.Series) -> pd.Series:
    """序列的**观测点**（值发生变化的那天，含首个有效值）。

    ⚠ 日频表里同一个周频/月频观测值会连续重复好几天（真实库就是这么写的）⇒
    「去重索引」等于没去重（索引本来就唯一）⇒
    任何按「观测点」定义的统计都会被「值停留了几天」加权。
    """
    s = s.dropna()
    if s.empty:
        return s
    changed = s.ne(s.shift(1))
    changed.iloc[0] = True
    return s[changed]


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


def _clip_to_observations(values: pd.Series, px: pd.Series) -> tuple[pd.Series, pd.Series]:
    """把价格日历裁到「因子首观测 ~ 末观测」之间，并把因子对齐上去。

    与 ``verify_cot_sign.py::analyse`` 同型：因子在首观测之前没有读数、
    末观测之后不再更新 ⇒ 那些天的因子值只是「沿用的旧读数」，
    留着会稀释样本（V0.123.0 对齐：n 差 3 行、Q1−Q5 差 0.07pp）。
    """
    obs = _change_points(values)
    if obs.empty:
        return values, px
    cal = px[(px.index >= obs.index[0]) & (px.index <= obs.index[-1])]
    return values.reindex(cal.index, method="ffill"), cal


def measure(
    series: pd.Series,
    px: pd.Series,
    h: int = H_FORWARD,
    years: tuple[int, int] | None = None,
) -> dict:
    """严格管线下的一个读数。

    管线：**非重叠采样**（每隔 h 个交易日取一次）+ 前瞻/回看收益**年内去均值**
    + 控制**当期金价水平**的年内秩。
    """
    c_series, c_px = _clip_to_observations(series, px)
    d = pd.DataFrame({"c": c_series, "px": c_px})
    d["yr"] = d.index.year
    d["r"] = _within_year_rank(d["c"])
    d["pxr"] = _within_year_rank(d["px"])
    d["fwd"] = d["px"].shift(-h) / d["px"] - 1.0
    d["past"] = d["px"] / d["px"].shift(h) - 1.0
    s = d.iloc[(np.arange(len(d)) % h == 0)].copy()
    for c in ("fwd", "past"):
        s[c + "_dm"] = s[c] - s.groupby("yr")[c].transform("mean")
    s = s.dropna(subset=["r", "fwd_dm", "past_dm", "pxr"])
    if years is not None:
        s = s[(s["yr"] >= years[0]) & (s["yr"] <= years[1])]
    pc, n = partial_corr(s["r"], s["fwd_dm"], s["pxr"])
    pcp, _ = partial_corr(s["r"], s["past_dm"], s["pxr"])
    ratio = abs(pc) / abs(pcp) if np.isfinite(pcp) and abs(pcp) > 1e-9 else float("nan")
    return {
        "pc_fwd": pc,
        "p_fwd": fisher_p(pc, n),
        "pc_past": pcp,
        "p_past": fisher_p(pcp, n),
        "ratio": ratio,
        "n": n,
        "raw_corr": float(s["r"].corr(s["fwd_dm"])) if len(s) > 2 else float("nan"),
    }


def measure_spans(series: pd.Series, px: pd.Series, h: int = H_FORWARD) -> list[float]:
    """三个子区间的 pc_fwd —— 检验「不是某一段行情撑起来的」。"""
    out: list[float] = []
    for span in SPANS:
        out.append(measure(series, px, h, years=span)["pc_fwd"])
    return out


# ───────────────────────── 服务真实打分 ─────────────────────────


def rolling_band(factors: pd.DataFrame, key: str, positive: bool) -> pd.Series:
    """服务口径的滚动分位带。

    ⚠ 口径必须与 ``services/macro_thresholds.py`` 一致：
    窗口是**最近 ``window_days`` 个日历日**内的**全部日频行**
    （含同一观测值的重复行 —— 真实库里就是一天一行地重复写），
    **不是**「去重后的观测日」。两者算出来的 P10/P90 不同。

    返回 ``Series[日期] = (best, worst)``。
    """
    rule = RULES[key]
    raw = factors[key]
    window = int(rule["window_days"])
    min_samples = int(rule["min_samples"])
    out: dict[pd.Timestamp, tuple[float, float]] = {}
    for d in raw.index:
        v = raw.loc[d]
        if pd.isna(v):
            continue
        lo = d - pd.Timedelta(days=window)
        vals = raw.loc[(raw.index >= lo) & (raw.index <= d)].dropna()
        if len(vals) < min_samples:
            continue
        sv = sorted(float(x) for x in vals)
        p10 = _percentile(sv, 10.0)
        p90 = _percentile(sv, 90.0)
        out[d] = (p90, p10) if positive else (p10, p90)
    # ⚠ 显式构造 DatetimeIndex：``pd.Series({}, dtype=object)`` 的索引是 **object**，
    # 下游 ``reindex(..., method="ffill")`` 会因索引类型不可比而抛 TypeError
    # （样本不足、滚动带为空时才触发 —— V0.123.0 的离线测试撞到过）。
    return pd.Series(
        list(out.values()),
        index=pd.DatetimeIndex(list(out.keys())),
        dtype=object,
    ).sort_index()


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
    src = factors if band_source is None else band_source
    out: dict[str, pd.Series] = {}
    for key in KEYS:
        rule = RULES[key]
        positive = bool(rule.get("positive", True))
        if flip_net and key == "cot_gold_net":
            positive = not positive
        raw = factors[key]
        band = rolling_band(src, key, positive)
        best = band.map(lambda t: t[0]).reindex(raw.index, method="ffill")
        worst = band.map(lambda t: t[1]).reindex(raw.index, method="ffill")
        # 样本不足 ⇒ 回退静态带（hardcode）。
        #
        # ⚠ 静态带**不带符号**：服务里 `hardcode[key] = (rule["best"], rule["worst"])`
        # （`macro_thresholds.py:107` / `money_flow.py:625`）—— 负号因子的
        # `rule["best"]` 本身就是**低**值（如 cot_gold_net：best=6.49 < worst=34.10）。
        # 符号只决定**滚动分位**里 P10/P90 谁当 best。
        # （V0.123.0 修：这里曾按符号把静态带也翻一次 ⇒ 负号因子在样本不足段方向反了。）
        best = best.fillna(rule["best"])
        worst = worst.fillna(rule["worst"])
        # best == worst ⇒ 服务返回 50（`_friendly_score` 的显式分支），不能算成 NaN
        denom = (best - worst).replace(0.0, np.nan)
        score = (raw - worst) / denom * 100.0
        score = score.where(denom.notna(), 50.0)
        out[key] = score.clip(0, 100)
    return pd.DataFrame(out)


def face_composite(scores: pd.DataFrame) -> pd.Series:
    """资金流面 composite（服务口径：因子分数 × 规则权重之和）。"""
    return sum(scores[k] * float(RULES[k]["weight"]) for k in KEYS)


# ───────────────────────── 单因子方向证据 ─────────────────────────


def _quintile_by_order(values: list[float]) -> list[int]:
    """按**因子值**排序（同值按时间顺序）等分 5 组 —— 与 ``verify_cot_sign.py`` 同型。

    ⚠ 不用 pandas 的 ``qcut(rank, 5)``：n 不能被 5 整除时它与「按序等分」差 ±1 行，
    两个脚本会给出**不同的数字**（V0.123.0 对齐过一轮）。
    """
    n = len(values)
    order = sorted(range(n), key=lambda i: (values[i], i))
    out = [0] * n
    for pos, idx in enumerate(order):
        p = (pos + 1) / n
        out[idx] = 1 if p <= 0.2 else 2 if p <= 0.4 else 3 if p <= 0.6 else 4 if p <= 0.8 else 5
    return out


def _quintile_sample(values: pd.Series, px: pd.Series, fwd_days: int = H_FORWARD) -> pd.DataFrame:
    """样本 + 年内五分位标签（一次算完；分区间复用**同一套**标签）。

    与 ``scripts/verify_cot_sign.py::analyse`` **同型**，以便两个脚本给出同一个数字：

    ① 因子先对齐到价格日历（前向填充），价格日历裁到「首观测~末观测」；
    ② 前瞻收益 = 价格日历上**位置**位移 h 个交易日；
    ③ **只在样本内**（有前瞻收益的行）做年内五分位分组；
    ④ 分区间统计用**全样本的分组标签**再按年份切片（不是分段重新分组）。
    """
    v_series, v_px = _clip_to_observations(values, px)
    d = pd.DataFrame({"v": v_series, "px": v_px})
    d["yr"] = d.index.year
    d["fwd"] = d["px"].shift(-fwd_days) / d["px"] - 1.0
    d = d.dropna(subset=["v", "px", "fwd"])
    if d.empty:
        return d
    q = pd.Series(index=d.index, dtype=float)
    for _yr, sub in d.groupby("yr"):
        q.loc[sub.index] = _quintile_by_order(sub["v"].tolist())
    d["q"] = q
    return d.dropna(subset=["q"])


def _agg_quintile(d: pd.DataFrame) -> dict:
    """把带 ``q`` 标签的样本聚合成 Q1..Q5 的前瞻收益均值与 Q1−Q5。"""
    if d.empty:
        return {}
    g = d.groupby("q", observed=True)["fwd"].mean() * 100.0
    if g.empty or 1 not in g.index or 5 not in g.index:
        return {}
    return {
        # ``q`` 是 float 列 ⇒ 分组标签形如 1.0..5.0 ⇒ 截断成 int 才是 Q1..Q5 的编号
        "quintile": {int(float(lbl)): float(g[lbl]) for lbl in g.index},
        "spread": float(g.iloc[0] - g.iloc[-1]),
        "n": len(d),
    }


def quintile_spread(values: pd.Series, px: pd.Series, fwd_days: int = H_FORWARD) -> dict:
    """年内五分位的前瞻收益差（Q1 = 因子最低 ⇒ 对拥挤度口径是「最不拥挤」）。"""
    return _agg_quintile(_quintile_sample(values, px, fwd_days))


# ───────────────────────── C5 候选读数 ─────────────────────────


def observation_series(factors: pd.DataFrame, key: str) -> pd.Series:
    """因子的**观测序列**（值发生变化的那天）—— 用于拥挤度的窗口统计。

    ⚠ V0.123.0 修：此前写的是「按索引去重」，而日频表的索引本来就唯一
    ⇒ 等于没去重 ⇒ 百分位被「这个值停留了几天」加权。
    """
    return _change_points(factors[key])


def crowding_readings(factors: pd.DataFrame, key: str = "cot_gold_net") -> dict[str, pd.Series]:
    """两种拥挤度读数。

    - ``pctile``：当前值在**自己窗口**里的百分位（位置读数）；
    - ``wmax``：窗口**最大值**（水平读数 —— 拥挤程度本身）。
    """
    rule = RULES[key]
    window = int(rule["window_days"])
    min_samples = int(rule["min_samples"])
    obs = observation_series(factors, key)
    series = factors[key]
    pctile: dict[pd.Timestamp, float] = {}
    wmax: dict[pd.Timestamp, float] = {}
    # ⚠ 日频求值（窗口是滑动的，每天的读数都不同），
    # 但窗口里的**分布**用观测点（周频读数）而不是日频重复行
    # ⇒ 百分位不被「这个值停留了几天」加权（V0.123.0 修）。
    for d in series.index:
        v = series.loc[d]
        if pd.isna(v):
            continue
        w = obs[(obs.index >= d - pd.Timedelta(days=window)) & (obs.index <= d)]
        if len(w) < min_samples:
            continue
        arr = w.to_numpy(float)
        pctile[d] = float((arr <= v).sum()) / len(arr) * 100.0
        wmax[d] = float(arr.max())
    return {
        "pctile": pd.Series(pctile, dtype=float).sort_index(),
        "wmax": pd.Series(wmax, dtype=float).sort_index(),
    }


def consensus_readings(scores: pd.DataFrame) -> dict[str, pd.Series]:
    """面内「共识度」三种读数（都基于服务打分）。"""
    centered = (scores - 50.0) / 50.0
    direction = centered.mean(axis=1)
    return {
        "dir": direction,
        "agree": direction.abs(),
        "dispersion": scores.std(axis=1),
    }


def three_question_verdict(m: dict, spans: list[float]) -> dict:
    """三问判据的机械判决（不含人的解读）。

    ⚠ 比值的**退化保护**：``|pc_past|`` 趋零时比值会爆表（分母趋零 ⇒ 任何 pc_fwd 都"过线"），
    那种"通过"是假的 ⇒ ``|pc_past| < RATIO_FLOOR`` 时第②问判**不可判**（按不过处理）。
    """
    q1 = bool(np.isfinite(m["pc_fwd"]) and abs(m["pc_fwd"]) >= POWER_GATE)
    usable = np.isfinite(m["pc_past"]) and abs(m["pc_past"]) >= RATIO_FLOOR
    q2 = bool(usable and np.isfinite(m["ratio"]) and m["ratio"] > RATIO_GATE)
    finite = [s for s in spans if np.isfinite(s)]
    q3 = bool(len(finite) == len(spans) and len(set(np.sign(finite))) == 1)
    return {
        "q1_power": q1,
        "q2_symmetry": q2,
        "q3_spans": q3,
        "ratio_usable": bool(usable),
        "passed": q1 and q2 and q3,
    }


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
