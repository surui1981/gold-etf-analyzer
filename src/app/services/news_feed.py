"""今日要闻业务服务：多源财经新闻编排（V0.102 / V0.104 单日模式 / V0.107 按日聚合 / V0.107.1 弃入「其他」/ V0.108.0 站点黑名单 / V0.114.0 多源 failover）

设计要点
--------
- 编排 fetcher + repository：``refresh()`` 走 抓 → 过滤 → upsert → 返回行数
- 编排层不做业务计算（不在此处做实体抽取 / 关键词 / 情感）
- V0.114.0：``fetch_readhub_feed`` 换成 ``fetch_news_feed``（4 源链式
  failover：wallstcn ★ → jin10 → eastmoney → readhub，首个足量即止）。
  本层**不**关心用了哪个源 —— 那是 fetcher 层的职责；但把 ``source`` 透传
  到响应里，因为「failover 是否真在工作」必须能被观测，否则首选源长期挂掉
  也没人知道
- **保留末次** UX：抓取失败时仍返回当前 DB 状态（status + items），让 UI
  显示「数据时效 chip」+ amber 提示，**不**在用户可见路径抛 500
  （参考 V0.84.0 状态条合并模式 + V0.77.1 失败态不再伪装正常）
- 手动 ``refresh()`` 强制走 fetcher cache miss（``use_cache=False``），
  scheduler 4h 唤醒可以吃 5min cache（V0.106 改 4h）
- V0.104 单日模式：``list_items(date=...)`` 时额外调
  ``repo.has_items_outside_day()`` 拿 has_older/has_newer，回填到 schema
- V0.107 按日聚合：``refresh()`` 末尾 → ``rebuild_daily(BJT today)`` 重建
  当日行；scheduler 跨午夜时加 rebuild_daily(BJT yesterday)。
  启动 lifespan 阶段 ``backfill_daily(30 days)`` 一次性回填历史
- V0.107.1：service ``refresh()`` 二次拦截 ``category='其他'`` 记录——
  defense-in-depth，fetcher ``_normalize`` 也已弃入（本层兜底）
- V0.108.0：同一道 gate 加拦 ``SITE_BLOCKLIST`` 站点（新浪科技 / maomu.com
  聚合噪声源），复用同一 tuple 过滤，无需额外分支
"""

from __future__ import annotations

from datetime import date as date_t
from datetime import datetime, time, timedelta, timezone
from typing import Any

from app.models.news_feed import NewsFeedDaily
from app.repositories.news_feed import NewsFeedRepository
from app.repositories.news_sources_fetcher import NewsSourceError, fetch_news_feed
from app.repositories.readhub_fetcher import SITE_BLOCKLIST
from app.schemas.news_feed import (
    NewsFeedDailyListOut,
    NewsFeedDailyOut,
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
        category=getattr(it, "category", None),  # V0.105：未分类时 None
    )


def _to_daily_out(row: NewsFeedDaily) -> NewsFeedDailyOut:
    """V0.107 ORM NewsFeedDaily → Pydantic NewsFeedDailyOut。"""
    return NewsFeedDailyOut(
        date=row.date,
        total_count=row.total_count,
        finance_count=row.finance_count,
        tech_count=row.tech_count,
        vc_count=row.vc_count,
        biz_count=row.biz_count,
        other_count=row.other_count,
        unique_sites_count=row.unique_sites_count,
        en_count=row.en_count,
        zh_count=row.zh_count,
        first_publish_at=row.first_publish_at,
        last_publish_at=row.last_publish_at,
        last_refresh_at=row.last_refresh_at,
    )


