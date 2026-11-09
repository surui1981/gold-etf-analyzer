#!/usr/bin/env python3
"""宏观面的**可复算证据**脚本（V0.124.0 · roadmap §三·C6）。

背景
----
综合指数 = 技术 25% / **宏观 35%** / 消息面 25% / 资金流面 15%。
宏观面是权重最大的那一面，但 **V0.119.0 之前从未被真正测量过**：

- 生产库 ``daily_macro_factors`` 只有 201 天历史，4 个低频因子只有 14~33 行；
- h=60 非重叠采样后整段只剩 ~3 个样本 ⇒ roadmap §C6 里那组
  「前瞻 −0.107 / 回看 +0.329」是 **3 个样本**算出来的 ⇒ **不能用**。

⇒ 本脚本做三件事：

1. **重建**：按 point-in-time 口径把「每日 07:00 采集 + 落表」这条流水线
   在历史上重放一遍（**共用** ``app/services/macro_history.py`` ——
   与生产回填**同一份**代码 ⇒ 口径不会漂）；
2. **测量**：在**生产真实打分口径**（滚动分位带 + 0-100 截断）下，
   用 V0.122.0 定下的**三问**判据测宏观面；
3. **交叉验证**：X1（脚本重建 ≡ 生产表，逐行相等）与 X2（撤销
   point-in-time ⇒ X1 必须变红）。

三问判据（沿用 ``docs/roadmap.md`` §C4 / V0.122.0）
--------------------------------------------------
1. 在**年内去均值 + 非重叠采样 + 控制当期金价水平**之后还剩多少？（残余功效）
2. **前瞻/回看**比值 > 1.3 吗？（对称性 —— 只像回看的因子不是预测因子）
3. **三个子区间**同向吗？（不是某一段行情撑起来的）

三条过不了就不改。

用法
----
::

    # ① 取数（需联网）并落缓存
    PYTHONPATH=src:. python scripts/verify_macro_face.py --fetch --cache data/verify/macro_face_cache.pkl

    # ② 只做分析（**不联网**，读缓存）
    PYTHONPATH=src:. python scripts/verify_macro_face.py --cache data/verify/macro_face_cache.pkl

    # ③ X1 交叉验证：脚本重建 ≡ 生产表（读本地库，不联网）
    PYTHONPATH=src:. python scripts/verify_macro_face.py --cross-check-db --cache data/verify/macro_face_cache.pkl

    # ④ X2 口径守卫：撤销 point-in-time 后必须与生产表不一致
    PYTHONPATH=src:. python scripts/verify_macro_face.py --guard --cache data/verify/macro_face_cache.pkl

⚠ **绝不隐式联网**：不带 ``--fetch`` 就只读缓存；缓存不存在直接报错退出。
⚠ 本脚本**不在 CI 门禁集里**（依赖外网）；但它的**分析函数**有离线单测
（``tests/test_scripts/test_verify_macro_face.py``）⇒ 分析口径本身被 CI 守着。
"""

from __future__ import annotations

import argparse
import asyncio
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
from app.services.macro import MACRO_FACTOR_RULES, SKIP_ROLLING_FACTORS
from app.services.macro_backfill import (
    DEEP_WINDOW_DAYS,
    _fetch_cb_gold_quarters,
    _fetch_eurostat_deep,
    _fetch_fred_history,
    _fetch_fred_periodic_history,
    _fetch_h15_history,
    _fetch_yahoo_dxy_deep,
)
from app.services.macro_history import (
    Observation,
    asof_rows,
    build_observations,
)

#: 规则表 → {key: rule}（**服务唯一真源** —— 不在这里抄一份权重/方向）
RULES: dict[str, dict] = {r["key"]: r for r in MACRO_FACTOR_RULES}
KEYS: list[str] = list(RULES)

#: 低频因子（永远走静态带）
LOWFREQ: tuple[str, ...] = tuple(k for k in KEYS if k in SKIP_ROLLING_FACTORS)
#: 日频因子（走滚动分位带）
DAILY: tuple[str, ...] = tuple(k for k in KEYS if k not in SKIP_ROLLING_FACTORS)

