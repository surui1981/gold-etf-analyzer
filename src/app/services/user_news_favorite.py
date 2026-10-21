"""用户新闻收藏业务服务：今日要闻「收藏 / 永久存储」编排（V0.103）

设计要点
--------
- 编排 repository：add / update / delete / list / status
- **不**自动抓取（与 news_feed 区别）—— 收藏是用户主动行为
- 当 ``news_feed_items`` 中能找到 ``news_external_id`` 对应行时，POST 时**优先
  从源表回填快照字段**（标题 / 摘要 / URL / 来源站 / 发布时间等），
  保证与 readhub 当前数据一致；源表无对应行时（外部 URL 收藏），走客户端直接
  传值（``UserNewsFavoriteCreateIn.title / url / site_name / publish_date``）
- ``user_tags`` 写入前用 ``normalize_tags`` 做去重 + 字母序排序，与
  ``scoring_daily_wide.news_basis_tags`` 一致（``dump_basis`` 模式）
- 失败语义：dedup → 409；找不到 id → 404；其它 → 500（仓储层异常）
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.models.user_news_favorite import UserNewsFavorite
from app.repositories.news_feed import NewsFeedRepository
from app.repositories.user_news_favorite import (
    DuplicateFavoriteError,
    UserNewsFavoriteRepository,
)
from app.schemas.user_news_favorite import (
    UserNewsFavoriteCreateIn,
    UserNewsFavoriteItemOut,
    UserNewsFavoriteListOut,
    UserNewsFavoriteStatusOut,
    UserNewsFavoriteUpdateIn,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _normalize_tags(tags: list[str]) -> list[str]:
    """tag 列表标准化：去空 + 去重 + 字母序排序（与 scoring_daily_wide 一致）。"""
    cleaned = {t.strip() for t in tags if isinstance(t, str) and t.strip()}
    return sorted(cleaned)


def _dump_tags(tags: list[str]) -> str:
    """标准化后的 tag 列表 → JSON 字符串（与 scoring_daily_wide 一致）。"""
    return json.dumps(_normalize_tags(tags), ensure_ascii=False)


def _to_out(fav: UserNewsFavorite) -> UserNewsFavoriteItemOut:
    """ORM → Pydantic Out（参考 news_feed._to_out 模式）。"""
    try:
        tags = json.loads(fav.user_tags) if fav.user_tags else []
        if not isinstance(tags, list):
            tags = []
    except (json.JSONDecodeError, TypeError):
        tags = []
    return UserNewsFavoriteItemOut(
        id=fav.id,
        news_external_id=fav.news_external_id,
        news_source=fav.news_source,
        title=fav.title,
        summary=fav.summary or "",
        url=fav.url,
        mobile_url=fav.mobile_url,
        site_name=fav.site_name,
        language=fav.language,
        author_name=fav.author_name,
        publish_date=fav.publish_date,
        user_tags=[t for t in tags if isinstance(t, str)],
        user_note=fav.user_note or "",
        importance=fav.importance,
        archived_at=fav.archived_at,
        updated_at=fav.updated_at,
    )


class UserNewsFavoriteService:
    """用户新闻收藏业务编排（V0.103）。"""

    def __init__(
        self,
        fav_repo: UserNewsFavoriteRepository,
        feed_repo: NewsFeedRepository | None = None,
    ) -> None:
        self._fav_repo = fav_repo
        self._feed_repo = feed_repo  # 可选：用于 POST 时从源表回填快照

    # ────────────── 写 ──────────────

    async def add(self, payload: UserNewsFavoriteCreateIn) -> UserNewsFavoriteItemOut:
        """新增收藏。

        流程：
        1. 若 ``feed_repo`` 提供且 ``news_feed_items`` 中能找到对应行，
           优先用源表当前字段填充快照（保证与 readhub 一致）
        2. 否则用 payload 直接传值（外部 URL 收藏场景）
        3. tags → 标准化 → JSON 字符串
        4. 插入；重复 → 抛 DuplicateFavoriteError → 409
        """
        snapshot: dict[str, Any] = {
            # ⚠ V0.114.0：列是 String(32)（金十 id 超出 SQLite int64）。
            # Pydantic 把入参收成 int，这里显式转回字符串再落库。
            "news_external_id": str(payload.news_external_id),
            "news_source": payload.news_source,
        }
        # 尝试从源表回填快照
        if self._feed_repo is not None:
            source_item = await self._feed_repo.find_by_external(
                payload.news_external_id, payload.news_source
            )
            if source_item is not None:
                snapshot.update(
                    {
                        "title": source_item.title,
                        "summary": source_item.summary or "",
                        "url": source_item.url,
                        "mobile_url": source_item.mobile_url,
                        "site_name": source_item.site_name,
                        "language": source_item.language,
                        "author_name": source_item.author_name,
                        "publish_date": source_item.publish_date,
                    }
                )

        # ⚠ V0.114.0：``url`` 从必填清单里**移出**。金十 / 东方财富的快讯接口根本不
        #   提供链接（实测 30/30 条无 url 字段），原先的必填校验会让这类条目
        #   **永远收藏不了**（422）。NULL = 「来源没给链接」，UI 侧渲染成不可点
        #   纯文本（V0.77.1 不给假 affordance），与 news_feed 侧口径一致。
        #
        # ⚠ 但 url 仍要能被 **payload 兜底**：外部 URL 直传场景（V0.103）里
        #   url 不在源表快照中，只能来自 payload。曾经它靠「在 missing 清单里」
        #   被顺带拷进来 —— 移出清单后那次拷贝就没了，外部直传的收藏会**静默丢
        #   掉链接**（不报错，收藏成功但点不开）。所以这里单独兜一次。
        if not snapshot.get("url") and payload.url is not None:
            snapshot["url"] = payload.url

        # 校验必填快照（外部 URL 收藏场景）
        missing = [
            k
            for k in ("title", "site_name", "publish_date")
            if not snapshot.get(k)
        ]
        if missing:
            # 用 payload 兜底
            for k in missing:
                v = getattr(payload, k, None)
                if v is not None:
                    snapshot[k] = v
        # 再次校验（外部 URL 收藏必填字段未传 → 422）
        missing = [
            k
            for k in ("title", "site_name", "publish_date")
            if not snapshot.get(k)
        ]
        if missing:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=422,
                detail=(
                    f"missing required snapshot fields: {missing}; "
                    "either provide news_external_id that exists in news_feed_items, "
                    "or supply title/site_name/publish_date directly"
                ),
            )
        # url 缺失（源条目本就无链接）→ 显式置 None，而不是让 dict 里缺这个 key
        # （SQLAlchemy 会按列默认值处理，但显式更清晰，也避免「未传」与「无链接」混淆）
        snapshot["url"] = snapshot.get("url") or None

        # tags 标准化 → JSON
        snapshot["user_tags"] = _dump_tags(payload.user_tags)
        snapshot["user_note"] = payload.user_note or ""
        snapshot["importance"] = payload.importance

        fav = await self._fav_repo.add(snapshot)
        return _to_out(fav)

    async def update(
        self, fav_id: int, payload: UserNewsFavoriteUpdateIn
    ) -> UserNewsFavoriteItemOut | None:
        """更新收藏的 user_tags / user_note / importance。"""
        kwargs: dict[str, Any] = {}
        if payload.user_tags is not None:
            kwargs["user_tags"] = _dump_tags(payload.user_tags)
        if payload.user_note is not None:
            kwargs["user_note"] = payload.user_note
        if payload.importance is not None:
            kwargs["importance"] = payload.importance
        if not kwargs:
            # 空 patch → 直接返回当前行
            current = await self._fav_repo.get(fav_id)
            return _to_out(current) if current else None
        fav = await self._fav_repo.update(fav_id, **kwargs)
        return _to_out(fav) if fav else None

    async def delete(self, fav_id: int) -> bool:
        return await self._fav_repo.delete(fav_id)

    # ────────────── 读 ──────────────

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
    ) -> UserNewsFavoriteListOut:
        items = await self._fav_repo.list_items(
            days=days,
            site_name=site_name,
            tag=tag,
            importance_min=importance_min,
            limit=limit,
            offset=offset,
            sort=sort,
        )
        total = await self._fav_repo.count_items(
            days=days,
            site_name=site_name,
            tag=tag,
            importance_min=importance_min,
        )
        return UserNewsFavoriteListOut(
            items=[_to_out(it) for it in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get(self, fav_id: int) -> UserNewsFavoriteItemOut | None:
        fav = await self._fav_repo.get(fav_id)
        return _to_out(fav) if fav else None

    async def find_by_external(
        self, news_external_id: int, news_source: str = "readhub"
    ) -> UserNewsFavoriteItemOut | None:
        """幂等检查：判断某条新闻是否已收藏（UI 按钮态切换用）。"""
        fav = await self._fav_repo.find_by_external(news_external_id, news_source)
        return _to_out(fav) if fav else None

    async def list_sites(self) -> list[str]:
        return await self._fav_repo.list_sites()

    async def list_tags(self) -> list[str]:
        return await self._fav_repo.list_tags()

    async def get_status(self) -> UserNewsFavoriteStatusOut:
        status = await self._fav_repo.get_status()
        return UserNewsFavoriteStatusOut(
            total=int(status["total"]),
            by_importance={int(k): int(v) for k, v in status["by_importance"].items()},
            by_site=list(status["by_site"]),
            by_tag=list(status["by_tag"]),
            by_month=list(status["by_month"]),
            last_7d_count=int(status["last_7d_count"]),
            last_30d_count=int(status["last_30d_count"]),
        )
