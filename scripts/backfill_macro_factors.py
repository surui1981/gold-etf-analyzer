#!/usr/bin/env python
"""宏观因子历史回填脚本（V0.118.0 日常补缺口 · V0.124.0 深回填）。

把 H.15 / FRED / Yahoo / WGC / Eurostat 的**自带历史**回填进
``daily_macro_factors`` 表。

背景
----
V0.79.0 Step E 造的「近 252 个交易日滚动 90/10 分位」动态阈值机制**从未真正生效**：
该表在 2026-10-25 只有 18 天样本，而 ``MacroThresholdCalculator`` 要求单因子
≥ 60 个样本才切动态阈值。结果全部因子被钉死在 2020-2023 的硬编码 ``best/worst``
上 —— ``us10y``（4.96% vs worst 4.5）与 ``us30y``（5.29% vs worst 5.0）长期
输出 **0 分**，合计 35% 的宏观权重贡献恒为 0。

数据一直都在，只是没被采集。本脚本把各源的历史灌进去，回填后滚动分位
立刻接管，阈值自动跟随市场。

三种模式
--------
======================  ==========================================  ==================
模式                    干什么                                      因子
======================  ==========================================  ==================
（默认）                **日常补缺口**：窗口内样本不足的才回填，     7 个日频
                        行粒度 = **交易日**（= 源数据的观测日）
``--all-factors``      在默认模式之上，**额外**用同一套 point-in-time  7 日频 + 4 低频
                        口径补上 4 个低频因子（当前窗口）
``--deep``             **深回填**：point-in-time + **日历日**粒度 +   11 个（全部）
                        多年窗口（默认 5 年）—— 一次性铺历史
======================  ==========================================  ==================

⚠ **行粒度的差别不是小事**：线上 ``daily_capture_loop`` 每天 07:00 触发、
**无星期过滤** ⇒ 库里每个日历日都有一行（周末也有，值沿用上一交易日）。
滚动分位窗口是 252 **日历**日 ⇒ 只写交易日会让窗口里的样本数与线上不一致
⇒ P10/P90 算出不同的数 ⇒ 「复算」就不是生产口径了。``--deep`` 用日历日。

⚠ **低频因子的已知偏差**：point-in-time 重建把季度/年度读数按**观测期末**
判定为可得（WGC GDT 实际滞后约 1~2 个月、FRED 债务约 1 个季度）⇒
相对真实发布**乐观了最多一个观测期** ⇒ 该偏差只会**高估**低频因子的
前瞻力 ⇒ 若低频组实测不过三问，结论是保守且安全的。

用法
----
::

    # 默认回填最近 252 个自然日窗口内的所有可得历史
    python -m scripts.backfill_macro_factors

    # 指定窗口天数 / 强制重写 / dry-run
    python -m scripts.backfill_macro_factors --days 400
    python -m scripts.backfill_macro_factors --force
    python -m scripts.backfill_macro_factors --dry-run

    # V0.124.0：低频因子补写（当前窗口，只拉低频源）
    python -m scripts.backfill_macro_factors --all-factors

    # V0.124.0：深回填（11 因子 / 日历日 / point-in-time / 默认 5 年）
    python -m scripts.backfill_macro_factors --deep --dry-run
    python -m scripts.backfill_macro_factors --deep
    python -m scripts.backfill_macro_factors --deep --days 1825

幂等：按 ``(target, snapshot_date, factor_key)`` 覆盖写，重复跑不会产生脏数据。
``daily_capture_and_warm`` 的 step 3 也会调用同一个服务函数补缺口，
所以本脚本主要用于**部署后立刻见效**，而不是必须执行的步骤。
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.repositories.db import async_session_factory
from app.repositories.macro_factor_history import MacroFactorHistoryRepository
from app.services.macro_backfill import (
    DEEP_LOWFREQ_FACTORS,
    DEEP_WINDOW_DAYS,
    DEFAULT_MIN_SAMPLES,
    DEFAULT_WINDOW_DAYS,
    backfill_macro_history,
    backfill_macro_history_deep,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: 日常模式回填的 7 个日频因子（与 ``backfill_macro_history`` 内部一致）
_DAILY_KEYS = ("dxy", "us2y", "us10y", "us30y", "curve_10y2y", "real10y", "vix")


async def _run(
    days: int | None,
    min_samples: int,
    force: bool,
    dry_run: bool,
    deep: bool,
    all_factors: bool,
) -> int:
    async with async_session_factory() as session:
        repo = MacroFactorHistoryRepository(session)

        # ── 深回填 ──
        if deep:
            window = days if days is not None else DEEP_WINDOW_DAYS
            print(f"深回填（11 因子 · 日历日 · point-in-time）：窗口 {window} 天")
            result = await backfill_macro_history_deep(
                repo,
                target="default",
                days=window,
                dry_run=dry_run,
            )
            if not result:
                print("窗口内没有可用历史数据（各源取数都失败？）")
                return 1
            label = "dry-run 计划写入" if dry_run else "写入完成"
            print(f"{label}：合计 {sum(result.values())} 行")
            for key in sorted(result):
                print(f"  {key:<16} {result[key]:>6} 行")
            if all_factors:
                print("（--all-factors 在 --deep 下是冗余的：深回填本来就含 4 个低频因子）")
            return 0

        # ── 日常补缺口 ──
        window = days if days is not None else DEFAULT_WINDOW_DAYS
        if dry_run:
            counts = {}
            for key in _DAILY_KEYS:
                counts[key] = await repo.count_samples("default", key, window)
            print(f"dry-run：当前窗口（{window} 天）内各因子样本数（目标 ≥{min_samples}）")
            for key, n in counts.items():
                flag = "需回填" if (force or n < min_samples) else "充足"
                print(f"  {key:<16} {n:>5}  {flag}")
        else:
            result = await backfill_macro_history(
                repo,
                target="default",
                days=window,
                min_samples=min_samples,
                force=force,
            )
            if result:
                print(f"回填完成（合计 {sum(result.values())} 行）：")
                for key, n in sorted(result.items()):
                    print(f"  {key:<16} {n:>5} 行")
            else:
                print("无需回填（各因子样本已充足）")

        # ── 低频因子补写（point-in-time · 日历日 · 当前窗口）──
        if all_factors:
            print(f"低频因子补写（{', '.join(DEEP_LOWFREQ_FACTORS)} · 窗口 {window} 天）")
            low = await backfill_macro_history_deep(
                repo,
                target="default",
                days=window,
                dry_run=dry_run,
                factors=DEEP_LOWFREQ_FACTORS,
            )
            if not low:
                print("  低频因子：窗口内没有可用历史数据")
            else:
                label = "dry-run 计划写入" if dry_run else "写入完成"
                print(f"  {label}：合计 {sum(low.values())} 行")
                for key in sorted(low):
                    print(f"  {key:<16} {low[key]:>6} 行")
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="宏观因子历史回填（V0.118.0 / V0.124.0）")
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help=(
            "回填窗口（自然日）；默认：日常模式 "
            f"{DEFAULT_WINDOW_DAYS}、--deep 模式 {DEEP_WINDOW_DAYS}"
        ),
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=DEFAULT_MIN_SAMPLES,
        help=f"低于该样本数的因子才回填，默认 {DEFAULT_MIN_SAMPLES}",
    )
    parser.add_argument("--force", action="store_true", help="忽略样本数检查，强制重写")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不写入")
    parser.add_argument(
        "--deep",
        action="store_true",
        help=(f"深回填：11 因子 · 日历日 · point-in-time · 多年窗口（默认 {DEEP_WINDOW_DAYS} 天）"),
    )
    parser.add_argument(
        "--all-factors",
        action="store_true",
        help="额外补写 4 个低频因子（point-in-time · 日历日 · 当前窗口）",
    )
    args = parser.parse_args(argv)
    return asyncio.run(
        _run(
            args.days,
            args.min_samples,
            args.force,
            args.dry_run,
            args.deep,
            args.all_factors,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