#: 前瞻窗口（交易日）：h=60 与资金流面可比；h=20 是 C6 原问题的「短周期择时力」
HORIZONS: tuple[int, ...] = (60, 20)

#: 重建窗口（自然日）—— 与深回填默认一致
DEFAULT_WINDOW_DAYS = DEEP_WINDOW_DAYS

#: z 分数候选读数的回看窗口（自然日）
ZSCORE_WINDOW_DAYS = 252


# ───────────────────────── 重建（point-in-time） ─────────────────────────


def build_observations_cached(cache: dict, *, end: date) -> dict[str, list[Observation]]:
    """从缓存里的原始源数据组装观测。

    ⚠ **映射逻辑只有一份**：``app/services/macro_history.py::build_observations``
    —— 与生产回填（``services/macro_backfill.py``）**共用** ⇒ 口径不会漂。
    """
    return build_observations(
        h15=cache["h15"],
        fred=cache["fred"],
        yahoo=cache["yahoo"],
        eurostat=cache["eurostat"],
        fred_periodic=cache["fred_periodic"],
        cb_quarters=cache["cb_quarters"],
        end=end,
    )


def reconstruct_rows(
    observations: dict[str, list[Observation]],
    *,
    start: date,
    end: date,
) -> list[tuple[date, str, float, str, str]]:
    """把观测展开成「每个日历日一行」的 point-in-time 行。

    返回 ``[(snapshot_date, factor_key, value, data_date, source), ...]``。
    """
    rows: list[tuple[date, str, float, str, str]] = []
    for key in KEYS:
        rows.extend(asof_rows(observations.get(key, []), factor_key=key, start=start, end=end))
    return rows


def front_view_rows(
    observations: dict[str, list[Observation]],
    *,
    start: date,
    end: date,
) -> list[tuple[date, str, float, str, str]]:
    """**故意前视**的重建（把每条观测的可得日改成观测日本身）。

    只用于 **X2 口径守卫**：撤销 point-in-time 后，脚本重建必须与生产表
    **不一致** ⇒ 一致 ⇒ 说明守卫失效（或生产表本身就是前视的）。
    """
    naive: dict[str, list[Observation]] = {}
    for key, obs in observations.items():
        naive[key] = [
            (d, v, dd, s) for (_orig, (d, v, dd, s)) in enumerate(sorted(obs, key=lambda o: o[0]))
        ]
        # 把「可得日」退回「观测日」：data_date 文本就是源自己的观测日
        fixed: list[Observation] = []
        for avail, value, dd_text, src in naive[key]:
            try:
                obs_date = date.fromisoformat(dd_text)
            except ValueError:
                # 低频因子的 data_date 是窗口标签（如 "2025Q4–2026Q3"）⇒ 退回可得日
                obs_date = avail
            fixed.append((obs_date, value, dd_text, src))
        naive[key] = fixed
    return reconstruct_rows(naive, start=start, end=end)


def rows_to_frame(rows: list[tuple[date, str, float, str, str]]) -> pd.DataFrame:
    """落库行 → ``DataFrame[日期, 因子列]``（重复的 (日期, 因子) 取最后一条）。"""
    if not rows:
        return pd.DataFrame(columns=KEYS, index=pd.DatetimeIndex([]))
    df = pd.DataFrame(rows, columns=["d", "key", "value", "data_date", "source"])
    df = df.drop_duplicates(subset=["d", "key"], keep="last")
    wide = df.pivot(index="d", columns="key", values="value").sort_index()
    wide.index = pd.DatetimeIndex(wide.index)
    return wide


# ───────────────────────── 打分与读数 ─────────────────────────


def macro_scores(factors: pd.DataFrame) -> pd.DataFrame:
    """宏观面 11 因子的**生产真实打分**（0-100）。

    - 7 个日频因子走滚动分位带（窗口 252 **日历**日，含重复行）；
    - 4 个低频因子恒走静态带（``SKIP_ROLLING_FACTORS``）。
    """
    return core.service_scores(factors, RULES, KEYS, skip_rolling=SKIP_ROLLING_FACTORS)


