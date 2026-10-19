"""新闻流仓储：readhub 财经新闻 CRUD（V0.102 / V0.104 单日模式 / V0.105 类目 / V0.107 按日聚合）

设计要点：
- 纯 CRUD 仓储，**不**做业务编排（业务在 ``services/news_feed.py``）
- 唯一入口 ``upsert_bulk`` 走 SQLite ``on_conflict_do_update``（参考
  ``central_bank.py`` 同模式），二次抓取 dedup 不重不漏
- 列表查询 6 维：date / days / site_name / language / category / limit（任选组合）
  - V0.104 新增 ``date`` + ``tz_offset_minutes``：单日模式（与 ``days`` 互斥）
  - ``date`` 是浏览器本地日期（YYYY-MM-DD），由 service 层负责转 UTC 边界
  - V0.105 新增 ``category``：与上述 5 维正交叠加（不互斥）
- 单日模式配套：``has_items_outside_day`` 2 个 LIMIT-1 存在性查询
  - 返回 ``(has_older, has_newer)``，供前端禁用「前一天/后一天」按钮
- 状态查询：last_refresh（最新 fetched_at）+ total + 24h 新增数
- V0.105 类目回填：``backfill_categories()`` 启动时一次性处理 NULL 行
- V0.107 按日聚合：``upsert_daily(target_date)`` 重建指定 BJT 日行；
  ``backfill_daily(start, end)`` 启动 lifespan 一次性回填
  - BJT 边界计算：``target_date`` 是 BJT 日期，转 UTC 区间
    ``[target_date 00:00 BJT, target_date+1 00:00 BJT)``，
    用 ``datetime.combine(target_date, time.min, tzinfo=BJT)`` 构造边界
  - 当日为空 → **不**创建空行（保留「DB 反映实际数据」原则）
"""

from __future__ import annotations

from datetime import date as date_t, datetime, time, timedelta, timezone

from sqlalchemy import and_, case, desc, distinct, func, literal, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news_feed import NewsFeedDaily, NewsFeedItem
from app.repositories.news_classifier import classify
from app.utils.logger import get_logger

logger = get_logger(__name__)


