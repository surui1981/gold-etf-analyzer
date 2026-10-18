"""新闻流仓储：readhub 财经新闻 CRUD（V0.102）

设计要点：
- 纯 CRUD 仓储，**不**做业务编排（业务在 ``services/news_feed.py``）
- 唯一入口 ``upsert_bulk`` 走 SQLite ``on_conflict_do_update``（参考
  ``central_bank.py`` 同模式），二次抓取 dedup 不重不漏
- 列表查询 4 维：days / site_name / language / limit（任选组合）
- 状态查询：last_refresh（最新 fetched_at）+ total + 24h 新增数
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, distinct, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news_feed import NewsFeedItem


class NewsFeedRepository:
    """readhub 财经新闻仓储。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ────────────── 写 ──────────────

    async def upsert_bulk(self, records: list[dict]) -> int:
        """批量 upsert；按 ``external_id`` 唯一约束做 dedup。

        ``records`` 元素是 dict（key 对应 NewsFeedItem 字段），由 fetcher 给出
        已 normalize 的 payload；不在这里做业务校验。

        Returns:
            受影响行数（SQLite 包含 INSERT 新行 + UPDATE 冲突行）
        """
        if not records:
            return 0
        # 过滤掉 None external_id（readhub API 偶发，理论上不会）
        payload = [r for r in records if r.get("external_id") is not None]
        if not payload:
            return 0
        stmt = sqlite_insert(NewsFeedItem).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=["external_id"],
            set_={
                "title": stmt.excluded.title,
                "summary": stmt.excluded.summary,
                "url": stmt.excluded.url,
                "mobile_url": stmt.excluded.mobile_url,
                "site_name": stmt.excluded.site_name,
                "language": stmt.excluded.language,
                "author_name": stmt.excluded.author_name,
                "publish_date": stmt.excluded.publish_date,
                "fetched_at": stmt.excluded.fetched_at,
                "source": stmt.excluded.source,
            },
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return result.rowcount or 0

    # ────────────── 读 ──────────────

    async def list_items(
        self,
        *,
        days: int | None = None,
        site_name: str | None = None,
        language: str | None = None,
        limit: int = 50,
    ) -> list[NewsFeedItem]:
        """按筛选条件取新闻（默认按 publish_date 倒序）。

        Args:
            days: 限定最近 N 天内的（基于 ``publish_date``），None=不限
            site_name: 按来源站精确匹配，None=不限
            language: 按语种精确匹配，None=不限
            limit: 返回上限（默认 50，保护 UI）
        """
        stmt = select(NewsFeedItem)
        if days is not None and days > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            stmt = stmt.where(NewsFeedItem.publish_date >= cutoff)
        if site_name is not None:
            stmt = stmt.where(NewsFeedItem.site_name == site_name)
        if language is not None:
            stmt = stmt.where(NewsFeedItem.language == language)
        stmt = stmt.order_by(desc(NewsFeedItem.publish_date)).limit(max(1, min(limit, 200)))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_sites(self) -> list[str]:
        """取 DB 中出现过的全部来源站（去重 + 倒序按出现频次）。"""
        # 频次降序 → 同源新闻多的排前面
        stmt = (
            select(NewsFeedItem.site_name, func.count(NewsFeedItem.id).label("cnt"))
            .group_by(NewsFeedItem.site_name)
            .order_by(desc("cnt"))
        )
        rows = (await self._session.execute(stmt)).all()
        return [r[0] for r in rows]

    async def find_by_external(
        self, external_id: int, source: str = "readhub"
    ) -> NewsFeedItem | None:
        """按 ``(external_id, source)`` 取单条（V0.103 收藏回填快照用）。

        Returns:
            匹配的行；不存在则 None。
        """
        stmt = select(NewsFeedItem).where(
            NewsFeedItem.external_id == external_id,
            NewsFeedItem.source == source,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_status(self) -> dict:
        """取状态摘要：last_refresh + total + 24h 新增数。"""
        now = datetime.now(timezone.utc)
        last_refresh = (
            await self._session.execute(select(func.max(NewsFeedItem.fetched_at)))
        ).scalar_one_or_none()
        total = (
            await self._session.execute(select(func.count(NewsFeedItem.id)))
        ).scalar_one()
        last_24h_cutoff = now - timedelta(hours=24)
        last_24h = (
            await self._session.execute(
                select(func.count(NewsFeedItem.id)).where(
                    NewsFeedItem.fetched_at >= last_24h_cutoff
                )
            )
        ).scalar_one()
        return {
            "last_refresh_at": last_refresh,
            "total_items": int(total or 0),
            "last_24h_count": int(last_24h or 0),
        }

    async def list_languages(self) -> list[str]:
        """取 DB 中出现过的全部语种（去重）。"""
        stmt = select(distinct(NewsFeedItem.language)).where(NewsFeedItem.language.isnot(None))
        rows = (await self._session.execute(stmt)).all()
        return sorted([r[0] for r in rows if r[0]])
