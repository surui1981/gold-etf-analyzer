"""用户新闻收藏仓储：今日要闻「收藏 / 永久存储」CRUD（V0.103）

设计要点：
- 纯 CRUD 仓储，**不**做业务编排（业务在 ``services/user_news_favorite.py``）
- **不**走 SQLite ``on_conflict_do_update`` 路径（与 ``news_feed`` 区别）：
  收藏是用户主动行为，重复 POST 应当显式 409 Conflict 而不是默默覆盖
  （V0.97.0 user_saved 信号 + V0.84 失败态不伪装正常 设计纪律）
- 列表查询 6 维：days / site_name / tag (LIKE) / importance (>=) / limit / offset
- 排序：3 模式（最近收藏 / 重要度 / 发布时间）
- 状态查询：total + by_importance + by_site + by_tag (top) + by_month
- tag 维度：JSON 数组用 LIKE 模式搜索（``LIKE '%"美联储"%'`` 命中）
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, distinct, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_news_favorite import UserNewsFavorite


class DuplicateFavoriteError(Exception):
    """重复收藏（同一 external_id+source 已存在）→ 409 Conflict。"""


class UserNewsFavoriteRepository:
    """用户新闻收藏仓储（V0.103）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ────────────── 写 ──────────────

    async def add(self, payload: dict[str, Any]) -> UserNewsFavorite:
        """新增一条收藏。重复（external_id+source）抛 DuplicateFavoriteError。"""
        stmt = sqlite_insert(UserNewsFavorite).values(payload)
        try:
            result = await self._session.execute(stmt)
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            # UNIQUE 冲突 → 重复收藏
            raise DuplicateFavoriteError(
                f"news_external_id={payload.get('news_external_id')} "
                f"source={payload.get('news_source', 'readhub')} already archived"
            ) from exc
        # 取回插入行（SQLite last_insert_rowid）
        new_id = result.lastrowid
        return await self.get(new_id)  # type: ignore[return-value]

    async def update(
        self,
        fav_id: int,
        *,
        user_tags: str | None = None,
        user_note: str | None = None,
        importance: int | None = None,
    ) -> UserNewsFavorite | None:
        """局部更新：user_tags / user_note / importance 任选。

        任一字段为 None → 不更新。``updated_at`` 自动刷新。
        Returns:
            更新后的行；id 不存在则返回 None。
        """
        updates: dict[str, Any] = {"updated_at": func.now()}
        if user_tags is not None:
            updates["user_tags"] = user_tags
        if user_note is not None:
            updates["user_note"] = user_note
        if importance is not None:
            updates["importance"] = importance
        if len(updates) == 1:  # 只有 updated_at → 视为无更新
            return await self.get(fav_id)
        stmt = (
            UserNewsFavorite.__table__.update()
            .where(UserNewsFavorite.id == fav_id)
            .values(**updates)
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        if result.rowcount == 0:
            return None
        # Core UPDATE 不会刷新 identity map 里的 ORM 实例 → expire_all 让下次 get() 走 DB
        self._session.expire_all()
        return await self.get(fav_id)

    async def delete(self, fav_id: int) -> bool:
        """删除一条收藏。Returns: 是否实际删除。"""
        stmt = UserNewsFavorite.__table__.delete().where(
            UserNewsFavorite.id == fav_id
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return (result.rowcount or 0) > 0

    # ────────────── 读 ──────────────

    async def get(self, fav_id: int) -> UserNewsFavorite | None:
        """按主键取。"""
        stmt = select(UserNewsFavorite).where(UserNewsFavorite.id == fav_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def find_by_external(
        self, news_external_id: int, news_source: str = "readhub"
    ) -> UserNewsFavorite | None:
        """按 (external_id, source) 取（用于检查是否已收藏 / 幂等返回）。"""
        stmt = select(UserNewsFavorite).where(
            UserNewsFavorite.news_external_id == news_external_id,
            UserNewsFavorite.news_source == news_source,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_items(
        self,
        *,
        days: int | None = None,
        site_name: str | None = None,
        tag: str | None = None,
        importance_min: int | None = None,
        limit: int = 50,
        offset: int = 0,
        sort: str = "recent",
    ) -> list[UserNewsFavorite]:
        """按筛选条件取收藏（默认按 archived_at 倒序）。

        Args:
            days: 限定最近 N 天内的（基于 ``archived_at``），None=不限
            site_name: 按来源站精确匹配，None=不限
            tag: JSON 数组中精确包含此 tag（LIKE 模式：`LIKE '%"<tag>"%'`），None=不限
            importance_min: 重要度 >= N（1-3），None=不限
            limit: 返回上限（默认 50，保护 UI）
            offset: 跳过前 N 条（分页用，默认 0）
            sort: "recent"=按 archived_at 倒序（默认）；
                  "importance"=按 importance 倒序 + archived_at 倒序；
                  "publish"=按 publish_date 倒序
        """
        stmt = select(UserNewsFavorite)
        if days is not None and days > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            stmt = stmt.where(UserNewsFavorite.archived_at >= cutoff)
        if site_name is not None:
            stmt = stmt.where(UserNewsFavorite.site_name == site_name)
        if tag is not None:
            # JSON 数组中精确字符串匹配：LIKE '%"<tag>"%'
            escaped = tag.replace('"', '""')
            stmt = stmt.where(UserNewsFavorite.user_tags.like(f'%"{escaped}"%'))
        if importance_min is not None and importance_min > 0:
            stmt = stmt.where(UserNewsFavorite.importance >= importance_min)
        # 排序
        if sort == "importance":
            stmt = stmt.order_by(
                desc(UserNewsFavorite.importance),
                desc(UserNewsFavorite.archived_at),
            )
        elif sort == "publish":
            stmt = stmt.order_by(desc(UserNewsFavorite.publish_date))
        else:  # recent（默认）
            stmt = stmt.order_by(desc(UserNewsFavorite.archived_at))
        stmt = stmt.limit(max(1, min(limit, 200))).offset(max(0, offset))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_items(
        self,
        *,
        days: int | None = None,
        site_name: str | None = None,
        tag: str | None = None,
        importance_min: int | None = None,
    ) -> int:
        """与 ``list_items`` 相同筛选条件的总数（用于分页）。"""
        stmt = select(func.count(UserNewsFavorite.id))
        if days is not None and days > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            stmt = stmt.where(UserNewsFavorite.archived_at >= cutoff)
        if site_name is not None:
            stmt = stmt.where(UserNewsFavorite.site_name == site_name)
        if tag is not None:
            escaped = tag.replace('"', '""')
            stmt = stmt.where(UserNewsFavorite.user_tags.like(f'%"{escaped}"%'))
        if importance_min is not None and importance_min > 0:
            stmt = stmt.where(UserNewsFavorite.importance >= importance_min)
        return int((await self._session.execute(stmt)).scalar_one() or 0)

    async def list_sites(self) -> list[str]:
        """取收藏中出现过的全部来源站（去重 + 倒序按出现频次）。"""
        stmt = (
            select(UserNewsFavorite.site_name, func.count(UserNewsFavorite.id).label("cnt"))
            .group_by(UserNewsFavorite.site_name)
            .order_by(desc("cnt"))
        )
        rows = (await self._session.execute(stmt)).all()
        return [r[0] for r in rows]

    async def list_tags(self) -> list[str]:
        """取收藏中全部出现过的 tag 集合（解析 JSON 数组 + 去重 + 字母序）。

        实现：SELECT DISTINCT user_tags → Python 端解析 + 扁平化 + 去重。
        收藏数 100 以内性能可接受；万级再考虑 FTS5（V0.103+ backlog）。
        """
        stmt = select(distinct(UserNewsFavorite.user_tags)).where(
            UserNewsFavorite.user_tags != "[]"
        )
        rows = (await self._session.execute(stmt)).all()
        all_tags: set[str] = set()
        for (raw,) in rows:
            try:
                tags = json.loads(raw)
                if isinstance(tags, list):
                    for t in tags:
                        if isinstance(t, str) and t.strip():
                            all_tags.add(t.strip())
            except (json.JSONDecodeError, TypeError):
                continue
        return sorted(all_tags)

    async def get_status(self) -> dict[str, Any]:
        """取状态摘要：total + by_importance + by_site + by_tag (top 10) + by_month。"""
        # total
        total = int(
            (
                await self._session.execute(select(func.count(UserNewsFavorite.id)))
            ).scalar_one()
            or 0
        )
        # by_importance
        by_imp_stmt = (
            select(UserNewsFavorite.importance, func.count(UserNewsFavorite.id))
            .group_by(UserNewsFavorite.importance)
            .order_by(UserNewsFavorite.importance)
        )
        by_importance = {
            int(r[0]): int(r[1])
            for r in (await self._session.execute(by_imp_stmt)).all()
        }
        # by_site (top 10)
        by_site_stmt = (
            select(UserNewsFavorite.site_name, func.count(UserNewsFavorite.id).label("cnt"))
            .group_by(UserNewsFavorite.site_name)
            .order_by(desc("cnt"))
            .limit(10)
        )
        by_site = [
            {"site_name": r[0], "count": int(r[1])}
            for r in (await self._session.execute(by_site_stmt)).all()
        ]
        # by_tag (top 10)：与 list_tags 同样的解析 + 计数
        by_tag_stmt = select(UserNewsFavorite.user_tags).where(
            UserNewsFavorite.user_tags != "[]"
        )
        rows = (await self._session.execute(by_tag_stmt)).all()
        tag_counter: dict[str, int] = {}
        for (raw,) in rows:
            try:
                tags = json.loads(raw)
                if isinstance(tags, list):
                    for t in tags:
                        if isinstance(t, str) and t.strip():
                            tag_counter[t.strip()] = tag_counter.get(t.strip(), 0) + 1
            except (json.JSONDecodeError, TypeError):
                continue
        by_tag = sorted(
            ({"tag": k, "count": v} for k, v in tag_counter.items()),
            key=lambda x: -x["count"],
        )[:10]
        # by_month（按 archived_at YYYY-MM 分组，6 个月）
        by_month_stmt = (
            select(
                func.strftime("%Y-%m", UserNewsFavorite.archived_at).label("ym"),
                func.count(UserNewsFavorite.id),
            )
            .group_by("ym")
            .order_by(desc("ym"))
            .limit(6)
        )
        by_month = [
            {"month": r[0], "count": int(r[1])}
            for r in (await self._session.execute(by_month_stmt)).all()
        ]
        # 7d / 30d 新增
        now = datetime.now(timezone.utc)
        last_7d = int(
            (
                await self._session.execute(
                    select(func.count(UserNewsFavorite.id)).where(
                        UserNewsFavorite.archived_at >= now - timedelta(days=7)
                    )
                )
            ).scalar_one()
            or 0
        )
        last_30d = int(
            (
                await self._session.execute(
                    select(func.count(UserNewsFavorite.id)).where(
                        UserNewsFavorite.archived_at >= now - timedelta(days=30)
                    )
                )
            ).scalar_one()
            or 0
        )
        return {
            "total": total,
            "by_importance": by_importance,
            "by_site": by_site,
            "by_tag": by_tag,
            "by_month": by_month,
            "last_7d_count": last_7d,
            "last_30d_count": last_30d,
        }
