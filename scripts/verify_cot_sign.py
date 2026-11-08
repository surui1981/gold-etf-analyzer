#!/usr/bin/env python3
"""验证资金流面 ``cot_gold_net`` 的**符号方向**（V0.122.0）。

背景
----
``cot_gold_net`` = CFTC 黄金管理基金**净多占持仓比 %**（投机盘的拥挤度）。
它自 V0.122.0 起按 **负号（拥挤度口径）** 计分：值越高 = 越拥挤 = 越利空黄金。
本脚本负责回答「这个符号方向到底对不对」，并**能被证伪**（判据不成立 ⇒ 退出码 1）。

为什么需要专门的脚本
--------------------
符号方向不是拍脑袋，也不是看一眼相关就能定 —— 直接算会被三层假象骗：

1. **年份效应**：年内的前瞻收益高度持续，池化相关主要在测「年度共振」；
2. **重叠窗口的机械伪相关**：``fwd_h`` 与 ``past_h`` 共享端点 ``P(t)``，
   随机游走下水平代理对「回看」的相关天然远大于对「前瞻」的相关；
3. **水平代理 ≠ 真预测**：一个只是「当期金价的代理」的因子，
   对回看窗口的相关会**同样强甚至更强** ⇒ 只有「前瞻显著强于回看」才算预测力。

本脚本采用的口径（与 ``services/money_flow.py`` 模块文档一致）
--------------------------------------------------------
- 因子：**原始**净多占 OI %（周频观测 ⇒ 按日频日历前向填充，**不回填未来**）；
- 分组：**年内**秩 → **年内**五分位（每年各 5 组 ⇒ 不让某一年主导样本）；
- 前瞻收益：**60 个交易日**（不是 60 周！周频序列上直接 shift 会算成 60 周）；
- 硬判据只看**方向**：Q1（最不拥挤）的前瞻收益应 **> ** Q5（最拥挤）⇒ 符号必须是负。

数据源（需联网）
----------------
- CFTC 年度分类持仓包 ``fut_disagg_txt_{year}.zip``（仓库自带的 ``fetch_cftc_gold_history``）；
- Yahoo 日线（仓库自带的 ``fetch_yahoo_daily``）—— 核心标的 **GLD**（美元金价）。

用法
----
    PYTHONPATH=src:. python scripts/verify_cot_sign.py [--years 12] [--symbol GLD]

⚠ 本脚本**不在 CI 门禁集里**（依赖外网 + 18MB/年的 CFTC 包），
   属于「按需复算证据」的工具；线上跑的硬门禁是 ``tests/test_services/test_money_flow_service.py``
   里的「静态带方向与 ``positive`` 标志一致」不变式。
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.config import get_settings
from app.repositories.macro_sources import fetch_yahoo_daily
from app.repositories.money_flow_sources import fetch_cftc_gold_history

#: 前瞻窗口（交易日）
FWD_DAYS = 60
#: 分区间的年份切分（近三段；第一段的起点随 ``--years`` 变，这里按 12 年回看写）
SPANS = ((2015, 2018), (2019, 2022), (2023, 2030))


def _quintile_by_order(values: list[float]) -> list[int]:
    """按**值**排序（同值按出现顺序）后等分成 5 组，返回每条的组号 1..5。

    等价于 pandas 的 ``groupby(yr).transform(lambda s: pd.qcut(s.rank(method="first"), 5))``：
    分组按**因子值**（不是按时间顺序），但每组**天数**相等。
    """
    n = len(values)
    order = sorted(range(n), key=lambda i: (values[i], i))
    out = [0] * n
    for pos, idx in enumerate(order):
        p = (pos + 1) / n
        if p <= 0.2:
            g = 1
        elif p <= 0.4:
            g = 2
        elif p <= 0.6:
            g = 3
        elif p <= 0.8:
            g = 4
        else:
            g = 5
        out[idx] = g
    return out


def _corr(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return float("nan")
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return float("nan")
    return sxy / math.sqrt(sxx * syy)


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


async def collect(years: int, symbol: str):
    cot = await fetch_cftc_gold_history(years=years)
    px = await fetch_yahoo_daily(
        symbol, base_url=get_settings().yahoo_chart_url, range_="max", interval="1d"
    )
    return cot, px


def analyse(cot, px) -> dict:
    """把周频因子对齐到日频日历，算方向证据。"""
    fac = sorted({p.obs_date: p.net_pct_oi for p in cot}.items())
    price = sorted(px)
    if not fac or len(price) < FWD_DAYS + 10:
        return {}

    first = fac[0][0]
    last = fac[-1][0]
    cal = [(d, v) for d, v in price if first <= d <= last]
    if len(cal) < FWD_DAYS + 10:
        return {}

    # 因子前向填充到日频日历（只用观测日当天及之前的值）
    fvals: list[float] = []
    j = 0
    for d, _ in cal:
        while j + 1 < len(fac) and fac[j + 1][0] <= d:
            j += 1
        if fac[j][0] > d:
            fvals.append(float("nan"))
        else:
            fvals.append(fac[j][1])

    px_vals = [v for _, v in cal]
    dates = [d for d, _ in cal]
    n = len(dates)

    # 前瞻 60 交易日收益
    fwd: list[float | None] = []
    for i in range(n):
        if i + FWD_DAYS < n and px_vals[i] > 0:
            fwd.append(px_vals[i + FWD_DAYS] / px_vals[i] - 1.0)
        else:
            fwd.append(None)

    # 样本 = 有前瞻收益的行（末尾 60 个交易日没有前瞻 ⇒ 不进样本）
    sample = [i for i in range(n) if fwd[i] is not None]

    # 年内五分位（按因子值分组、每组天数相等）—— 只在**样本内**分组
    by_year: dict[int, list[int]] = {}
    for i in sample:
        by_year.setdefault(dates[i].year, []).append(i)
    quint: dict[int, int] = {}
    for _yr, idxs in by_year.items():
        vals = [fvals[i] for i in idxs]
        if any(math.isnan(v) for v in vals):
            continue
        for i, g in zip(idxs, _quintile_by_order(vals), strict=True):
            quint[i] = g

    # 汇总
    def collect_q(lo: int, hi: int) -> dict[int, list[float]]:
        out: dict[int, list[float]] = {}
        for i in sample:
            if not (lo <= dates[i].year <= hi):
                continue
            if i not in quint:
                continue
            out.setdefault(quint[i], []).append(fwd[i] * 100.0)
        return out

    def spread(q: dict[int, list[float]]) -> float | None:
        if 1 not in q or 5 not in q:
            return None
        return _mean(q[1]) - _mean(q[5])

    full = collect_q(2013, 2030)
    # 水平代理对照：价格水平对「前瞻 / 回看」的相关
    lvl, fv = [], []
    for i in sample:
        lvl.append(px_vals[i])
        fv.append(fwd[i])
    lvl2, pv = [], []
    for i in sample:
        if i < FWD_DAYS:
            continue
        lvl2.append(px_vals[i])
        pv.append(px_vals[i] / px_vals[i - FWD_DAYS] - 1.0)

    return {
        "n": len(sample),
        "span": (dates[0], dates[-1]),
        "quint": full,
        "spread": spread(full),
        "spans": {
            f"{lo}-{hi}": {
                "spread": spread(collect_q(lo, hi)),
                "n": sum(len(v) for v in collect_q(lo, hi).values()),
            }
            for lo, hi in SPANS
        },
        "lvl_fwd": _corr(lvl, fv),
        "lvl_past": _corr(lvl2, pv),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="验证 cot_gold_net 的符号方向")
    ap.add_argument("--years", type=int, default=12, help="CFTC 回看自然年个数（含当年）")
    ap.add_argument("--symbol", default="GLD", help="核心标的（默认 GLD 美元金价）")
    args = ap.parse_args()

    cot, px = asyncio.run(collect(args.years, args.symbol))
    if not cot or not px:
        print("❌ 取数失败（CFTC 或 Yahoo）—— 无法复算，请检查网络")
        return 1

    res = analyse(cot, px)
    if not res:
        print("❌ 样本不足（CFTC 或价格序列太短）")
        return 1

    lo_d, hi_d = res["span"]
    print(f"\n=== cot_gold_net 符号方向验证（{args.symbol}）===")
    print(f"样本 {lo_d} → {hi_d}   n={res['n']}   前瞻窗口 {FWD_DAYS} 交易日")
    print("\n年内五分位的前瞻收益均值（Q1 = 净多最低 ⇒ 最不拥挤）：")
    for q in sorted(res["quint"]):
        print(f"   Q{q} = {_mean(res['quint'][q]):+.3f}%   n={len(res['quint'][q])}")
    print(f"   ⇒ Q1 − Q5 = {res['spread']:+.3f} pp")
    print("\n分区间：")
    for nm, d in res["spans"].items():
        sp = d["spread"]
        txt = "样本不足" if sp is None else f"{sp:+.3f} pp"
        print(f"   {nm}: {txt}   n={d['n']}")
    print("\n水平代理对照（伪相关的签名）：")
    print(f"   corr(金价水平, 前瞻{FWD_DAYS}) = {res['lvl_fwd']:+.4f}")
    print(f"   corr(金价水平, 回看{FWD_DAYS}) = {res['lvl_past']:+.4f}")
    print("   ⇒ 水平代理对「回看」的相关天然更强 ⇒ 前瞻相关必须先控制当期金价水平")

    passed = 0
    failed: list[str] = []

    if res["spread"] is None:
        failed.append("全样本五分位差算不出来")
    elif res["spread"] <= 0:
        failed.append(f"全样本 Q1−Q5 = {res['spread']:+.3f} pp ≤ 0 ⇒ 方向不是「越拥挤越差」")
    else:
        print(f"\n✅ C1 全样本方向：Q1 比 Q5 高 {res['spread']:.3f} pp ⇒ 符号应为负（拥挤度口径）")
        passed += 1

    pos = [nm for nm, d in res["spans"].items() if d["spread"] is not None and d["spread"] > 0]
    if len(pos) >= 2:
        print(f"✅ C2 分区间方向：{len(pos)}/{len(res['spans'])} 段为正 ⇒ 方向跨行情一致")
        passed += 1
    else:
        failed.append(f"分区间只有 {len(pos)}/{len(res['spans'])} 段为正 ⇒ 方向不稳")

    if res["lvl_past"] > res["lvl_fwd"]:
        print("✅ C3 水平代理对照成立 ⇒ 管线必须控制当期金价水平（已做）")
        passed += 1
    else:
        failed.append("水平代理对照不成立 ⇒ 管线设计需复查")

    print(f"\n结果：{passed} passed" + (f"，{len(failed)} failed" if failed else ""))
    for f in failed:
        print(f"❌ {f}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