class NewsFeedService:
    """多源财经新闻业务编排（V0.114.0 起走 4 源 failover）。"""

    def __init__(self, repo: NewsFeedRepository) -> None:
        self._repo = repo

    # ────────────── 写：refresh 入口 ──────────────

    async def refresh(self, *, force: bool = False) -> dict[str, Any]:
        """走 4 源链式 failover 拉一次新闻落库。

        Args:
            force: True → 跳过 fetcher 5min cache，强制重抓

        Returns:
            ``{ok: bool, upserted: int, error: str | None, source: str | None}``：
            UI 据此显示成功提示或 amber chip；失败时 ``ok=False`` + ``error``
            文案（不抛异常——保留末次数据）。
            ``source`` 是本次生效的源 key，**failover 是否真在工作要能被观测**。
        """
        try:
            result = await fetch_news_feed(use_cache=not force)
        except NewsSourceError as exc:
            logger.warning("news feed refresh failed (all sources): %s", exc)
            return {"ok": False, "upserted": 0, "error": str(exc), "source": None}
        except Exception as exc:  # 兜底：任何意外都不让 500 冒到 UI
            logger.error("news feed refresh unexpected error: %s", exc)
            return {"ok": False, "upserted": 0, "error": f"unexpected: {exc}", "source": None}
        records = result.items

        # V0.107.1：service 二次拦截「其他」——defense-in-depth（fetcher 层
        # _normalize 已弃入；本层在 fetcher 改动漏改时仍能拦住）
        # V0.108.0：同一道 gate 加拦站点黑名单（fetcher 层已硬删，此处兜底）
        _ALLOWED_CATEGORIES = ("财经", "科技", "创投", "商业")
        before = len(records)
        records = tuple(
            r
            for r in records
            if r.get("category") in _ALLOWED_CATEGORIES and r.get("site_name") not in SITE_BLOCKLIST
        )
        dropped = before - len(records)
        if dropped:
            logger.info(
                "news feed refresh: dropped %d items at service gate "
                "(category=其他 or site blacklisted)",
                dropped,
            )

        if not records:
            # 源返回空 或 全部被弃入「其他」→ 当作软失败
            return {
                "ok": False,
                "upserted": 0,
                "error": "no valid items after category filter",
                "source": result.source,
            }

        try:
            n = await self._repo.upsert_bulk(list(records))
        except Exception as exc:
            logger.error("news feed upsert failed: %s", exc)
            return {
                "ok": False,
                "upserted": 0,
                "error": f"upsert: {exc}",
                "source": result.source,
            }

        logger.info("news feed refresh OK: upserted=%d from source=%s", n, result.source)
        return {"ok": True, "upserted": int(n), "error": None, "source": result.source}

    # ────────────── 读：list 入口 ──────────────

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
    ) -> NewsFeedListOut:
        """按筛选取列表（单次返回，UI 单次渲染）。

        Args:
            days: 窗口模式（UTC cutoff），与 date 互斥
            date: 单日模式（浏览器本地日期），与 days 互斥
            tz_offset_minutes: 时区偏移（带符号），仅 date 模式用
            site_name/language/category/limit: 透传仓储

        Returns:
            NewsFeedListOut；date 模式时多 3 字段：current_date/has_older/has_newer
        """
        items = await self._repo.list_items(
            days=days,
            date=date,
            tz_offset_minutes=tz_offset_minutes,
            site_name=site_name,
            language=language,
            category=category,
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

    async def list_categories(self) -> list[str]:
        """V0.105：DB 中已分类的类目（去重 + 频次降序）。"""
        return await self._repo.list_categories()

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

    # ────────────── V0.107 按日聚合 ──────────────

    async def rebuild_daily(self, target_date: date_t) -> NewsFeedDailyOut | None:
        """V0.107：重建 ``target_date``（BJT 日）的聚合行。

        透传仓储 ``upsert_daily`` —— UI 触发手动 refresh / scheduler 4h 定时
        / 启动 lifespan backfill 都会调此入口。
        """
        try:
            row = await self._repo.upsert_daily(target_date)
        except Exception as exc:
            logger.error("rebuild_daily(%s) failed: %s", target_date, exc)
            return None
        return _to_daily_out(row) if row is not None else None

    async def get_daily(self, target_date: date_t) -> NewsFeedDailyOut | None:
        """V0.107：取指定 BJT 日的聚合行（无则 None）。"""
        row = await self._repo.get_daily(target_date)
        return _to_daily_out(row) if row is not None else None

    async def list_daily(self, *, start: date_t, end: date_t) -> NewsFeedDailyListOut:
        """V0.107：取 [start, end] BJT 闭区间的聚合行（倒序）。"""
        rows = await self._repo.list_daily(start=start, end=end)
        items = [_to_daily_out(r) for r in rows]
        return NewsFeedDailyListOut(items=items, start=start, end=end, total=len(items))

    async def backfill_daily(self, *, start_date: date_t, end_date: date_t | None = None) -> int:
        """V0.107：启动 lifespan 阶段一次性回填历史 N 天。"""
        try:
            return await self._repo.backfill_daily(start_date=start_date, end_date=end_date)
        except Exception as exc:
            logger.error("backfill_daily failed: %s", exc)
            return 0
