#!/usr/bin/env python
"""构建「历史危机金价周期」产物（V0.128.0）。

产物：``src/app/assets/forecast/crisis_cycles.json``
消费方：``src/app/services/crisis_cycle_fit.py``（``load_crisis_cycles``）⇒ 线上只读产物，**不联网**。

数据源（**免费、可复核**）
--------------------------
**世界银行 Pink Sheet**（Commodity Price Data）月度表的 ``Gold`` 列（$/troy oz）：
``https://thedocs.worldbank.org/en/doc/5d903e848db1d1b83e0ec8f744e55570-0350012021/related/CMO-Historical-Data-Monthly.xlsx``

⚠ 为什么不用东财的 COMEX 黄金日线（``push2his``）做模板：
它只到 **1990-01** ⇒ 拿不到 1974 / 1980 这两轮最经典的黄金周期。
Pink Sheet 的月度金价到 **1960-01** ⇒ 1974/1980 都在。
⚠ 口径差异：Pink Sheet 是**伦敦现货 fix 月均**；仓库自己的当前周期用的是
**COMEX 期货**（``gold_price_daily`` / ``target='ny'``）⇒ **形状可比、绝对价位不可比**。
算法对每轮周期各自归一（高点=100）⇒ 模板只贡献**形状**，不贡献价位 ✔。

周期选取规则（**可复现，不人工挑选**）
--------------------------------------
1. **局部高点**：月序列在某月 ±``WINDOW``(6) 个月窗口内最高；
2. **显著性**：该高点比窗口内最低点高 ≥ ``MIN_PROMINENCE``(10%) ⇒ 去掉平盘噪声；
3. **高点归并**：两个候选高点相隔 < ``MERGE_MONTHS``(18) 个月 ⇒ 视为同一轮行情，**取更高者**；
4. **熊市过滤**：高点之后 36 个月内最大回撤 ≥ ``MIN_DRAWDOWN``(15%) ⇒ 只要「顶 → 熊」的周期；
5. **样本边界**：周期必须**整体早于**当前周期起点（``--current-start``，默认 2016-11）——
   当前周期**绝不能**进模板（自我拟合 ⇒ 证据门 E3）；
6. **序列长度**：从高点月起到价格**回到该高点**（或 ``MAX_MONTHS``(60) 个月上限）为止。

用法
----
```bash
# 联网拉取并生成（默认写到 src/app/assets/forecast/crisis_cycles.json）
PYTHONPATH=src:. .venv/bin/python scripts/build_crisis_cycles.py

# 离线：用已下载的 xlsx 复现（可复核）
PYTHONPATH=src:. .venv/bin/python scripts/build_crisis_cycles.py --offline /tmp/pink.xlsx

# 只看会选出哪些周期（不写文件）
PYTHONPATH=src:. .venv/bin/python scripts/build_crisis_cycles.py --dry-run
```
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from app.services.crisis_cycle_fit import (  # noqa: E402
    DEFAULT_TARGET,
    month_index,
    months_between,
)

PINK_SHEET_URL = (
    "https://thedocs.worldbank.org/en/doc/5d903e848db1d1b83e0ec8f744e55570-0350012021"
    "/related/CMO-Historical-Data-Monthly.xlsx"
)
OUT_FILE = ROOT / "src" / "app" / "assets" / "forecast" / "crisis_cycles.json"

WINDOW = 6  # 局部高点判定窗口（±6 个月）
MIN_PROMINENCE = 10.0  # 高点相对窗口最低点的最小涨幅（%）
MERGE_MONTHS = 18  # 高点归并窗口（月）
MIN_DRAWDOWN = 10.0  # 「金价破裂」= 高点后 36 个月内回撤 ≥ 10%
MAX_MONTHS = 60  # 单轮周期的最长序列（月）
DRAWDOWN_LOOKAHEAD = 36  # 回撤观察窗（月）

#: **拟合窗口起点**：只有这之后的周期参与模板（等权平均）；
#: 更早的周期仍收进产物，但只作**参照**（另一张图展示，不进拟合）。
FIT_START = "2000-01"


def fetch_pink_sheet() -> Path:
    """下载 Pink Sheet 到临时文件（``--offline`` 可跳过）。"""
    import requests

    print(f"下载 Pink Sheet … {PINK_SHEET_URL}")
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        path = Path(tmp.name)
    r = requests.get(PINK_SHEET_URL, timeout=120)
    r.raise_for_status()
    path.write_bytes(r.content)
    print(f"  → {path}（{len(r.content):,} bytes）")
    return path


def load_gold_monthly(xlsx_path: Path) -> tuple[list[dict], str]:
    """从 Pink Sheet 的「Monthly Prices」表读 ``Gold`` 列（$/troy oz）。"""
    import pandas as pd

    df = pd.read_excel(xlsx_path, sheet_name="Monthly Prices", header=None)
    header_row = next(i for i in range(20) if df.iat[i, 1] == "Crude oil, average")
    names = [str(df.iat[header_row, c]) for c in range(df.shape[1])]
    gold_col = names.index("Gold")
    updated = str(df.iat[3, 0])

    out: list[dict] = []
    for i in range(header_row + 2, len(df)):
        mk = df.iat[i, 0]
        val = df.iat[i, gold_col]
        if not isinstance(mk, str) or not re.fullmatch(r"\d{4}M\d{2}", mk):
            continue
        if not isinstance(val, (int, float)):  # "…" = 该月缺失
            continue
        y, m = mk.split("M")
        out.append({"month": f"{int(y)}-{int(m):02d}", "price": round(float(val), 2)})
    return out, updated


def peak_candidates(series: list[dict], start: str | None = None) -> list[dict]:
    """局部高点候选（**未归并**）—— 显著性 + 「破裂」幅度两条过滤。

    ``start`` 给定时只保留该月之后的高点。
    """
    px = [s["price"] for s in series]
    months = [s["month"] for s in series]
    lo_idx = 0 if not start else next((i for i, m in enumerate(months) if m >= start), len(series))

    cands: list[dict] = []
    for i in range(max(WINDOW, lo_idx), len(series) - WINDOW):
        win = px[i - WINDOW : i + WINDOW + 1]
        if px[i] < max(win) or px[i] <= min(win):
            continue
        prominence = (px[i] / min(win) - 1) * 100
        if prominence < MIN_PROMINENCE:
            continue
        fut = px[i : i + DRAWDOWN_LOOKAHEAD + 1]
        drawdown = (min(fut) / px[i] - 1) * 100
        if drawdown > -MIN_DRAWDOWN:
            continue
        cands.append(
            {
                "idx": i,
                "month": months[i],
                "price": px[i],
                "prominence": round(prominence, 1),
                "drawdown": round(drawdown, 1),
            }
        )
    return cands


def merge_peaks(cands: list[dict]) -> list[dict]:
    """高点归并：相隔 < ``MERGE_MONTHS`` 的视为同一轮行情，取更高者。

    ⚠ **必须分批归并**：跨批次归并会用窗口边界「吞掉」边界附近的一轮行情
    （1999-10 会把 2001-09 那次 9/11 尖峰合并掉）。
    """
    cands = sorted(cands, key=lambda c: month_index(c["month"]))
    merged: list[dict] = []
    for c in cands:
        if merged and month_index(c["month"]) - month_index(merged[-1]["month"]) < MERGE_MONTHS:
            if c["price"] > merged[-1]["price"]:
                merged[-1] = c
            continue
        merged.append(c)
    return merged


def find_peaks(series: list[dict], start: str | None = None) -> list[dict]:
    """按文档里的规则挑出周期高点（候选 → 归并）。"""
    return merge_peaks(peak_candidates(series, start=start))


def build_cycle(series: list[dict], peak: dict) -> dict:
    """一轮周期 = 高点月 → 价格回到高点（或 ``MAX_MONTHS`` 上限）。"""
    px = [s["price"] for s in series]
    months = [s["month"] for s in series]
    i = peak["idx"]
    end = i
    limit = min(len(series), i + MAX_MONTHS + 1)
    while end + 1 < limit:
        nxt = end + 1
        if px[nxt] >= px[i]:  # 回到高点 ⇒ 周期结束
            break
        end = nxt
    rows = [[months[k], px[k]] for k in range(i, end + 1)]
    return {
        "name": f"{peak['month']} 起的一轮金价周期",
        "short": peak["month"].replace("-", ""),
        "goldPeak": peak["month"],
        "peakPrice": peak["price"],
        "prominence_pct": peak["prominence"],
        "max_drawdown_pct": peak["drawdown"],
        "series": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="构建历史危机金价周期产物")
    ap.add_argument("--offline", help="用本地已下载的 Pink Sheet xlsx（不联网）")
    ap.add_argument("--out", default=str(OUT_FILE), help="产物输出路径")
    ap.add_argument("--current-start", default="2016-11", help="当前周期起点（其后的周期不进模板）")
    ap.add_argument(
        "--fit-start",
        default=FIT_START,
        help="拟合窗口起点（更早的周期只作参照，不进模板）",
    )
    ap.add_argument("--target", default=DEFAULT_TARGET)
    ap.add_argument("--dry-run", action="store_true", help="只打印会选出的周期，不写文件")
    args = ap.parse_args()

    xlsx = Path(args.offline) if args.offline else fetch_pink_sheet()
    series, updated = load_gold_monthly(xlsx)
    print(f"月度金价：{len(series)} 行，{series[0]['month']} → {series[-1]['month']}（{updated}）")

    # ── 两批：拟合集（fit_start 之后）与参照集（之前，只展示、不进模板）──
    all_cands = peak_candidates(series)

    def _build(cands: list[dict], label: str) -> list[dict]:
        out: list[dict] = []
        for p in merge_peaks(cands):
            cyc = build_cycle(series, p)
            # ⚠ 样本边界：周期必须整体早于当前周期起点（当前周期绝不能进模板）
            if months_between(cyc["series"][-1][0], args.current_start) < 0:
                continue
            out.append(cyc)
        print(f"\n{label}：{len(out)} 轮")
        for c in out:
            print(
                f"  {c['goldPeak']}  峰价 {c['peakPrice']:>8.2f}  "
                f"prominence {c['prominence_pct']:>5.1f}%  回撤 {c['max_drawdown_pct']:>6.1f}%  "
                f"序列 {len(c['series']):>2d} 月 → {c['series'][-1][0]}"
            )
        return out

    cycles = _build(
        [c for c in all_cands if c["month"] >= args.fit_start],
        f"拟合集（{args.fit_start} 之后，当前周期起点 {args.current_start} 之前）",
    )
    reference_cycles = _build(
        [c for c in all_cands if c["month"] < args.fit_start],
        f"参照集（{args.fit_start} 之前，只展示、不进拟合）",
    )

    if args.dry_run:
        return 0

    payload = {
        "schema_version": 1,
        "target": args.target,
        "horizon_months": 30,
        "price_basis": "monthly_average",
        "fit_window": {"start": args.fit_start, "end": args.current_start},
        "reference_window": {"start": series[0]["month"], "end": args.fit_start},
        "provenance": {
            "source": "世界银行 Pink Sheet（Commodity Price Data）月度表 Gold 列",
            "url": PINK_SHEET_URL,
            "coverage": f"{series[0]['month']} → {series[-1]['month']}（月度金价 $/troy oz）",
            "method": "London fix 月均；周期按「±6 月局部高点 + prominence≥10% + 同episode归并 + "
            "后续36月回撤≥10%（金价破裂）+ 早于当前周期起点」自动识别（无人工挑选）；"
            f"拟合只取 {args.fit_start} 之后的周期，更早的进 reference_cycles（只展示、不进模板）",
            "updated": updated,
            "exported_at": "2026-11-18",
            "note": "当前周期用仓库自己的 COMEX 期货价（gold_price_daily/target=ny），"
            "与本模板的伦敦现货口径不同 ⇒ 只影响绝对价位，形状（归一后）可比",
        },
        "cycles": cycles,
        "reference_cycles": reference_cycles,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"\n已写入 {out}（{out.stat().st_size:,} bytes；"
        f"拟合 {len(cycles)} 轮 / 参照 {len(reference_cycles)} 轮）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
