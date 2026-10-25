#!/usr/bin/env python
"""宏观因子历史回填脚本（V0.118.0）

把 H.15 / FRED / Yahoo 的**自带历史**回填进 ``daily_macro_factors`` 表。

背景
----
V0.79.0 Step E 造的「近 252 个交易日滚动 90/10 分位」动态阈值机制**从未真正生效**：
该表在 2026-10-25 只有 18 天样本，而 ``MacroThresholdCalculator`` 要求单因子
≥ 60 个样本才切动态阈值。结果全部因子被钉死在 2020-2023 的硬编码 ``best/worst``
上 —— ``us10y``（4.96% vs worst 4.5）与 ``us30y``（5.29% vs worst 5.0）长期
输出 **0 分**，合计 35% 的宏观权重贡献恒为 0。

数据一直都在，只是没被采集。本脚本把三个源的历史灌进去，回填后滚动分位
立刻接管，阈值自动跟随市场。

用法
----
::

    # 默认回填最近 252 个自然日窗口内的所有可得历史
    python -m scripts.backfill_macro_factors

    # 指定窗口天数 / 强制重写 / dry-run
    python -m scripts.backfill_macro_factors --days 400
    python -m scripts.backfill_macro_factors --force
    python -m scripts.backfill_macro_factors --dry-run

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
    DEFAULT_MIN_SAMPLES,
    DEFAULT_WINDOW_DAYS,
    backfill_macro_history,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def _run(days: int, min_samples: int, force: bool, dry_run: bool) -> int:
    async with async_session_factory() as session:
        repo = MacroFactorHistoryRepository(session)
        if dry_run:
            counts = {}
            for key in ("dxy", "us2y", "us10y", "us30y", "curve_10y2y", "real10y", "vix"):
                counts[key] = await repo.count_samples("default", key, days)
            print(f"dry-run：当前窗口内各因子样本数（目标 ≥{min_samples}）")
            for key, n in counts.items():
                flag = "需回填" if (force or n < min_samples) else "充足"
                print(f"  {key:<14} {n:>5}  {flag}")
            return 0

        result = await backfill_macro_history(
            repo,
            target="default",
            days=days,
            min_samples=min_samples,
            force=force,
        )
        if not result:
            print("无需回填（各因子样本已充足）")
            return 0
        print("回填完成：")
        for key, n in sorted(result.items()):
            print(f"  {key:<14} {n:>5} 行")
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="宏观因子历史回填（V0.118.0）")
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_WINDOW_DAYS,
        help=f"回填窗口（自然日），默认 {DEFAULT_WINDOW_DAYS}",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=DEFAULT_MIN_SAMPLES,
        help=f"低于该样本数的因子才回填，默认 {DEFAULT_MIN_SAMPLES}",
    )
    parser.add_argument("--force", action="store_true", help="忽略样本数检查，强制重写")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不写入")
    args = parser.parse_args(argv)
    return asyncio.run(_run(args.days, args.min_samples, args.force, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