def group_composite(scores: pd.DataFrame, keys: tuple[str, ...]) -> pd.Series:
    """子组 composite（组内权重**归一化**后加权）。"""
    total = sum(float(RULES[k]["weight"]) for k in keys)
    return sum(scores[k] * (float(RULES[k]["weight"]) / total) for k in keys)


def trailing_zscore(factors: pd.DataFrame, key: str, window: int = ZSCORE_WINDOW_DAYS) -> pd.Series:
    """因子值的**尾随 z 分数**（只用 D 及之前的 252 个日历日）。

    ⚠ 这是「滚动分位带」的**替代候选口径**：滚动带是**尾随**的，
    天生「像回看、不像前瞻」；z 分数只用**过往**数据 ⇒ 无前视。
    """
    s = factors[key]
    mean = s.rolling(window, min_periods=60).mean()
    std = s.rolling(window, min_periods=60).std(ddof=0)
    return (s - mean) / std.replace(0.0, np.nan)


def zscore_composite(factors: pd.DataFrame, keys: tuple[str, ...] = tuple(KEYS)) -> pd.Series:
    """「尾随 z 分数」加权和（候选读数 ``zscore_all``）。"""
    total = sum(float(RULES[k]["weight"]) for k in keys)
    out = None
    for k in keys:
        z = trailing_zscore(factors, k)
        part = z * (float(RULES[k]["weight"]) / total)
        out = part if out is None else out + part
    return out if out is not None else pd.Series(dtype=float)


# ───────────────────────── 取数与缓存 ─────────────────────────


async def fetch_all(window_days: int, today: date) -> dict:
    """联网取全部源数据（形状与 ``build_observations`` 的入参一致）。"""
    from app.repositories.money_flow_sources import fetch_sina_etf_closes

    start = today - timedelta(days=window_days)
    h15, fred, yahoo, eurostat, fred_periodic = await asyncio.gather(
        _fetch_h15_history(),
        _fetch_fred_history(),
        _fetch_yahoo_dxy_deep(start, today),
        _fetch_eurostat_deep(),
        _fetch_fred_periodic_history(),
        return_exceptions=True,
    )
    for name, obj in (
        ("H.15", h15),
        ("FRED", fred),
        ("Yahoo DXY", yahoo),
        ("Eurostat", eurostat),
        ("FRED 低频", fred_periodic),
    ):
        if isinstance(obj, BaseException):
            raise RuntimeError(f"{name} 取数失败：{obj}")

    quarters = await _fetch_cb_gold_quarters()

    from app.config import get_settings as _gs
    from app.repositories.macro_sources import fetch_yahoo_daily_period

    cfg = _gs()
    gld = await fetch_yahoo_daily_period(
        "GLD", base_url=cfg.yahoo_chart_period_url, start=start, end=today
    )
    closes_518880 = await fetch_sina_etf_closes("sh518880")
    return {
        "built_at": date.today().isoformat(),
        "asof": today.isoformat(),
        "window_days": window_days,
        "h15": h15,
        "fred": fred,
        "yahoo": yahoo,
        "eurostat": eurostat,
        "fred_periodic": fred_periodic,
        "cb_quarters": quarters,
        "gld": gld,
        "closes_518880": closes_518880,
    }


def save_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        pickle.dump(cache, fh)


def load_cache(path: Path) -> dict:
    with path.open("rb") as fh:
        return pickle.load(fh)


# ───────────────────────── X1 / X2 交叉验证 ─────────────────────────


def _read_production_rows() -> list[tuple[date, str, float, str, str]]:
    """读生产表 ``daily_macro_factors`` → ``[(日期, 因子, 值, data_date, source)]``。"""
    import sqlite3

    cfg = get_settings()
    url = cfg.database_url
    db_path = url.split("///")[-1]
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "SELECT snapshot_date, factor_key, value, data_date, source FROM daily_macro_factors"
        )
        return [
            (date.fromisoformat(sd), key, float(v), dd or "", src or "")
            for sd, key, v, dd, src in cur.fetchall()
        ]
    finally:
        conn.close()


