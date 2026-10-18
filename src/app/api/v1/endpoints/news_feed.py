"""今日要闻 REST 端点（V0.102）"""

from fastapi import APIRouter, Depends, Query

from app.dependencies import get_news_feed_service
from app.middleware.admin_auth import require_admin_session
from app.schemas.news_feed import (
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
        description="限定最近 N 天内的（按 publish_date）；None=不限",
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
    limit: int = Query(50, ge=1, le=200, description="返回上限（默认 50，保护 UI）"),
    service: NewsFeedService = Depends(get_news_feed_service),
) -> NewsFeedListOut:
    """返回按 publish_date 倒序的 readhub 新闻列表。

    UI 默认只显示今天 1 天的；``days=7`` 适合「7 日回顾」视图。
    """
    return await service.list_items(
        days=days,
        site_name=site_name,
        language=language,
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
