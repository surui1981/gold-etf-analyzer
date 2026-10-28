#!/usr/bin/env python
"""资金流因子历史回填脚本（V0.120.0）

把 6 个资金流因子的**自带历史**回填进 ``daily_money_flow_factors`` 表。

背景
----
资金流面的滚动分位窗口按**观测节奏**取（周频 104 周 = 728 日、月频 60 月 = 1826 日），
样本门槛 60 / 40 / 36 个观测。表里一条数据都没有 ⇒ 6 个因子全部退回静态阈带
（``services/money_flow.py`` 里实测标定的 best/worst）。静态带能用，
但要让阈值**跟随市场**就得有历史 —— 而历史一直都在源里（CFTC 年度包 /
FRED 全量 CSV / akshare 全历史 / 上交所按日可查），只是从没被采集。

回填后：滚动分位接管 → ``flow.facets`` 的「N/M 个因子使用滚动分位」badge 才会亮；
同时「末次落库」降级层也有了真实读数可顶。

用法
----
::

    # 默认按各因子自己的窗口回填（周频 728 日 / 月频 1826 日）
    python -m scripts.backfill_money_flow_factors

    # 只回填某一个因子（CFTC 年度包 18MB/个，按需来）
    python -m scripts.backfill_money_flow_factors --factors cot_gold_net cot_gold_flow

    # 指定统一窗口 / 强制重写 / dry-run
    python -m scripts.backfill_money_flow_factors --days 900 --force
    python -m scripts.backfill_money_flow_factors --dry-run

    # **观测口径改了**时：先删掉旧网格的行再回填
    # （旧行不会被新网格的 upsert 覆盖 —— snapshot_date 不同 ⇒ 两张网格并存）
    python -m scripts.backfill_money_flow_factors --factors gold_etf_flow --reset --force

幂等：按 ``(target, snapshot_date, factor_key)`` 覆盖写，重复跑不会产生脏数据。
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.repositories.db import async_session_factory
from app.repositories.money_flow_factor_history import MoneyFlowFactorHistoryRepository
from app.services.money_flow_backfill import (
    BACKFILL_WINDOW_DAYS,
    _min_samples_of,
    backfill_money_flow_history,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def _run(
    days: int | None,
    force: bool,
    dry_run: bool,
    factors: list[str] | None,
    reset: bool = False,
) -> int:
    async with async_session_factory() as session:
        repo = MoneyFlowFactorHistoryRepository(session)
        wanted = list(factors) if factors else list(BACKFILL_WINDOW_DAYS)
        if dry_run:
            print("dry-run：当前各因子窗口内样本数")
            for key in wanted:
                window = days or BACKFILL_WINDOW_DAYS.get(key, 728)
                n = await repo.count_samples("default", key, window)
                # 门槛取规则表的 min_samples —— 与回填本身同一口径
                need_n = _min_samples_of(key)
                flag = "需回填" if (force or n < need_n) else "充足"
                print(f"  {key:<16} 窗口 {window:>5} 日  样本 {n:>5}  需 {need_n:>3}  {flag}")
            return 0

        if reset:
            # 口径改过时，旧网格的行必须先删掉 —— 否则新旧两套观测日并存，
            # 同一周/月被重复计入滚动分位窗口。
            for key in wanted:
                n = await repo.delete_factor("default", key)
                print(f"  重置 {key:<16} 删除 {n} 行")

        result = await backfill_money_flow_history(
            repo,
            target="default",
            days=days,
            force=force,
            factors=factors,
        )
        if not result:
            print("无需回填（各因子样本已充足）")
            return 0
        print("回填完成：")
        for key, n in sorted(result.items()):
            print(f"  {key:<16} {n:>6} 行")
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="资金流因子历史回填（V0.120.0）")
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="统一回填窗口（自然日）；默认按因子各自的窗口（周频 728 / 月频 1826）",
    )
    parser.add_argument(
        "--factors",
        nargs="+",
        default=None,
        help="只回填指定因子，默认全部 6 个",
    )
    parser.add_argument("--force", action="store_true", help="忽略样本数检查，强制重写")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="回填前先删掉目标因子的全部历史行（**观测口径改了**时用："
        "旧网格的行不会被新网格覆盖，两张网格会并存）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不写入")
    args = parser.parse_args(argv)
    return asyncio.run(_run(args.days, args.force, args.dry_run, args.factors, args.reset))


if __name__ == "__main__":
    sys.exit(main())
