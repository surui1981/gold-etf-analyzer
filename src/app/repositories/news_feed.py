"""新闻流仓储：readhub 财经新闻 CRUD（V0.102 / V0.104 单日模式扩展）

设计要点：
- 纯 CRUD 仓储，**不**做业务编排（业务在 ``services/news_feed.py``）
- 唯一入口 ``upsert_bulk`` 走 SQLite ``on_conflict_do_update``（参考
  ``central_bank.py`` 同模式），二次抓取 dedup 不重不漏
- 列表查询 5 维：date / days / site_name / language / limit（任选组合）
  - V0.104 新增 ``date`` + ``tz_offset_minutes``：单日模式（与 ``days`` 互斥）
  - ``date`` 是浏览器本地日期（YYYY-MM-DD），由 service 层负责转 UTC 边界
- 单日模式配套：``has_items_outside_day`` 2 个 LIMIT-1 存在性查询
  - 返回 ``(has_older, has_newer)``，供前端禁用「前一天/后一天」按钮
- 状态查询：last_refresh（最新 fetched_at）+ total + 24h 新增数
"""

from __future__ import annotations

from datetime import date as date_t, datetime, time, timedelta, timezone

from sqlalchemy import and_, desc, distinct, func, literal, select
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
        date: date_t | None = None,
        tz_offset_minutes: int = 0,
        site_name: str | None = None,
        language: str | None = None,
        limit: int = 50,
    ) -> list[NewsFeedItem]:
        """按筛选条件取新闻（默认按 publish_date 倒序）。

        Args:
            days: 限定最近 N 天内的（基于 ``publish_date``，UTC cutoff），None=不限
            date: 单日模式：取 ``publish_date`` 落在 ``[date 00:00 本地, date+1 00:00 本地)`` 的新闻。
                与 ``days`` 互斥；date 优先。date 走 ``tz_offset_minutes`` 转换。
            tz_offset_minutes: 浏览器时区偏移（**带符号**，东八区 = +480）。仅 date 模式用。
            site_name: 按来源站精确匹配，None=不限
            language: 按语种精确匹配，None=不限
            limit: 返回上限（默认 50，保护 UI）

        Note:
            V0.104 新增 date 模式（与 days 二选一）；date=None 时走 days 模式，**0 字段破坏**。
        """
        stmt = select(NewsFeedItem)
        if date is not None:
            # 单日模式：date 0:00 本地 → date+1 0:00 本地（半开区间）
            tz = timezone(timedelta(minutes=tz_offset_minutes))
            day_start = datetime.combine(date, time.min, tzinfo=tz)
            day_end = datetime.combine(date + timedelta(days=1), time.min, tzinfo=tz)
            stmt = stmt.where(
                and_(
                    NewsFeedItem.publish_date >= day_start,
                    NewsFeedItem.publish_date < day_end,
                )
            )
        elif days is not None and days > 0:
            # 窗口模式：现有逻辑
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            stmt = stmt.where(NewsFeedItem.publish_date >= cutoff)
        if site_name is not None:
            stmt = stmt.where(NewsFeedItem.site_name == site_name)
        if language is not None:
            stmt = stmt.where(NewsFeedItem.language == language)
        stmt = stmt.order_by(desc(NewsFeedItem.publish_date)).limit(max(1, min(limit, 200)))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def has_items_outside_day(
        self, *, day_start: datetime, day_end: datetime
    ) -> tuple[bool, bool]:
        """检测给定的「单日窗口」之外是否还有新闻（V0.104 单日模式翻页用）。

        Args:
            day_start: 窗口起始（含），与 ``list_items(date=...)`` 的下界一致
            day_end: 窗口结束（不含），与 ``list_items(date=...)`` 的上界一致

        Returns:
            ``(has_older, has_newer)``：
            - ``has_older`` = True 表示 day_start 之前还有更早的新闻（可点「前一天」）
            - ``has_newer`` = True 表示 day_end 之后还有更新的新闻（可点「后一天」）

        实现：2 个 LIMIT 1 存在性查询（不走 COUNT，比 ``EXISTS`` 子查询更直白）。
        """
        older_stmt = (
            select(literal(1))
            .where(NewsFeedItem.publish_date < day_start)
            .limit(1)
        )
        newer_stmt = (
            select(literal(1))
            .where(NewsFeedItem.publish_date >= day_end)
            .limit(1)
        )
        has_older = (await self._session.execute(older_stmt)).first() is not None
        has_newer = (await self._session.execute(newer_stmt)).first() is not None
        return has_older, has_newer

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
