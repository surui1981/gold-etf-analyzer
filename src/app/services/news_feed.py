"""今日要闻业务服务：readhub 财经新闻编排（V0.102 / V0.104 单日模式扩展）

设计要点
--------
- 编排 fetcher + repository：``refresh()`` 走 抓 → 过滤 → upsert → 返回行数
- 编排层不做业务计算（不在此处做实体抽取 / 关键词 / 情感）
- **保留末次** UX：抓取失败时仍返回当前 DB 状态（status + items），让 UI
  显示「数据时效 chip」+ amber 提示，**不**在用户可见路径抛 500
  （参考 V0.84.0 状态条合并模式 + V0.77.1 失败态不再伪装正常）
- 手动 ``refresh()`` 强制走 fetcher cache miss（``use_cache=False``），
  scheduler 6h 唤醒可以吃 5min cache
- V0.104 单日模式：``list_items(date=...)`` 时额外调
  ``repo.has_items_outside_day()`` 拿 has_older/has_newer，回填到 schema
"""

from __future__ import annotations

from datetime import date as date_t, datetime, time, timedelta, timezone
from typing import Any

from app.repositories.news_feed import NewsFeedRepository
from app.repositories.readhub_fetcher import ReadhubFetchError, fetch_readhub_feed
from app.schemas.news_feed import (
    NewsFeedItemOut,
    NewsFeedListOut,
    NewsFeedStatusOut,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _to_out(it) -> NewsFeedItemOut:
    """ORM → Pydantic Out（参考 central_bank.py:_to_out 模式）。"""
    return NewsFeedItemOut(
        external_id=it.external_id,
        title=it.title,
        summary=it.summary or "",
        url=it.url,
        mobile_url=it.mobile_url,
        site_name=it.site_name,
        language=it.language,
        author_name=it.author_name,
        publish_date=it.publish_date,
        fetched_at=it.fetched_at,
        source=it.source,
    )


class NewsFeedService:
    """readhub 财经新闻业务编排。"""

    def __init__(self, repo: NewsFeedRepository) -> None:
        self._repo = repo

    # ────────────── 写：refresh 入口 ──────────────

    async def refresh(self, *, force: bool = False) -> dict[str, Any]:
        """拉一次 readhub 落库。

        Args:
            force: True → 跳过 fetcher 5min cache，强制重抓

        Returns:
            ``{ok: bool, upserted: int, error: str | None}``：UI 据此显示
            成功提示或 amber chip；失败时 ``ok=False`` + ``error`` 文案
            （不抛异常——保留末次数据）
        """
        try:
            records = await fetch_readhub_feed(use_cache=not force)
        except ReadhubFetchError as exc:
            logger.warning("news feed refresh failed: %s", exc)
            return {"ok": False, "upserted": 0, "error": str(exc)}
        except Exception as exc:  # 兜底：任何意外都不让 500 冒到 UI
            logger.error("news feed refresh unexpected error: %s", exc)
            return {"ok": False, "upserted": 0, "error": f"unexpected: {exc}"}

        if not records:
            # readhub 返回空（极罕见，可能是 API 维护）→ 当作软失败
            return {
                "ok": False,
                "upserted": 0,
                "error": "readhub returned empty payload",
            }

        try:
            n = await self._repo.upsert_bulk(list(records))
        except Exception as exc:
            logger.error("news feed upsert failed: %s", exc)
            return {"ok": False, "upserted": 0, "error": f"upsert: {exc}"}

        logger.info("news feed refresh OK: upserted=%d", n)
        return {"ok": True, "upserted": int(n), "error": None}

    # ────────────── 读：list 入口 ──────────────

    async def list_items(
        self,
        *,
        days: int | None = None,
        date: date_t | None = None,
        tz_offset_minutes: int = 0,
        site_name: str | None = None,
        language: str | None = None,
        limit: int = 50,
    ) -> NewsFeedListOut:
        """按筛选取列表（单次返回，UI 单次渲染）。

        Args:
            days: 窗口模式（UTC cutoff），与 date 互斥
            date: 单日模式（浏览器本地日期），与 days 互斥
            tz_offset_minutes: 时区偏移（带符号），仅 date 模式用
            site_name/language/limit: 透传仓储

        Returns:
            NewsFeedListOut；date 模式时多 3 字段：current_date/has_older/has_newer
        """
        items = await self._repo.list_items(
            days=days,
            date=date,
            tz_offset_minutes=tz_offset_minutes,
            site_name=site_name,
            language=language,
            limit=limit,
        )

        # 单日模式：查窗口外是否有新闻（has_older/has_newer）
        current_date_str: str | None = None
        has_older = False
        has_newer = False
        if date is not None:
            current_date_str = date.isoformat()
            tz = timezone(timedelta(minutes=tz_offset_minutes))
            day_start = datetime.combine(date, time.min, tzinfo=tz)
            day_end = datetime.combine(date + timedelta(days=1), time.min, tzinfo=tz)
            has_older, has_newer = await self._repo.has_items_outside_day(
                day_start=day_start, day_end=day_end
            )

        return NewsFeedListOut(
            items=[_to_out(it) for it in items],
            total=len(items),
            current_date=current_date_str,
            has_older=has_older,
            has_newer=has_newer,
        )

    async def list_sites(self) -> list[str]:
        return await self._repo.list_sites()

    async def list_languages(self) -> list[str]:
        return await self._repo.list_languages()

    async def get_status(self) -> NewsFeedStatusOut:
        status = await self._repo.get_status()
        last_refresh = status["last_refresh_at"]
        return NewsFeedStatusOut(
            last_refresh_at=(
                last_refresh.isoformat() if isinstance(last_refresh, datetime) else None
            ),
            total_items=int(status["total_items"]),
            last_24h_count=int(status["last_24h_count"]),
        )
