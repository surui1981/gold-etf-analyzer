#!/usr/bin/env python
"""打分数据宽表回填脚本（V0.92.0 · 历史打分数据汇总）

扫 ``daily_snapshots`` 表中某区间内的全部日期，对每日触发
``ScoringWideService.rebuild`` ETL。结果写入 ``scoring_daily_wide``。

用法
----
::

    # 默认从 V0.66.0 上线日到今天
    python -m scripts.backfill_scoring_wide

    # 指定区间
    python -m scripts.backfill_scoring_wide --from 2026-01-01 --to 2026-10-12

    # dry-run（只打印计划，不写入）
    python -m scripts.backfill_scoring_wide --dry-run

⚠ V0.79.0 任务 #162 教训：宽表 ETL 失败**不**回滚源表 —— 宽表是"读优化副本"。
   本脚本中 rebuild() 内部 try/except 已捕获失败并 log.warning；本 CLI 仅汇总
   成功/失败计数，**不**为单日失败中断回填（断点续跑友好）。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.config import get_settings
from app.models.snapshot import DailySnapshot
from app.repositories.db import async_session_factory
from app.repositories.news import NewsScoreRepository
from app.repositories.review import GoldPriceRepository
from app.repositories.scoring_wide import ScoringWideRepository
from app.repositories.snapshot import SnapshotRepository
from app.services.scoring_wide import ScoringWideService
from app.utils.logger import get_logger

logger = get_logger(__name__)


# V0.66.0 上线日（review 价格日历 + basis 字段起点）；之前无完整打分明细。
DEFAULT_FROM = date(2024, 9, 1)


async def _collect_snapshot_dates(start: date, end: date) -> list[date]:
    """从 daily_snapshots 收集区间内全部有数据的日期。"""
    async with async_session_factory() as session:
        stmt = (
            select(DailySnapshot.snapshot_date)
            .where(
                DailySnapshot.snapshot_date >= start,
                DailySnapshot.snapshot_date <= end,
            )
            .distinct()
            .order_by(DailySnapshot.snapshot_date)
        )
        result = await session.execute(stmt)
        return [row[0] for row in result.all()]


async def _run_backfill(start: date, end: date, dry_run: bool) -> int:
    """执行回填。返回 0 = 全成功，1 = 有失败。"""
    snapshot_dates = await _collect_snapshot_dates(start, end)
    total = len(snapshot_dates)
    if total == 0:
        print(f"[backfill] no daily_snapshots in [{start}, {end}]", file=sys.stderr)
        return 0

    if dry_run:
        print(
            f"[backfill] DRY-RUN: would ETL {total} snapshots in [{start}, {end}]"
        )
        return 0

    print(f"[backfill] ETL {total} snapshots in [{start}, {end}]")
    ok = 0
    fail = 0
    fail_dates: list[tuple[date, str]] = []
    start_ts = datetime.now()

    for i, d in enumerate(snapshot_dates, 1):
        try:
            # 每日单独 session（rebuild 内部有 commit，独立会话最简单）
            async with async_session_factory() as sub_session:
                sub_svc = ScoringWideService(
                    repo=ScoringWideRepository(sub_session),
                    snapshot_repo=SnapshotRepository(sub_session),
                    news_repo=NewsScoreRepository(sub_session),
                    gold_repo=GoldPriceRepository(sub_session),
                )
                out = await sub_svc.rebuild(d)
                if out is not None:
                    ok += 1
                # out is None = 当日 3 源都无数据（无 snapshot / 无 news / 无 gold），
                # 跳过不算失败
        except Exception as exc:  # noqa: BLE001
            fail += 1
            fail_dates.append((d, str(exc)[:80]))
            logger.warning("backfill failed: date=%s err=%s", d, exc)

        # 进度条（每 10% 一打）
        if i % max(1, total // 10) == 0 or i == total:
            pct = i * 100 // total
            elapsed = (datetime.now() - start_ts).total_seconds()
            print(f"[backfill] [{pct:3d}%] {i}/{total} ok={ok} fail={fail} ({elapsed:.1f}s)")

    elapsed = (datetime.now() - start_ts).total_seconds()
    print(
        f"[backfill] done in {elapsed:.1f}s: ok={ok} fail={fail} total={total}"
    )
    if fail_dates:
        print("[backfill] failed dates (前 10):")
        for d, err in fail_dates[:10]:
            print(f"  - {d}: {err}")
    return 0 if fail == 0 else 1


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="打分数据宽表历史回填（V0.92.0）",
    )
    p.add_argument(
        "--from",
        dest="from_date",
        type=date.fromisoformat,
        default=DEFAULT_FROM,
        help=f"起始日（含），默认 {DEFAULT_FROM.isoformat()}（V0.66.0 上线日）",
    )
    p.add_argument(
        "--to",
        dest="to_date",
        type=date.fromisoformat,
        default=date.today(),
        help="截止日（含），默认今天",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印计划，不实际写入",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    if args.from_date > args.to_date:
        print(f"[backfill] invalid range: {args.from_date} > {args.to_date}", file=sys.stderr)
        return 2
    if (args.to_date - args.from_date) > timedelta(days=365 * 5):
        print("[backfill] range too wide (>5y); split into chunks", file=sys.stderr)
        return 2
    return asyncio.run(_run_backfill(args.from_date, args.to_date, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
