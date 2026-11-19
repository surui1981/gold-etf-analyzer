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

#: ★ **显式指定的拟合锚点**（用户 2026-11-19 拍板：「只要 2000 年互联网危机 +
#:   2008 年房地产危机这两轮」）。
#: - ``1999-10`` = 互联网泡沫**前夜**的金价高点（310.72）—— ⚠ 不是泡沫顶点（2000-03），
#:   因为金价在泡沫破裂时并没有「破裂特征」（2000-03 → 2001-04 金价横盘 12 个月）；
#:   用金价高点做锚点才与 2008 轮（2008-03）**同口径** ⇒ 两轮形状可比。
#: - ``2008-03`` = 房地产危机中金价的高点（968.43），雷曼前 6 个月。
#:
#: ⚠ 指定锚点**必须**是「±6 月窗口内的局部高点」⇒ 脚本会校验，不合法直接报错
#:   （防止手滑写错月份而无人发现）。
FIT_ANCHORS = ("1999-10", "2008-03")


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
    ap.add_argument(
        "--fit-anchors",
        default=",".join(FIT_ANCHORS),
        help="★ 显式指定的拟合锚点（逗号分隔的 YYYY-MM）；必须是合法的局部高点",
    )
    ap.add_argument("--target", default=DEFAULT_TARGET)
    ap.add_argument("--dry-run", action="store_true", help="只打印会选出的周期，不写文件")
    args = ap.parse_args()

    xlsx = Path(args.offline) if args.offline else fetch_pink_sheet()
    series, updated = load_gold_monthly(xlsx)
    print(f"月度金价：{len(series)} 行，{series[0]['month']} → {series[-1]['month']}（{updated}）")

    # ── 两批：拟合集（**显式指定**）与参照集（更早的，只展示、不进模板）──
    all_cands = peak_candidates(series)
    months_all = [s["month"] for s in series]

    def _cycle_at(anchor: str, label: str) -> dict:
        """按**指定锚点**取一轮周期（锚点必须是合法的局部高点）。"""
        if anchor not in months_all:
            raise SystemExit(f"锚点 {anchor} 不在月度序列里")
        i = months_all.index(anchor)
        win = [
            series[k]["price"] for k in range(max(0, i - WINDOW), min(len(series), i + WINDOW + 1))
        ]
        peak = series[i]["price"]
        if peak < max(win):
            raise SystemExit(
                f"锚点 {anchor} 不是 ±{WINDOW} 月窗口内的局部高点"
                f"（该月 {peak}，窗口最高 {max(win)}）—— 指定锚点必须真的是金价高点"
            )
        c = build_cycle(
            series,
            {
                "idx": i,
                "month": anchor,
                "price": peak,
                "prominence": round((peak / min(win) - 1) * 100, 1),
                "drawdown": round(
                    (
                        min(
                            series[k]["price"]
                            for k in range(i, min(len(series), i + DRAWDOWN_LOOKAHEAD + 1))
                        )
                        / peak
                        - 1
                    )
                    * 100,
                    1,
                ),
            },
        )
        c["name"] = label
        c["short"] = anchor.replace("-", "")
        c["role"] = "fit"
        return c

    def _build_ref(cands: list[dict], label: str) -> list[dict]:
        out: list[dict] = []
        for p in merge_peaks(cands):
            cyc = build_cycle(series, p)
            # ⚠ 样本边界：周期必须整体早于当前周期起点（当前周期绝不能进模板）
            if months_between(cyc["series"][-1][0], args.current_start) < 0:
                continue
            cyc["role"] = "reference"
            # ⚠ 参照集分两类，**参考性不同**：
            #   · 2000 年前 ⇒ 固定汇率/布雷顿森林体系，金价被行政管制
            #     ⇒ 形态与现代市场不可直接类比 ⇒ **参考性最低**（用户 2026-11-19 口径）；
            #   · 2000 年后但未入选拟合集 ⇒ 是现代市场，只是没被选中 ⇒ 对照用。
            if p["month"] < FIT_START:
                cyc["era"] = "pre_2000"
                cyc["reference_only_reason"] = "固定汇率/布雷顿森林体系下的金价，参考性最低"
            else:
                cyc["era"] = "post_2000_unselected"
                cyc["reference_only_reason"] = "现代市场周期，未入选拟合集（对照用）"
            out.append(cyc)
        print(f"\n{label}：{len(out)} 轮")
        for c in out:
            tag = "（参考性最低）" if c.get("era") == "pre_2000" else ""
            print(
                f"  {c['goldPeak']}  峰价 {c['peakPrice']:>8.2f}  "
                f"prominence {c['prominence_pct']:>5.1f}%  回撤 {c['max_drawdown_pct']:>6.1f}%  "
                f"序列 {len(c['series']):>2d} 月 → {c['series'][-1][0]}{tag}"
            )
        return out

    anchors = [a.strip() for a in args.fit_anchors.split(",") if a.strip()]
    labels = {
        "1999-10": "2000 互联网泡沫（金价高点 1999-10）",
        "2008-03": "2008 房地产危机（金价高点 2008-03）",
    }
    cycles = []
    for a in anchors:
        c = _cycle_at(a, labels.get(a, f"{a} 起的一轮金价周期"))
        # ⚠ 样本边界：拟合集也必须整体早于当前周期起点
        if months_between(c["series"][-1][0], args.current_start) < 0:
            raise SystemExit(f"拟合锚点 {a} 的序列伸进了当前周期（{c['series'][-1][0]}）⇒ 自我拟合")
        cycles.append(c)
    print(f"\n拟合集（**显式指定** {len(cycles)} 轮，只有它们进等权平均）：")
    for c in cycles:
        print(
            f"  {c['goldPeak']}  {c['name']}  峰价 {c['peakPrice']:>8.2f}  "
            f"序列 {len(c['series']):>2d} 月 → {c['series'][-1][0]}"
        )

    # 参照集 = 自动识别出的、更早的周期，**排除**已被指定进拟合集的锚点
    used = set(anchors)
    reference_cycles = _build_ref(
        [c for c in all_cands if c["month"] not in used],
        "参照集（不参与拟合的其它周期，只展示）",
    )

    if args.dry_run:
        return 0

    payload = {
        "schema_version": 1,
        "target": args.target,
        "horizon_months": 30,
        "price_basis": "monthly_average",
        "fit_window": {"start": args.fit_start, "end": args.current_start},
        "reference_window": {"start": series[0]["month"], "end": args.current_start},
        "fit_anchors": anchors,
        "fit_selection": "explicit",
        "provenance": {
            "source": "世界银行 Pink Sheet（Commodity Price Data）月度表 Gold 列",
            "url": PINK_SHEET_URL,
            "coverage": f"{series[0]['month']} → {series[-1]['month']}（月度金价 $/troy oz）",
            "method": "London fix 月均。★ **拟合集是显式指定的**（用户 2026-11-19 拍板）："
            f"{', '.join(anchors)} —— 互联网泡沫（金价高点 1999-10，泡沫前夜）+ "
            "房地产危机（金价高点 2008-03）；只有这两轮进等权平均。"
            "参照集由「±6 月局部高点 + prominence≥10% + 同episode归并 + 后续36月回撤≥10%」"
            "自动识别（无人工挑选），只展示、不进模板；它们在固定汇率体系下 ⇒ 参考性最低",
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
