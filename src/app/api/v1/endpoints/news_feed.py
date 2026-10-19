"""今日要闻 REST 端点（V0.102 / V0.104 单日模式 / V0.107 按日聚合）"""

from datetime import date as date_t

from fastapi import APIRouter, Depends, Query

from app.dependencies import get_news_feed_service
from app.middleware.admin_auth import require_admin_session
from app.schemas.news_feed import (
    NewsFeedDailyListOut,
    NewsFeedDailyOut,
    NewsFeedListOut,
    NewsFeedRefreshOut,
    NewsFeedStatusOut,
)
from app.services.news_feed import NewsFeedService

router = APIRouter(prefix="/news-feed", tags=["news-feed"])


@router.get(
    "/items",
    response_model=NewsFeedListOut,
    summary="今日要闻列表（按 publish_date 倒序）",
)
async def list_items(
    days: int | None = Query(
        None,
        ge=1,
        le=90,
        description="限定最近 N 天内的（按 publish_date）；None=不限。V0.104：与 date 互斥，date 优先。",
    ),
    date: date_t | None = Query(
        None,
        description="V0.104 单日模式：取 publish_date 落在 [date 00:00 本地, date+1 00:00 本地) 的新闻。YYYY-MM-DD 格式。",
    ),
    tz_offset_minutes: int = Query(
        0,
        ge=-14 * 60,
        le=14 * 60,
        description="V0.104 浏览器时区偏移（**带符号**，东八区 = +480）。仅 date 模式生效。",
    ),
    site_name: str | None = Query(
        None,
        max_length=64,
        description="按来源站精确筛选（华尔街见闻 / 36Kr / 财联社 / 格隆汇）",
    ),
    language: str | None = Query(
        None,
        max_length=8,
        description="按语种精确筛选（zh-cn / en）",
    ),
    category: str | None = Query(
        None,
        max_length=16,
        description="V0.105 按分类精确筛选（财经/科技/创投/商业/其他）；与 date/days/site_name/language 正交叠加",
    ),
    limit: int = Query(50, ge=1, le=200, description="返回上限（默认 50，保护 UI）"),
    service: NewsFeedService = Depends(get_news_feed_service),
) -> NewsFeedListOut:
    """返回按 publish_date 倒序的 readhub 新闻列表。

    - 窗口模式（``days=N``）：取最近 N 天内的新闻
    - 单日模式（``date=YYYY-MM-DD``）：取那一天的新闻；响应里多 3 字段
      （``current_date`` / ``has_older`` / ``has_newer``）供前端翻页按钮
    - 两个模式互斥，date 优先
    - V0.105 ``category`` 与上述模式**正交叠加**，独立过滤
    """
    return await service.list_items(
        days=days,
        date=date,
        tz_offset_minutes=tz_offset_minutes,
        site_name=site_name,
        language=language,
        category=category,
        limit=limit,
    )


@router.get(
    "/sites",
    response_model=list[str],
    summary="DB 内全部来源站（按频次降序）",
)
async def list_sites(
    service: NewsFeedService = Depends(get_news_feed_service),
) -> list[str]:
    """工具栏来源筛选下拉数据源。"""
    return await service.list_sites()


@router.get(
    "/languages",
    response_model=list[str],
    summary="DB 内全部语种（去重 + 字典序）",
)
async def list_languages(
    service: NewsFeedService = Depends(get_news_feed_service),
) -> list[str]:
    """语种筛选下拉数据源（按字母序）。"""
    return await service.list_languages()


@router.get(
    "/categories",
    response_model=list[str],
    summary="V0.105 DB 内已分类的类目（去重 + 频次降序）",
)
async def list_categories(
    service: NewsFeedService = Depends(get_news_feed_service),
) -> list[str]:
    """类目筛选下拉数据源（按频次降序）。仅返回已分类（``category IS NOT NULL``）行。

    - 启动后 ``_backfill_news_categories()`` 一次性补齐历史 NULL 行
    - 新条目由 ``readhub_fetcher._normalize()`` 入库即分类
    - 启动过渡期可能返回空 list（等待 backfill 完成）；前端下拉此时仅显示「全部」+ 固定 5 类兜底
    """
    return await service.list_categories()


@router.get(
    "/status",
    response_model=NewsFeedStatusOut,
    summary="数据时效摘要：last_refresh + total + 24h 新增",
)
async def get_status(
    service: NewsFeedService = Depends(get_news_feed_service),
) -> NewsFeedStatusOut:
    """顶栏 4-chip：上次刷新 / 总数 / 24h 新增。"""
    return await service.get_status()


@router.post(
    "/refresh",
    response_model=NewsFeedRefreshOut,
    summary="立即触发一次抓取（admin 守卫）",
    dependencies=[Depends(require_admin_session)],
)
async def refresh(
    service: NewsFeedService = Depends(get_news_feed_service),
) -> NewsFeedRefreshOut:
    """强制走 fetcher cache miss 重抓（不受 5min TTL 限制）。

    单用户模式（``AUTH_ENABLED=false``）下 ``require_admin_session`` 自动豁免。
    """
    result = await service.refresh(force=True)
    return NewsFeedRefreshOut(
        ok=result["ok"],
        upserted=result["upserted"],
        error=result["error"],
    )


# ──────────────── V0.107 按日聚合 ────────────────


@router.get(
    "/daily",
    response_model=NewsFeedDailyOut | None,
    summary="V0.107 指定 BJT 日的聚合行（无则 null）",
)
async def get_daily(
    date: date_t = Query(
        ..., description="BJT 日期（YYYY-MM-DD）；目标聚合日"
    ),
    service: NewsFeedService = Depends(get_news_feed_service),
) -> NewsFeedDailyOut | None:
    """取单日聚合（UI /headlines 顶 chip + /home 底 chip 用）。

    无该日数据时返回 ``null``（**不**创建空行），前端按「暂无」处理。
    """
    return await service.get_daily(date)


@router.get(
    "/daily/list",
    response_model=NewsFeedDailyListOut,
    summary="V0.107 [start, end] 闭区间的聚合行（倒序）",
)
async def list_daily(
    start: date_t = Query(..., description="BJT 起始日（闭）"),
    end: date_t = Query(..., description="BJT 结束日（闭）"),
    service: NewsFeedService = Depends(get_news_feed_service),
) -> NewsFeedDailyListOut:
    """取闭区间聚合（最多 90 天，仿 ``/items`` 的 ``days`` 上限）。

    倒序返回（最近 → 远期），与 ``/items`` 排序保持一致。
    """
    # 区间合法性校验：start ≤ end 且跨度 ≤ 90 天
    if start > end:
        from fastapi import HTTPException  # 局部 import 避免模块级拖入

        raise HTTPException(status_code=400, detail="start must be <= end")
    if (end - start).days > 90:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400, detail="range too large (max 90 days)"
        )
    return await service.list_daily(start=start, end=end)
