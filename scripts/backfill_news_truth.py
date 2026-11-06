#!/usr/bin/env python
"""消息面真实性回填脚本（V0.121.1 · P0-3）

把「伪造的中性 50 分」从历史数据里清掉，并顺带把宽表的 ``price_direction``
补齐（P0-2）。

背景
----
V0.100 起，消息面未打分时 ``trend.news.score`` 是 ``None``（正确），
但落库时被兜底成 ``50.0``（错误）——「没打分」被写成「中性 50」。
污染链（实测）::

    trend.news.score = None
       └─ services/snapshot.py → news_index = 50.0            ← 源头伪造
            └─ daily_snapshots NOT NULL                        ← 源头锁死
                 └─ 宽表 ETL 继承 snap.news_index               ⇒ 32 行假 50
                      └─ direction_of(50.0) = NEUTRAL（不是 None！）
                           └─ judge_hit(NEUTRAL, chg) → 按 ±0.3% 横盘判定
                                ⇒ 伪造出 14 个 hit_t1 / 12 个 hit_t5

生产库实测（2026-11-06，61 条快照 / 61 条宽表行）：

===================================  ==========  ==========  ==========
快照 ``news_index == 50``            条数        判定        动作
===================================  ==========  ==========  ==========
当天**无** news_scores 记录          32          伪造        → NULL
当天**有** news_scores 记录          25          见下        → 当日聚合值
===================================  ==========  ==========  ==========

那 25 行「当天有记录」的，进一步核对了**打分时刻 vs 快照捕获时刻**：
**25 行全部是「打分日期 >= 快照日期」**（即快照捕获时用户还没打分）⇒
它们的 50 也是兜底，不是真实分；其中 17 行的当日聚合值 ≠ 50
（如 2026-09-09 聚合=20，快照存 50）⇒ 数值对不上，佐证是伪造。

⚠ **判据是「当天有没有 news_scores 记录」，不是「值是不是 50」**：
宽表里 ``news_slot_count >= 1`` 的 28 行中有 **8 行 news_index 恰好 = 50**，
那 8 行是**用户真实打了 50 分** ⇒ 一律不动。

宽表怎么修
----------
**重跑 ETL**（``ScoringWideService.rebuild``）而不是写一段一次性 SQL：

- 修完后的 ETL 对「当天无 news_scores」的行写 ``news_index = NULL``，
  ``hit_t*`` 留 NULL（没有方向 ⇒ 没有判定）⇒ 恰好是回填要的结果；
- 同时把 ``price_direction`` 补上（P0-2：唯一可信口径是
  ``gold_price_daily.change_pct`` 的符号）—— 这是加列后的历史回填；
- 走的是**真实代码路径** ⇒ 不会与未来的 ETL 漂移。

幂等
----
快照侧：处理完的行不再是 50（或聚合值就是 50 ⇒ 值不变）⇒ 重跑无变更。
宽表侧：同样的输入 ⇒ 同样的行 ⇒ 重跑无变更。
脚本会打印「改了多少行 / 跳过多少行」，重跑时应显示 0 变更。

用法
----
::

    # 先看要改什么（不写库）
    python -m scripts.backfill_news_truth --dry-run

    # 真跑
    python -m scripts.backfill_news_truth

    # 限定区间
    python -m scripts.backfill_news_truth --from 2026-09-01 --to 2026-10-31
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date

from sqlalchemy import select

from app.models.scoring_wide import ScoringDailyWide
from app.models.snapshot import DailySnapshot
from app.repositories.db import async_session_factory
from app.repositories.news import NewsScoreRepository
from app.repositories.review import GoldPriceRepository
from app.repositories.scoring_wide import ScoringWideRepository
from app.repositories.snapshot import SnapshotRepository
from app.services.news import aggregate_slots
from app.services.scoring_wide import ScoringWideService
from app.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_FROM = date(2000, 1, 1)


async def _plan_snapshot_updates(
    start: date, end: date, user_id: int
) -> list[tuple[int, date, float | None, float | None]]:
    """规划快照表的 news_index 修正。

    Returns:
        ``[(snapshot_id, snapshot_date, old_value, new_value), ...]``
        （只含**需要变更**的行）。
    """
    out: list[tuple[int, date, float | None, float | None]] = []
    async with async_session_factory() as session:
        stmt = select(DailySnapshot).where(
            DailySnapshot.snapshot_date >= start,
            DailySnapshot.snapshot_date <= end,
        )
        snaps = list((await session.execute(stmt)).scalars().all())

        news_repo = NewsScoreRepository(session)
        for snap in snaps:
            # ⚠ 只处理 ``news_index == 50`` 的行 —— 它们是「伪造兜底」的嫌疑对象。
            #   非 50 的行是用户真实评分（哪怕与当日聚合值不同，那也是「捕获时刻的立场」，
            #   属于有意保留的语义），**不动**。
            if snap.news_index is None or abs(float(snap.news_index) - 50.0) > 1e-9:
                continue
            records = await news_repo.list_by_date(snap.snapshot_date, user_id=user_id)
            if records:
                effective, _formula, _weighted = aggregate_slots(records)
                new_value: float | None = effective
            else:
                # 当天**没有任何**打分记录 ⇒ 50 分没有任何依据 ⇒ 未知（NULL）
                new_value = None
            if new_value is None or abs(new_value - float(snap.news_index)) > 1e-9:
                out.append((snap.id, snap.snapshot_date, float(snap.news_index), new_value))
    return out


async def _apply_snapshot_updates(
    updates: list[tuple[int, date, float | None, float | None]], dry_run: bool
) -> int:
    """执行快照表更新，返回实际改动行数。"""
    if dry_run or not updates:
        return 0
    async with async_session_factory() as session:
        for snap_id, _d, _old, new_value in updates:
            snap = await session.get(DailySnapshot, snap_id)
            if snap is None:
                continue
            snap.news_index = new_value
        await session.commit()
    return len(updates)


async def _rebuild_wide(start: date, end: date, user_id: int, dry_run: bool) -> tuple[int, int]:
    """重跑宽表 ETL（修 news_index / hit_* + 补 price_direction）。

    Returns:
        ``(尝试天数, 成功天数)``。
    """
    async with async_session_factory() as session:
        stmt = select(ScoringDailyWide.date).where(
            ScoringDailyWide.date >= start,
            ScoringDailyWide.date <= end,
            ScoringDailyWide.user_id == user_id,
        )
        dates = sorted({row[0] for row in (await session.execute(stmt)).all()})

    ok = 0
    for d in dates:
        if dry_run:
            ok += 1
            continue
        async with async_session_factory() as session:
            service = ScoringWideService(
                repo=ScoringWideRepository(session),
                snapshot_repo=SnapshotRepository(session),
                news_repo=NewsScoreRepository(session),
                gold_repo=GoldPriceRepository(session),
            )
            result = await service.rebuild(d, user_id=user_id)
        if result is not None:
            ok += 1
        else:
            logger.warning("backfill: rebuild failed for date=%s", d)
    return len(dates), ok


async def _snapshot_summary(user_id: int) -> dict[str, int]:
    """当前快照表的消息面分布（回填后自查）。"""
    async with async_session_factory() as session:
        stmt = select(DailySnapshot.news_index)
        vals = [row[0] for row in (await session.execute(stmt)).all()]
    return {
        "total": len(vals),
        "null": sum(1 for v in vals if v is None),
        "eq50": sum(1 for v in vals if v is not None and abs(float(v) - 50.0) < 1e-9),
    }


async def _run(start: date, end: date, user_id: int, dry_run: bool) -> int:
    print(f"[backfill] 区间 [{start}, {end}]  user_id={user_id}  dry_run={dry_run}")

    before = await _snapshot_summary(user_id)
    print(
        f"[backfill] 快照表现状：共 {before['total']} 行 / news_index=NULL {before['null']} 行"
        f" / news_index=50 {before['eq50']} 行"
    )

    updates = await _plan_snapshot_updates(start, end, user_id)
    n_null = sum(1 for u in updates if u[3] is None)
    n_value = len(updates) - n_null
    print(
        f"[backfill] 快照表待修正 {len(updates)} 行：置 NULL {n_null} 行 / 写当日聚合值 {n_value} 行"
    )
    for sid, d, old, new in updates[:20]:
        print(f"           - id={sid} {d} : {old} → {new}")
    if len(updates) > 20:
        print(f"           ... +{len(updates) - 20} more")

    changed = await _apply_snapshot_updates(updates, dry_run)
    print(f"[backfill] 快照表实际改动 {changed} 行")

    total_days, ok_days = await _rebuild_wide(start, end, user_id, dry_run)
    print(f"[backfill] 宽表 ETL 重跑：{ok_days}/{total_days} 天成功")

    after = await _snapshot_summary(user_id)
    print(
        f"[backfill] 快照表现状：共 {after['total']} 行 / news_index=NULL {after['null']} 行"
        f" / news_index=50 {after['eq50']} 行"
    )
    if not dry_run:
        # 幂等自查：再规划一次，应当没有待修正项
        again = await _plan_snapshot_updates(start, end, user_id)
        print(f"[backfill] 幂等自查：二次规划待修正 {len(again)} 行（应为 0）")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="from_date", default=DEFAULT_FROM.isoformat())
    parser.add_argument("--to", dest="to_date", default=date.today().isoformat())
    parser.add_argument("--user-id", dest="user_id", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true", help="只报告，不写库")
    args = parser.parse_args()

    start = date.fromisoformat(args.from_date)
    end = date.fromisoformat(args.to_date)
    return asyncio.run(_run(start, end, args.user_id, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