def compare_rows(
    mine: list[tuple[date, str, float, str, str]],
    theirs: list[tuple[date, str, float, str, str]],
    *,
    only_dates: set[date] | None = None,
) -> dict:
    """逐行比较两组 ``(日期, 因子, 值, data_date, source)``。

    返回 ``{相同行数, 不同行数, 只在一侧的行数, 前 N 条差异样例}``。
    """
    idx = {(d, k): (v, dd, s) for d, k, v, dd, s in mine}
    idx2 = {(d, k): (v, dd, s) for d, k, v, dd, s in theirs}
    keys = set(idx) | set(idx2)
    if only_dates is not None:
        keys = {k for k in keys if k[0] in only_dates}
    same = 0
    diff: list[tuple] = []
    only_mine = 0
    only_theirs = 0
    for k in sorted(keys):
        a = idx.get(k)
        b = idx2.get(k)
        if a is None:
            only_theirs += 1
            continue
        if b is None:
            only_mine += 1
            continue
        if abs(a[0] - b[0]) <= 1e-9 and a[1] == b[1] and a[2] == b[2]:
            same += 1
        else:
            diff.append((k[0].isoformat(), k[1], a, b))
    return {
        "same": same,
        "diff": len(diff),
        "only_mine": only_mine,
        "only_theirs": only_theirs,
        "samples": diff[:5],
    }


def cross_check_db(cache: dict, *, use_front_view: bool = False) -> dict:
    """X1（脚本重建 ≡ 生产表）/ X2（撤销 point-in-time 必须不一致）。

    ⚠ **比较区间 = 两者的重叠区间**（V0.124.0 修）。
    脚本窗口（默认 20 年）通常**比生产表覆盖的区间长**（生产库只回填了 5 年）⇒
    脚本独有的那些「生产表根本没覆盖的老历史」**不是不一致**，只是没回填到。
    把它们算进失败会让 X1 永远红 ⇒ 判据失真 ⇒ 等于没有判据。

    判据（重叠区间内）：
    - ``diff == 0``     —— 生产表里每一行都被脚本逐位复现（值 / data_date / source）；
    - ``only_theirs == 0`` —— 生产表在重叠区间里没有脚本复现不出的行；
    - ``only_mine == 0``（仅 X1）—— 重叠区间内脚本没有多出生产表没有的行。

    ⚠ 这个改动**不会**削弱判据：把 point-in-time 撤销（前视）后，
    重叠区间内会出现成百上千行 ``diff`` ⇒ X1 照样变红（X2 就是靠这个）。
    """
    end = date.fromisoformat(cache["asof"])
    start = end - timedelta(days=int(cache.get("window_days", DEFAULT_WINDOW_DAYS)))
    obs = build_observations_cached(cache, end=end)
    if use_front_view:
        rows = front_view_rows(obs, start=start, end=end)
    else:
        rows = reconstruct_rows(obs, start=start, end=end)
    prod = _read_production_rows()
    # 重叠区间 = [脚本窗口起点, 生产表起点] ~ [脚本窗口终点, 生产表终点]
    script_dates = {r[0] for r in rows}
    prod_dates = {r[0] for r in prod}
    overlap = script_dates & prod_dates
    res = compare_rows(rows, prod, only_dates=overlap)
    res["overlap_start"] = min(overlap).isoformat() if overlap else ""
    res["overlap_end"] = max(overlap).isoformat() if overlap else ""
    res["script_only_outside"] = len(script_dates - prod_dates)
    return res


# ───────────────────────── 输出 ─────────────────────────


def _fmt(m: dict) -> str:
    ratio = m["ratio"]
    rs = f"{ratio:>6.2f}" if np.isfinite(ratio) else "     —"
    return (
        f"pc_fwd {m['pc_fwd']:+.4f} (p={m['p_fwd']:.3f})  "
        f"pc_past {m['pc_past']:+.4f} (p={m['p_past']:.3f})  "
        f"比值 {rs}  n={m['n']}"
    )


