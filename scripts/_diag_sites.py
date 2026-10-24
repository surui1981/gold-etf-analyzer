"""V0.108.0 准备：统计生产 DB 里出现过的站点 + 类目分布

目的：确认白名单候选站点；不写 DB（只读）。
"""

from __future__ import annotations

import sys

sys.path.insert(0, "src")
import asyncio

from sqlalchemy import func, select

from app.models.news_feed import NewsFeedItem
from app.repositories.db import async_session_factory


async def main() -> None:
    async with async_session_factory() as session:
        stmt = (
            select(NewsFeedItem.site_name, func.count(NewsFeedItem.id).label("n"))
            .group_by(NewsFeedItem.site_name)
            .order_by(func.count(NewsFeedItem.id).desc())
        )
        result = await session.execute(stmt)
        rows = result.all()
        print(f"\n=== 全量 {len(rows)} 个站名（按出现次数倒序）===\n")
        for site, n in rows:
            print(f"  {n:5d}  {site!r}")


if __name__ == "__main__":
    asyncio.run(main())
