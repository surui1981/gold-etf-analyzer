"""报告存档仓储：HTML 报告元数据 CRUD（V0.111.0）

设计要点：
- 纯 CRUD 仓储，**不**做业务编排（业务在 ``services/reports.py``；
  磁盘写入 / 校验 / unlink 全在 service 层，仓储层完全不知道文件存在）
- **每个方法首行** ``user_id = resolve_user_id(user_id)`` —— 报告是用户私有
  资产（区别于 ``user_news_favorites`` 的共享上下文语义），多用户模式下
  列表 / 详情 / 修改 / 删除全部按 owner 过滤
- 跨用户访问 ``get()`` 返回 ``None`` 而非 403 —— 沿用 ``ai_chat`` 的理由：
  「避免泄露存在性」（403 等于告诉攻击者「这个 id 存在但不是你的」）
- 列表查询：q（标题 / 摘要 / 原始文件名模糊）/ category / tag(LIKE) / limit / offset
- ``tags`` 用 LIKE 精确匹配数组元素：``LIKE '%"<tag>"%'``（与
  ``user_news_favorites`` 的 JSON 数组搜索同模式，千级数据够用）
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reports import Report
from app.utils.user_scope import resolve_user_id


class ReportRepository:
    """报告存档仓储（V0.111.0）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ────────────── 写 ──────────────

    async def add(self, payload: dict[str, Any], *, user_id: int | None = None) -> Report:
        """新增一条报告记录（磁盘文件已由 service 层写好）。

        用 ORM ``add()`` + ``refresh()`` 而不是 Core ``sqlite_insert``：
        Core insert 不回填 ORM 实例，而 ``created_at`` / ``updated_at`` 是
        ``server_default=func.now()`` —— 只有 refresh 才能把这两个值读回来。
        """
        payload = {**payload, "user_id": resolve_user_id(user_id)}
        row = Report(**payload)
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def update(
        self,
        report_id: int,
        *,
        user_id: int | None = None,
        title: str | None = None,
        report_date: Any = None,
        category: str | None = None,
        tags: str | None = None,
        summary: str | None = None,
    ) -> Report | None:
        """局部更新登记表字段。任一字段为 None → 不更新。

        Returns:
            更新后的行；不存在或不属于该用户则返回 None。
        """
        uid = resolve_user_id(user_id)
        updates: dict[str, Any] = {"updated_at": func.now()}
        if title is not None:
            updates["title"] = title
        if report_date is not None:
            updates["report_date"] = report_date
        if category is not None:
            updates["category"] = category
        if tags is not None:
            updates["tags"] = tags
        if summary is not None:
            updates["summary"] = summary
        if len(updates) == 1:  # 只有 updated_at → 视为无更新
            return await self.get(report_id, user_id=uid)
        stmt = Report.__table__.update().where(Report.id == report_id, Report.user_id == uid)
        result = await self._session.execute(stmt.values(**updates))
        await self._session.commit()
        if result.rowcount == 0:
            return None
        # Core UPDATE 不会刷新 identity map 里的 ORM 实例 → expire_all 让下次 get() 走 DB
        self._session.expire_all()
        return await self.get(report_id, user_id=uid)

    async def delete(self, report_id: int, *, user_id: int | None = None) -> bool:
        """删除一条报告记录。Returns: 是否实际删除（调用方负责 unlink 磁盘文件）。"""
        uid = resolve_user_id(user_id)
        stmt = Report.__table__.delete().where(Report.id == report_id, Report.user_id == uid)
        result = await self._session.execute(stmt)
        await self._session.commit()
        return (result.rowcount or 0) > 0

    # ────────────── 读 ──────────────

    async def get(self, report_id: int, *, user_id: int | None = None) -> Report | None:
        """按主键取（带 owner 过滤）。不存在或跨用户均返回 None。"""
        uid = resolve_user_id(user_id)
        stmt = select(Report).where(Report.id == report_id, Report.user_id == uid)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_stored_name(self, stored_name: str) -> Report | None:
        """按磁盘文件名取（仅供 service 内部校验，不对外暴露端点）。"""
        stmt = select(Report).where(Report.stored_name == stored_name)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_items(
        self,
        *,
        user_id: int | None = None,
        q: str | None = None,
        category: str | None = None,
        tag: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Report]:
        """按筛选条件取报告（默认 created_at 倒序）。"""
        uid = resolve_user_id(user_id)
        stmt = select(Report).where(Report.user_id == uid)
        if q:
            like = f"%{_escape_like(q)}%"
            stmt = stmt.where(
                or_(
                    Report.title.like(like, escape="\\"),
                    Report.summary.like(like, escape="\\"),
                    Report.original_name.like(like, escape="\\"),
                )
            )
        if category:
            stmt = stmt.where(Report.category == category)
        if tag:
            # JSON 数组中精确字符串匹配：LIKE '%"<tag>"%'
            stmt = stmt.where(Report.tags.like(f'%"{_escape_like(tag)}"%', escape="\\"))
        stmt = stmt.order_by(desc(Report.created_at), desc(Report.id))
        stmt = stmt.limit(max(1, min(limit, 200))).offset(max(0, offset))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_items(
        self,
        *,
        user_id: int | None = None,
        q: str | None = None,
        category: str | None = None,
        tag: str | None = None,
    ) -> int:
        """与 ``list_items`` 相同筛选条件的总数（用于分页）。

        ⚠ 谓词与 ``list_items`` **故意重复**而非抽公共函数 —— 与
        ``user_news_favorites`` 仓储同风格，抽出来会让两处都要改，
        漏改一处就是「列表和总数对不上」的分页 bug。
        """
        uid = resolve_user_id(user_id)
        stmt = select(func.count(Report.id)).where(Report.user_id == uid)
        if q:
            like = f"%{_escape_like(q)}%"
            stmt = stmt.where(
                or_(
                    Report.title.like(like, escape="\\"),
                    Report.summary.like(like, escape="\\"),
                    Report.original_name.like(like, escape="\\"),
                )
            )
        if category:
            stmt = stmt.where(Report.category == category)
        if tag:
            stmt = stmt.where(Report.tags.like(f'%"{_escape_like(tag)}"%', escape="\\"))
        return int((await self._session.execute(stmt)).scalar_one() or 0)

    async def list_categories(self, *, user_id: int | None = None) -> list[str]:
        """取出现过的全部分类（去重 + 按频次倒序）。"""
        uid = resolve_user_id(user_id)
        stmt = (
            select(Report.category, func.count(Report.id).label("cnt"))
            .where(Report.user_id == uid)
            .group_by(Report.category)
            .order_by(desc("cnt"))
        )
        rows = (await self._session.execute(stmt)).all()
        return [r[0] for r in rows]

    async def list_tags(self, *, user_id: int | None = None) -> list[str]:
        """取全部出现过的 tag（解析 JSON 数组 + 去重 + 字母序）。"""
        uid = resolve_user_id(user_id)
        stmt = select(Report.tags).where(Report.user_id == uid, Report.tags != "[]")
        rows = (await self._session.execute(stmt)).all()
        all_tags: set[str] = set()
        for (raw,) in rows:
            try:
                parsed = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(parsed, list):
                for t in parsed:
                    if isinstance(t, str) and t.strip():
                        all_tags.add(t.strip())
        return sorted(all_tags)

    async def get_stats(self, *, user_id: int | None = None) -> dict[str, Any]:
        """侧栏统计：total / last_30d_count / total_bytes / by_category。"""
        from datetime import datetime, timedelta, timezone

        uid = resolve_user_id(user_id)
        now = datetime.now(timezone.utc)
        row = (
            await self._session.execute(
                select(
                    func.count(Report.id),
                    func.coalesce(func.sum(Report.size_bytes), 0),
                ).where(Report.user_id == uid)
            )
        ).one()
        last_30d = int(
            (
                await self._session.execute(
                    select(func.count(Report.id)).where(
                        Report.user_id == uid, Report.created_at >= now - timedelta(days=30)
                    )
                )
            ).scalar_one()
            or 0
        )
        by_cat_stmt = (
            select(Report.category, func.count(Report.id).label("cnt"))
            .where(Report.user_id == uid)
            .group_by(Report.category)
            .order_by(desc("cnt"))
        )
        by_category = [
            {"category": r[0], "count": int(r[1])}
            for r in (await self._session.execute(by_cat_stmt)).all()
        ]
        return {
            "total": int(row[0] or 0),
            "last_30d_count": last_30d,
            "total_bytes": int(row[1] or 0),
            "by_category": by_category,
        }


def _escape_like(s: str) -> str:
    """转义 LIKE 通配符，否则用户搜 ``100%`` 会匹配到任意行。

    ⚠ 转义字符是 ``\\``，所以每个 ``.like()`` **必须**同时传 ``escape="\\"``。
    少传这个参数比不转义更糟：SQLite 默认不把反斜杠当转义符，于是 ``100\\%``
    变成「字面反斜杠 + 通配符」，搜 ``100%`` 反而一条都搜不到（而不是全命中）。
    """
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
