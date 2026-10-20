"""V0.107.1 二次诊断：剩余「其他」为什么仍判「其他」？

拉所有遗留「其他」行 → 跑 classify() → 看哪类关键词未命中。
"""
from __future__ import annotations

import sys
from collections import Counter

sys.path.insert(0, "src")

import asyncio  # noqa: E402

from sqlalchemy import select  # noqa: E402

from app.models.news_feed import NewsFeedItem  # noqa: E402
from app.repositories.db import async_session_factory  # noqa: E402
from app.repositories.news_classifier import classify  # noqa: E402


async def main() -> None:
    async with async_session_factory() as session:
        stmt = select(NewsFeedItem).where(NewsFeedItem.category == "其他")
        result = await session.execute(stmt)
        rows = result.scalars().all()
        print(f"当前「其他」仍剩 {len(rows)} 条\n")
        # 抽样 8 条
        samples = rows[:8]
        for r in samples:
            cls = classify(r.title or "", r.summary or "", r.site_name or "")
            print(f"  [{r.site_name[:12]:12s}]")
            print(f"    title   : {r.title[:70]}")
            print(f"    summary : {(r.summary or '')[:70]!r}")
            print(f"    classify→ {cls}")
            print(f"    pub_date: {r.publish_date}")
            print()


if __name__ == "__main__":
    asyncio.run(main())