def _series_report(
    name: str,
    series: pd.Series,
    prices: dict[str, pd.Series],
    *,
    horizons: tuple[int, ...] = HORIZONS,
) -> tuple[list[str], list[str]]:
    """一个读数（一个因子序列 × 两个标的 × 两个 h）的三问判决。"""
    passed: list[str] = []
    failed: list[str] = []
    print(f"\n【{name}】")
    for target in core.TARGETS:
        px = prices.get(target)
        if px is None or px.empty:
            print(f"  {target}: ⚠ 无价格数据")
            continue
        for h in horizons:
            m = core.measure(series, px, h=h)
            spans = core.measure_spans(series, px, h=h)
            v = core.three_question_verdict(m, spans)
            tag = f"{name} / {target} / h={h}"
            print(f"  {target:<7} h={h:<3} {_fmt(m)}")
            print(
                "          三段 pc_fwd: "
                + ", ".join(f"{s:+.4f}" if np.isfinite(s) else "—" for s in spans)
                + f"   ⇒ {'✅ 通过' if v['passed'] else '❌ 未通过'}"
            )
            if v["passed"]:
                passed.append(tag)
            else:
                why = []
                if not v["q1_power"]:
                    why.append("①残余功效不足")
                if not v["q2_symmetry"]:
                    why.append("②对称性不达标" + ("（不可判）" if not v["ratio_usable"] else ""))
                if not v["q3_spans"]:
                    why.append("③三段不同向")
                failed.append(f"{tag}：{'、'.join(why)}")
    return passed, failed


def report(cache: dict) -> tuple[list[str], list[str]]:
    """打印全部证据，返回 ``(通过项, 失败项)``。"""
    passed: list[str] = []
    failed: list[str] = []

    end = date.fromisoformat(cache["asof"])
    start = end - timedelta(days=int(cache.get("window_days", DEFAULT_WINDOW_DAYS)))
    obs = build_observations_cached(cache, end=end)
    rows = reconstruct_rows(obs, start=start, end=end)
    factors = rows_to_frame(rows)

    print("=" * 100)
    print(
        f"宏观面证据复算（缓存构建于 {cache.get('built_at', '?')}，as-of {cache.get('asof', '?')}）"
    )
    print("=" * 100)
    print("\n因子覆盖：")
    for k in KEYS:
        s = factors[k].dropna() if k in factors else pd.Series(dtype=float)
        if s.empty:
            print(f"   {k:<16} ⚠ 无数据")
            continue
        print(
            f"   {k:<16} n={len(s):>5}  {s.index[0].date()} → {s.index[-1].date()}  末值 {s.iloc[-1]:.4f}"
        )

    scores = macro_scores(factors)
    px = {
        "GLD": pd.Series(
            {pd.Timestamp(k): float(v) for k, v in cache.get("gld", []) or []}
        ).sort_index(),
        "518880": pd.Series(
            {pd.Timestamp(k): float(v) for k, v in (cache.get("closes_518880") or {}).items()}
        ).sort_index(),
    }

    # ── 读数 ①：面 composite（三个分组）──
    readings: dict[str, pd.Series] = {
        "macro_all": group_composite(scores, tuple(KEYS)),
        "macro_daily": group_composite(scores, DAILY),
        "macro_lowfreq": group_composite(scores, LOWFREQ),
    }
    for name, series in readings.items():
        p, f = _series_report(name, series, px)
        passed.extend(p)
        failed.extend(f)

    # ── 读数 ②：z 分数候选（尾随 252 日 z）──
    z = zscore_composite(factors)
    p, f = _series_report("zscore_all（候选）", z, px)
    passed.extend(p)
    failed.extend(f)

    # ── 读数 ③：单因子（每个因子自己的 0-100 分）──
    print("\n【单因子（前瞻偏相关 / 三问）】")
    for k in KEYS:
        if k not in scores:
            continue
        line = [f"   {k:<14}"]
        for target in core.TARGETS:
            if target not in px or px[target].empty:
                continue
            m = core.measure(scores[k], px[target], h=60)
            spans = core.measure_spans(scores[k], px[target], h=60)
            v = core.three_question_verdict(m, spans)
            mark = "✅" if v["passed"] else "❌"
            line.append(
                f"{target}: pc_fwd {m['pc_fwd']:+.3f} 比值 {m['ratio']:.2f} n={m['n']} {mark}"
            )
        print("  ".join(line))

    print("\n" + "=" * 100)
    print(f"结论：通过 {len(passed)} 项，未通过 {len(failed)} 项")
    for f in failed:
        print(f"  ❌ {f}")
    for p in passed:
        print(f"  ✅ {p}")
    return passed, failed


