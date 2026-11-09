#!/usr/bin/env python3
"""**通用证据管线**（V0.124.0 抽出）—— 资金流面与宏观面共用同一份口径。

为什么要有这个模块
------------------
V0.122.0 / V0.123.0 已经给资金流面建了一套「三问」测量管线
（``scripts/verify_flow_face.py``）；V0.124.0 要用**同一套判据**去测宏观面。
若各写各的，两边会各自漂移 —— 而**漂移的方向恰好是最危险的那种**：
宏观面权重 35%，是综合指数里最大的一面，它的结论要是比资金流面更宽松，
读者根本看不出来（两边的数字都「看着像那么回事」）。

⇒ 把「与面无关」的部分抽到这里，**两个脚本 import 同一份代码** ⇒ 口径不会漂。

抽的是哪些东西
--------------
=========================  ==========================================
函数                       用途
=========================  ==========================================
``partial_corr``           控制变量后的偏相关
``fisher_p``               相关系数的双尾 p 值
``within_year_rank``       年内秩（去年度共振）
``align_to_price``         因子序列对齐到**价格日历**（as-of，不回填未来）
``change_points``          序列的**观测点**（值变化的那天）
``clip_to_observations``   把价格日历裁到「首观测 ~ 末观测」
``measure``                一个读数（严格管线）
``measure_spans``          三个子区间的读数
``rolling_band``           服务口径的滚动分位带
``service_scores``         服务真实打分（0-100，线性 + 截断）
``face_composite``         面 composite（分数 × 权重）
``quintile_*``             年内五分位方向统计
``crowding_readings``      拥挤度读数（位置 + 水平）
``consensus_readings``     面内共识度
``three_question_verdict`` 三问的机械判决
=========================  ==========================================

⚠ **「面相关」的东西留在各自的脚本里**：规则表（权重 / 方向 / best / worst）、
数据源、标的日历 —— 这些由各自脚本从**服务的唯一真源**取
（``services/money_flow.py::MONEY_FLOW_FACTOR_RULES`` /
``services/macro.py::MACRO_FACTOR_RULES``），
本模块**不抄一份**（抄了就必然腐化）。

⚠ **静态带不带符号**（V0.123.0 踩过，V0.124.0 复核）：
服务里 ``hardcode[key] = (rule["best"], rule["worst"])`` ——
负号因子的 ``rule["best"]`` 本身就是**低**值。
符号（``positive``）只决定**滚动分位**里 P10/P90 谁当 best。
把静态带也按符号翻一次 ⇒ 负号因子在样本不足段**方向整个反过来**。

⚠ 本模块**不在 CI 门禁集里**（依赖 numpy/pandas），
但两个脚本的**分析函数**都有离线单测守着：
``tests/test_scripts/test_verify_flow_face.py``（13 条）、
``tests/test_scripts/test_verify_macro_face.py``。
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

import numpy as np
import pandas as pd

from app.services.macro_thresholds import _percentile

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

#: 滚动分位带的默认窗口 / 样本门槛（与服务 ``MacroThresholdCalculator`` 一致）
DEFAULT_WINDOW_DAYS = 252
DEFAULT_MIN_SAMPLES = 60


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


def within_year_rank(s: pd.Series) -> pd.Series:
    """年内秩（百分位）—— 去掉年度共振。"""
    return s.groupby(s.index.year).rank(pct=True)


def align_to_price(series: pd.Series, px: pd.Series) -> pd.Series:
    """把因子序列对齐到**价格日历**（前向填充，不回填未来）。

    ⚠ 因子与价格的日历**不一样**（518880 是 A 股日历、GLD 是美股日历）⇒
    直接 ``pd.DataFrame({"c": series, "px": px})`` 会取**并集**，
    于是 ``shift(-60)`` 数的是「并集行数」而不是「60 个交易日」
    ⇒ 前瞻窗口长度飘忽（V0.123.0 修）。
    """
    return series.reindex(px.index, method="ffill")


def change_points(s: pd.Series) -> pd.Series:
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


def clip_to_observations(values: pd.Series, px: pd.Series) -> tuple[pd.Series, pd.Series]:
    """把价格日历裁到「因子首观测 ~ 末观测」之间，并把因子对齐上去。

    与 ``verify_cot_sign.py::analyse`` 同型：因子在首观测之前没有读数、
    末观测之后不再更新 ⇒ 那些天的因子值只是「沿用的旧读数」，
    留着会稀释样本（V0.123.0 对齐：n 差 3 行、Q1−Q5 差 0.07pp）。
    """
    obs = change_points(values)
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
    c_series, c_px = clip_to_observations(series, px)
    d = pd.DataFrame({"c": c_series, "px": c_px})
    d["yr"] = d.index.year
    d["r"] = within_year_rank(d["c"])
    d["pxr"] = within_year_rank(d["px"])
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


def measure_spans(
    series: pd.Series,
    px: pd.Series,
    h: int = H_FORWARD,
    spans: Sequence[tuple[int, int]] = SPANS,
) -> list[float]:
    """三个子区间的 pc_fwd —— 检验「不是某一段行情撑起来的」。"""
    out: list[float] = []
    for span in spans:
        out.append(measure(series, px, h, years=span)["pc_fwd"])
    return out


# ───────────────────────── 服务真实打分 ─────────────────────────


def rolling_band(
    factors: pd.DataFrame,
    key: str,
    positive: bool,
    rule: dict,
    *,
    default_window_days: int = DEFAULT_WINDOW_DAYS,
    default_min_samples: int = DEFAULT_MIN_SAMPLES,
) -> pd.Series:
    """服务口径的滚动分位带。

    ⚠ 口径必须与 ``services/macro_thresholds.py`` 一致：
    窗口是**最近 ``window_days`` 个日历日**内的**全部日频行**
    （含同一观测值的重复行 —— 真实库里就是一天一行地重复写），
    **不是**「去重后的观测日」。两者算出来的 P10/P90 不同。

    返回 ``Series[日期] = (best, worst)``。
    """
    raw = factors[key]
    window = int(rule.get("window_days") or default_window_days)
    min_samples = int(rule.get("min_samples") or default_min_samples)
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
    rules: dict[str, dict],
    keys: Iterable[str],
    *,
    flip_keys: Iterable[str] | None = None,
    band_source: pd.DataFrame | None = None,
    skip_rolling: Iterable[str] = (),
    default_window_days: int = DEFAULT_WINDOW_DAYS,
    default_min_samples: int = DEFAULT_MIN_SAMPLES,
) -> pd.DataFrame:
    """服务真实打分（0-100，线性 + 截断）—— 与 ``_friendly_score`` 同型。

    Args:
        factors: 各因子的**日频原始值**（可以是某个标的自己的日历）。
        rules: ``{key: rule}``（服务的规则表）。
        keys: 参与打分的因子（顺序决定输出列序）。
        flip_keys: 把这些因子的符号翻回「+」（用于「改号前/后」对照）。
        band_source: 滚动分位带的**样本来源**；默认与 ``factors`` 相同。
            生产口径下滚动带来自服务自己的因子历史（与目标标的无关），
            而「因子的当期读数」是**按标的日历 as-of** 的 ⇒ 两者日历可以不同。
        skip_rolling: 这些因子**恒用静态带**（服务里的 ``SKIP_ROLLING_FACTORS``
            —— 低频因子样本天生不足，永远走 hardcode）。
    """
    src = factors if band_source is None else band_source
    flip = set(flip_keys or ())
    skip = set(skip_rolling)
    out: dict[str, pd.Series] = {}
    for key in keys:
        rule = rules[key]
        positive = bool(rule.get("positive", True))
        if key in flip:
            positive = not positive
        raw = factors[key]
        if key in skip:
            band = pd.Series(dtype=object, index=pd.DatetimeIndex([]))
        else:
            band = rolling_band(
                src,
                key,
                positive,
                rule,
                default_window_days=default_window_days,
                default_min_samples=default_min_samples,
            )
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


def face_composite(scores: pd.DataFrame, rules: dict[str, dict], keys: Iterable[str]) -> pd.Series:
    """面 composite（服务口径：因子分数 × 规则权重之和）。"""
    return sum(scores[k] * float(rules[k]["weight"]) for k in keys)


# ───────────────────────── 单因子方向证据 ─────────────────────────


def quintile_by_order(values: list[float]) -> list[int]:
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


def quintile_sample(values: pd.Series, px: pd.Series, fwd_days: int = H_FORWARD) -> pd.DataFrame:
    """样本 + 年内五分位标签（一次算完；分区间复用**同一套**标签）。

    与 ``scripts/verify_cot_sign.py::analyse`` **同型**，以便两个脚本给出同一个数字：

    ① 因子先对齐到价格日历（前向填充），价格日历裁到「首观测~末观测」；
    ② 前瞻收益 = 价格日历上**位置**位移 h 个交易日；
    ③ **只在样本内**（有前瞻收益的行）做年内五分位分组；
    ④ 分区间统计用**全样本的分组标签**再按年份切片（不是分段重新分组）。
    """
    v_series, v_px = clip_to_observations(values, px)
    d = pd.DataFrame({"v": v_series, "px": v_px})
    d["yr"] = d.index.year
    d["fwd"] = d["px"].shift(-fwd_days) / d["px"] - 1.0
    d = d.dropna(subset=["v", "px", "fwd"])
    if d.empty:
        return d
    q = pd.Series(index=d.index, dtype=float)
    for _yr, sub in d.groupby("yr"):
        q.loc[sub.index] = quintile_by_order(sub["v"].tolist())
    d["q"] = q
    return d.dropna(subset=["q"])


def agg_quintile(d: pd.DataFrame) -> dict:
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
    return agg_quintile(quintile_sample(values, px, fwd_days))


# ───────────────────────── 拥挤度 / 共识度 ─────────────────────────


def observation_series(factors: pd.DataFrame, key: str) -> pd.Series:
    """因子的**观测序列**（值发生变化的那天）—— 用于拥挤度的窗口统计。

    ⚠ V0.123.0 修：此前写的是「按索引去重」，而日频表的索引本来就唯一
    ⇒ 等于没去重 ⇒ 百分位被「这个值停留了几天」加权。
    """
    return change_points(factors[key])


def crowding_readings(factors: pd.DataFrame, key: str, rule: dict) -> dict[str, pd.Series]:
    """两种拥挤度读数。

    - ``pctile``：当前值在**自己窗口**里的百分位（位置读数）；
    - ``wmax``：窗口**最大值**（水平读数 —— 拥挤程度本身）。
    """
    window = int(rule.get("window_days") or DEFAULT_WINDOW_DAYS)
    min_samples = int(rule.get("min_samples") or DEFAULT_MIN_SAMPLES)
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


# ───────────────────────── 三问判决 ─────────────────────────


def three_question_verdict(
    m: dict,
    spans: list[float],
    *,
    power_gate: float = POWER_GATE,
    ratio_gate: float = RATIO_GATE,
    ratio_floor: float = RATIO_FLOOR,
) -> dict:
    """三问判据的机械判决（不含人的解读）。

    ⚠ 比值的**退化保护**：``|pc_past|`` 趋零时比值会爆表（分母趋零 ⇒ 任何 pc_fwd 都"过线"），
    那种"通过"是假的 ⇒ ``|pc_past| < ratio_floor`` 时第②问判**不可判**（按不过处理）。
    """
    q1 = bool(np.isfinite(m["pc_fwd"]) and abs(m["pc_fwd"]) >= power_gate)
    usable = np.isfinite(m["pc_past"]) and abs(m["pc_past"]) >= ratio_floor
    q2 = bool(usable and np.isfinite(m["ratio"]) and m["ratio"] > ratio_gate)
    finite = [s for s in spans if np.isfinite(s)]
    q3 = bool(len(finite) == len(spans) and len(set(np.sign(finite))) == 1)
    return {
        "q1_power": q1,
        "q2_symmetry": q2,
        "q3_spans": q3,
        "ratio_usable": bool(usable),
        "passed": q1 and q2 and q3,
    }