class NewsFeedRepository:
    """readhub 财经新闻仓储。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ────────────── 写 ──────────────

    async def upsert_bulk(self, records: list[dict]) -> int:
        """批量 upsert；按 ``external_id`` 唯一约束做 dedup。

        ``records`` 元素是 dict（key 对应 NewsFeedItem 字段），由 fetcher 给出
        已 normalize 的 payload；不在这里做业务校验。

        V0.105：``set_`` 里加 ``category=stmt.excluded.category``，让二次抓取
        时能覆盖（否则历史行永远 NULL，backfill 之外就再无机会分类）。

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
                "category": stmt.excluded.category,  # V0.105：upsert 时更新类目
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
        category: str | None = None,  # V0.105
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
            category: V0.105 按类目精确匹配（财经/科技/创投/商业/其他），None=不限
            limit: 返回上限（默认 50，保护 UI）

        Note:
            V0.104 新增 date 模式（与 days 二选一）；date=None 时走 days 模式，**0 字段破坏**。
            V0.105 新增 category；与 date/days/site_name/language **正交叠加**，不互斥。
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
        if category is not None:  # V0.105
            stmt = stmt.where(NewsFeedItem.category == category)
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

    async def list_categories(self) -> list[str]:
        """V0.105：取 DB 中已分类的类目（distinct + 频次降序）。

        只返回已分类的行（``category IS NOT NULL``），过滤掉「未分类」legacy
        行（启动后首次 backfill 即清空；过渡期可能仍有少量 NULL）。
        频次降序让热门类目排前面，UI 下拉默认显示也合理。
        """
        stmt = (
            select(NewsFeedItem.category, func.count(NewsFeedItem.id).label("cnt"))
            .where(NewsFeedItem.category.isnot(None))
            .group_by(NewsFeedItem.category)
            .order_by(desc("cnt"))
        )
        rows = (await self._session.execute(stmt)).all()
        return [r[0] for r in rows if r[0]]

    async def backfill_categories(self, *, batch_size: int = 500) -> int:
        """V0.105：启动时一次性把历史 NULL 行打上类目标签。

        - 只处理 ``category IS NULL`` 的行（已分类的不动，幂等）
        - 逐批处理：``SELECT WHERE category IS NULL LIMIT batch_size`` → 分类 → ``UPDATE``
        - 单批内全量更新（不检查「已变更」），保证「一遍刷完」
        - 返回本次处理的行数

        性能：~64378 行 / 500 batch ≈ 130 批 × 50ms ≈ 6-10s
        """
        total = 0
        while True:
            # 取出 1 批 NULL 行（只用需要的字段，避免大对象）
            stmt = (
                select(
                    NewsFeedItem.id,
                    NewsFeedItem.title,
                    NewsFeedItem.summary,
                    NewsFeedItem.site_name,
                )
                .where(NewsFeedItem.category.is_(None))
                .limit(batch_size)
            )
            rows = (await self._session.execute(stmt)).all()
            if not rows:
                break

            # 逐行分类
            for row in rows:
                cat = classify(row.title, row.summary, row.site_name)
                await self._session.execute(
                    update(NewsFeedItem)
                    .where(NewsFeedItem.id == row.id)
                    .values(category=cat)
                )
            await self._session.commit()
            total += len(rows)
            logger.info("backfill_categories: processed %d rows (total=%d)", len(rows), total)

            if len(rows) < batch_size:
                break  # 不到 1 批说明刷完了
        if total > 0:
            logger.info("backfill_categories DONE: %d rows backfilled", total)
        return total

    # ────────────── V0.107 按日聚合 ──────────────

    @staticmethod
    def _bjt_day_bounds(target_date: date_t) -> tuple[datetime, datetime]:
        """BJT 日期 → (start, end) UTC-aware datetime 边界（半开区间）。

        例：target_date=2026-10-19 (BJT) → [2026-10-19 00:00 BJT, 2026-10-20 00:00 BJT)
        即 [2026-10-18 16:00 UTC, 2026-10-19 16:00 UTC)

        ⚠ 返回的 datetime **带 BJT tzinfo**（不是 UTC），SQLAlchemy 会在
        WHERE 子句里自动转 UTC 比较（DateTime(timezone=True) 列）。
        """
        bjt_tz = timezone(timedelta(hours=8))
        day_start = datetime.combine(target_date, time.min, tzinfo=bjt_tz)
        day_end = datetime.combine(target_date + timedelta(days=1), time.min, tzinfo=bjt_tz)
        return day_start, day_end

    async def upsert_daily(self, target_date: date_t) -> NewsFeedDaily | None:
        """V0.107：重建 ``target_date``（BJT 日）的聚合行（idempotent）。

        1. 从 ``news_feed_items`` 算 BJT 当日的 5 类目 / 站点 / 中英文 / 首末时间
        2. ``INSERT ON CONFLICT(date) DO UPDATE SET ...``

        Args:
            target_date: BJT 日期（YYYY-MM-DD）

        Returns:
            ``NewsFeedDaily`` 行（新建或更新）；当日为空时返回 ``None``
            （**不**创建空行 —— 保留「DB 反映实际数据」原则）
        """
        day_start, day_end = self._bjt_day_bounds(target_date)

        # 1. 单行聚合：5 类目计数 + 独立站点 + 中英文 + 首末时间
        agg_stmt = (
            select(
                func.count(NewsFeedItem.id).label("total"),
                func.sum(case((NewsFeedItem.category == "财经", 1), else_=0)).label(
                    "finance"
                ),
                func.sum(case((NewsFeedItem.category == "科技", 1), else_=0)).label(
                    "tech"
                ),
                func.sum(case((NewsFeedItem.category == "创投", 1), else_=0)).label("vc"),
                func.sum(case((NewsFeedItem.category == "商业", 1), else_=0)).label("biz"),
                func.sum(case((NewsFeedItem.category == "其他", 1), else_=0)).label(
                    "other"
                ),
                func.count(distinct(NewsFeedItem.site_name)).label("unique_sites"),
                func.sum(case((NewsFeedItem.language == "en", 1), else_=0)).label("en"),
                func.sum(case((NewsFeedItem.language.like("zh%"), 1), else_=0)).label(
                    "zh"
                ),
                func.min(NewsFeedItem.publish_date).label("first_pub"),
                func.max(NewsFeedItem.publish_date).label("last_pub"),
            )
            .where(
                and_(
                    NewsFeedItem.publish_date >= day_start,
                    NewsFeedItem.publish_date < day_end,
                )
            )
        )
        row = (await self._session.execute(agg_stmt)).one()
        total = int(row.total or 0)

        # 2. 当日为空 → 不创建空行
        if total == 0:
            return None

        # 3. Upsert：date PK 冲突时全字段更新（除 date 主键自身）
        now_utc = datetime.now(timezone.utc)
        payload = {
            "date": target_date,
            "total_count": total,
            "finance_count": int(row.finance or 0),
            "tech_count": int(row.tech or 0),
            "vc_count": int(row.vc or 0),
            "biz_count": int(row.biz or 0),
            "other_count": int(row.other or 0),
            "unique_sites_count": int(row.unique_sites or 0),
            "en_count": int(row.en or 0),
            "zh_count": int(row.zh or 0),
            "first_publish_at": row.first_pub,
            "last_publish_at": row.last_pub,
            "last_refresh_at": now_utc,
        }
        stmt = sqlite_insert(NewsFeedDaily).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=["date"],
            set_={k: stmt.excluded[k] for k in payload if k != "date"},
        )
        await self._session.execute(stmt)
        await self._session.commit()
        return await self.get_daily(target_date)

    async def get_daily(self, target_date: date_t) -> NewsFeedDaily | None:
        """V0.107：取指定 BJT 日的聚合行（无则 None）。"""
        stmt = select(NewsFeedDaily).where(NewsFeedDaily.date == target_date)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_daily(
        self, *, start: date_t, end: date_t
    ) -> list[NewsFeedDaily]:
        """V0.107：取 BJT 日期区间 [start, end] 的聚合行（闭区间，倒序）。

        闭区间（含 start 和 end）+ 倒序（最近日期在前），与 ``list_items`` 的
        默认排序保持一致。
        """
        stmt = (
            select(NewsFeedDaily)
            .where(and_(NewsFeedDaily.date >= start, NewsFeedDaily.date <= end))
            .order_by(desc(NewsFeedDaily.date))
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def backfill_daily(
        self, *, start_date: date_t, end_date: date_t | None = None
    ) -> int:
        """V0.107：逐日重建 [start_date, end_date] 闭区间（仿 backfill_categories）。

        Args:
            start_date: 起始 BJT 日（含）
            end_date: 结束 BJT 日（含），None 时 = start_date（单日）

        Returns:
            本次回填创建 / 更新的天数（不含「当日为空」跳过的天数）
        """
        if end_date is None:
            end_date = start_date
        if end_date < start_date:
            return 0
        total = 0
        current = start_date
        one_day = timedelta(days=1)
        while current <= end_date:
            try:
                result = await self.upsert_daily(current)
            except Exception as exc:  # 防止单日 SQL 异常中断整段
                logger.error("backfill_daily failed at %s: %s", current, exc)
                current += one_day
                continue
            if result is not None:
                total += 1
            current += one_day
        if total > 0:
            logger.info(
                "backfill_daily DONE: %d days backfilled (range %s..%s)",
                total,
                start_date,
                end_date,
            )
        return total