# ───────────────────────── 入口 ─────────────────────────


async def _run(args: argparse.Namespace) -> int:
    today = date.today()

    if args.fetch:
        print(f"取数中（窗口 {args.days} 天）…")
        cache = await fetch_all(args.days, today)
        if args.cache:
            save_cache(Path(args.cache), cache)
            print(f"缓存已写入 {args.cache}")
    else:
        if not args.cache:
            print("必须给 --cache <路径>（本脚本**不会隐式联网**）")
            return 2
        path = Path(args.cache)
        if not path.exists():
            print(f"缓存不存在：{path}（先跑 --fetch）")
            return 2
        cache = load_cache(path)

    if args.cross_check_db:
        res = cross_check_db(cache, use_front_view=False)
        print("\n" + "=" * 100)
        print("X1 · 脚本重建 ≡ 生产表（比较区间 = 双方重叠区间）")
        print("=" * 100)
        print(f"  重叠区间：{res['overlap_start']} ~ {res['overlap_end']}")
        print(f"  逐行相同：{res['same']}")
        print(f"  逐行不同：{res['diff']}")
        print(f"  只在脚本：{res['only_mine']}    只在生产表：{res['only_theirs']}")
        print(
            f"  （脚本窗口更长、生产表未回填到的那段：{res['script_only_outside']} 天 · 不计入判据）"
        )
        for s in res["samples"]:
            print(f"    {s[0]} {s[1]}  脚本={s[2]}  生产={s[3]}")
        ok = res["diff"] == 0 and res["only_mine"] == 0 and res["only_theirs"] == 0
        print(f"  ⇒ {'✅ 一致' if ok else '❌ 不一致'}")
        return 0 if ok else 1

    if args.guard:
        res = cross_check_db(cache, use_front_view=True)
        print("\n" + "=" * 100)
        print("X2 · 口径守卫：撤销 point-in-time 后**必须**与生产表不一致")
        print("=" * 100)
        print(f"  重叠区间：{res['overlap_start']} ~ {res['overlap_end']}")
        print(f"  逐行相同：{res['same']}")
        print(f"  逐行不同：{res['diff']}")
        print(f"  只在脚本：{res['only_mine']}    只在生产表：{res['only_theirs']}")
        for s in res["samples"]:
            print(f"    {s[0]} {s[1]}  前视={s[2]}  生产={s[3]}")
        ok = res["diff"] > 0 or res["only_mine"] > 0
        print(
            f"  ⇒ {'✅ 守卫生效（前视会改写历史值）' if ok else '❌ 守卫失效（前视与生产表一致 ⇒ 生产表可能是前视的）'}"
        )
        return 0 if ok else 1

    report(cache)
    return 0


def main(argv: list[str] | None = None) -> int:
    """入口。

    ``argv`` 可显式传入（离线单测用）⇒ 默认读 ``sys.argv[1:]``。
    """
    parser = argparse.ArgumentParser(description="宏观面证据复算（V0.124.0）")
    parser.add_argument("--fetch", action="store_true", help="联网取数并落缓存")
    parser.add_argument("--cache", help="缓存路径（.pkl）")
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_WINDOW_DAYS,
        help=f"重建窗口（自然日），默认 {DEFAULT_WINDOW_DAYS}",
    )
    parser.add_argument(
        "--cross-check-db",
        action="store_true",
        help="X1：脚本重建 ≡ 生产表（逐行比较）",
    )
    parser.add_argument(
        "--guard",
        action="store_true",
        help="X2：撤销 point-in-time 后必须与生产表不一致",
    )
    args = parser.parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
