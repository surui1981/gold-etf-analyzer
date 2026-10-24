"""V0.107.1 一次性 sweep：把 DB 里历史 `category='其他'` 行用新字典重新判

只更新 category='其他' 的行（4 类的行不重判）。
判后 rebuild_daily(BJT today) 让 daily 摘要同步。

用法：
  PYTHONPATH=src:. .venv/bin/python scripts/reclassify_v01071.py
"""

from __future__ import annotations

import asyncio
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "src")

from sqlalchemy import select, update

from app.models.news_feed import NewsFeedItem
from app.repositories.db import async_session_factory
from app.repositories.news_classifier import classify


async def main() -> None:
    BJT = timezone(timedelta(hours=8))
    today_bjt = datetime.now(BJT).date()

    print("=" * 70)
    print(f"V0.107.1 一次性重分类 sweep · {datetime.now(BJT).isoformat(timespec='seconds')}")
    print("=" * 70)

    async with async_session_factory() as session:
        # ── Step 1: 拉所有 category='其他' 行 ──
        print("\n[1] 拉所有 category='其他' 的行...")
        stmt = select(NewsFeedItem).where(NewsFeedItem.category == "其他")
        result = await session.execute(stmt)
        old_others = result.scalars().all()
        print(f"  找到 {len(old_others)} 条历史「其他」行")

        # ── Step 2: 用 V0.107.1 字典重判 ──
        print("\n[2] 用 V0.107.1 扩充字典重判...")
        new_dist = Counter()
        unchanged = 0
        to_update: list[tuple[int, str]] = []  # (id, new_category)
        for row in old_others:
            new_cat = classify(row.title or "", row.summary or "", row.site_name or "")
            if new_cat == "其他":
                unchanged += 1
            else:
                new_dist[new_cat] += 1
                to_update.append((row.id, new_cat))

        print("  → 重判后归类:")
        for cat in ("财经", "科技", "创投", "商业", "其他"):
            n = unchanged if cat == "其他" else new_dist.get(cat, 0)
            print(f"    {cat:6s} = {n:3d}")
        print(f"  → 仍判「其他」(无法归 4 类): {unchanged}")

        # ── Step 3: 批量 UPDATE ──
        print(f"\n[3] 批量 UPDATE {len(to_update)} 行...")
        if to_update:
            # 用 bulk_update_mappings 比手写 UPDATE 快
            from sqlalchemy.orm import Session  # noqa: F401

            for row_id, new_cat in to_update:
                await session.execute(
                    update(NewsFeedItem).where(NewsFeedItem.id == row_id).values(category=new_cat)
                )
            await session.commit()
            print(f"  ✅ 已提交 {len(to_update)} 行 UPDATE")
        else:
            print("  (无 UPDATE，跳过)")

        # ── Step 4: 重建当日 + 昨日 daily ──
        print(f"\n[4] rebuild_daily({today_bjt.isoformat()}) + 昨日 ...")
        from app.repositories.news_feed import NewsFeedRepository
        from app.services.news_feed import NewsFeedService

        # 上一轮 session 已 commit，重新取干净的 session 以便 daily 看到新数据
        repo = NewsFeedRepository(session)
        svc = NewsFeedService(repo)
        yesterday_bjt = today_bjt - timedelta(days=1)
        for d in (yesterday_bjt, today_bjt):
            rebuilt = await svc.rebuild_daily(d)
            if rebuilt is not None:
                print(
                    f"  ✅ {d} → total={rebuilt.total_count} "
                    f"财经={rebuilt.finance_count} 科技={rebuilt.tech_count} "
                    f"创投={rebuilt.vc_count} 商业={rebuilt.biz_count} "
                    f"其他={rebuilt.other_count}"
                )
            else:
                print("  (该日无数据)")

    print("\n" + "=" * 70)
    print("✅ V0.107.1 重分类 sweep 完成")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
