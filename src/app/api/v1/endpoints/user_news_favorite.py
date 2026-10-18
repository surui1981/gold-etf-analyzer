"""用户新闻收藏 REST 端点（V0.103）

7 个端点：
- GET    /api/v1/favorites/items          列表（多维筛选 + 排序 + 分页）
- GET    /api/v1/favorites/items/{id}     单条
- GET    /api/v1/favorites/sites         来源站 distinct
- GET    /api/v1/favorites/tags          tag distinct
- GET    /api/v1/favorites/stats         6 维统计
- GET    /api/v1/favorites/exists/{external_id}  幂等检查（UI 按钮态）
- POST   /api/v1/favorites/items         新增（require_user；重复 → 409）
- PATCH  /api/v1/favorites/items/{id}    更新 tags/note/importance（require_user）
- DELETE /api/v1/favorites/items/{id}    取消收藏（require_user）

鉴权语义：
- ``Depends(require_user)`` 在 AUTH_ENABLED=false 时自动回退 LEGACY_USER（V0.97.0
  hotfix 防 401），单用户模式零额外配置即可使用
- 多用户模式按 user.id 隔离（虽然不挂 user_id 字段，但中间件仍要校验登录态）
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_user_news_favorite_service, require_user
from app.repositories.user_news_favorite import DuplicateFavoriteError
from app.schemas.user_news_favorite import (
    UserNewsFavoriteCreateIn,
    UserNewsFavoriteItemOut,
    UserNewsFavoriteListOut,
    UserNewsFavoriteStatusOut,
    UserNewsFavoriteUpdateIn,
)
from app.services.user_news_favorite import UserNewsFavoriteService

router = APIRouter(prefix="/favorites", tags=["favorites"])


# ────────────── 读：列表 / 单条 / 统计 ──────────────


@router.get(
    "/items",
    response_model=UserNewsFavoriteListOut,
    summary="收藏列表（多维筛选 + 排序 + 分页）",
)
async def list_items(
    days: int | None = Query(
        None,
        ge=1,
        le=3650,
        description="限定最近 N 天收藏的（按 archived_at）；None=不限",
    ),
    site_name: str | None = Query(
        None, max_length=64, description="按来源站精确筛选"
    ),
    tag: str | None = Query(
        None,
        max_length=64,
        description="JSON 数组中精确包含此 tag（LIKE 模式）",
    ),
    importance_min: int | None = Query(
        None,
        ge=1,
        le=3,
        description="重要度下限（1-3），None=不限",
    ),
    sort: str = Query(
        "recent",
        pattern="^(recent|importance|publish)$",
        description="排序：recent=按 archived_at 倒序 / importance=按重要度倒序 / publish=按 publish_date 倒序",
    ),
    limit: int = Query(50, ge=1, le=200, description="返回上限（默认 50）"),
    offset: int = Query(0, ge=0, description="分页偏移"),
    service: UserNewsFavoriteService = Depends(get_user_news_favorite_service),
) -> UserNewsFavoriteListOut:
    """按筛选取收藏列表（默认按 archived_at 倒序）。"""
    return await service.list_items(
        days=days,
        site_name=site_name,
        tag=tag,
        importance_min=importance_min,
        limit=limit,
        offset=offset,
        sort=sort,
    )


@router.get(
    "/items/{fav_id}",
    response_model=UserNewsFavoriteItemOut,
    summary="单条收藏（按主键）",
)
async def get_item(
    fav_id: int,
    service: UserNewsFavoriteService = Depends(get_user_news_favorite_service),
) -> UserNewsFavoriteItemOut:
    item = await service.get(fav_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"favorite id={fav_id} not found")
    return item


@router.get(
    "/sites",
    response_model=list[str],
    summary="收藏中全部来源站（按频次降序）",
)
async def list_sites(
    service: UserNewsFavoriteService = Depends(get_user_news_favorite_service),
) -> list[str]:
    return await service.list_sites()


@router.get(
    "/tags",
    response_model=list[str],
    summary="收藏中全部 tag（解析 JSON 数组 + 去重 + 字母序）",
)
async def list_tags(
    service: UserNewsFavoriteService = Depends(get_user_news_favorite_service),
) -> list[str]:
    return await service.list_tags()


@router.get(
    "/stats",
    response_model=UserNewsFavoriteStatusOut,
    summary="6 维统计：total + by_importance + by_site + by_tag + by_month + 7d/30d 新增",
)
async def get_stats(
    service: UserNewsFavoriteService = Depends(get_user_news_favorite_service),
) -> UserNewsFavoriteStatusOut:
    """侧栏 4-chip + tag 分布 / 来源站分布 / 月度归档用。"""
    return await service.get_status()


@router.get(
    "/exists/{external_id}",
    response_model=UserNewsFavoriteItemOut | None,
    summary="幂等检查：判断某条新闻是否已收藏（UI 按钮态切换用）",
)
async def exists(
    external_id: int,
    source: str = Query("readhub", max_length=32, description="数据源标识"),
    service: UserNewsFavoriteService = Depends(get_user_news_favorite_service),
) -> UserNewsFavoriteItemOut | None:
    """返回已收藏的记录；不存在则 null（200 OK，UI 据此切换 ⭐/☆）。"""
    return await service.find_by_external(external_id, source)


# ────────────── 写：增 / 改 / 删（require_user）──────────────


@router.post(
    "/items",
    response_model=UserNewsFavoriteItemOut,
    status_code=status.HTTP_201_CREATED,
    summary="新增收藏（require_user；重复 → 409）",
    dependencies=[Depends(require_user)],
)
async def add(
    payload: UserNewsFavoriteCreateIn,
    service: UserNewsFavoriteService = Depends(get_user_news_favorite_service),
) -> UserNewsFavoriteItemOut:
    """从 ``news_feed_items`` 收藏时直接传 ``news_external_id``，后端自动回填
    标题/摘要/URL/来源站/发布时间等快照字段；外部 URL 收藏时手动传所有必填字段。
    """
    try:
        return await service.add(payload)
    except DuplicateFavoriteError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch(
    "/items/{fav_id}",
    response_model=UserNewsFavoriteItemOut,
    summary="更新收藏的 user_tags / user_note / importance（require_user）",
    dependencies=[Depends(require_user)],
)
async def update(
    fav_id: int,
    payload: UserNewsFavoriteUpdateIn,
    service: UserNewsFavoriteService = Depends(get_user_news_favorite_service),
) -> UserNewsFavoriteItemOut:
    """任一字段为 None → 不更新。``updated_at`` 自动刷新。"""
    item = await service.update(fav_id, payload)
    if item is None:
        raise HTTPException(
            status_code=404, detail=f"favorite id={fav_id} not found"
        )
    return item


@router.delete(
    "/items/{fav_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="取消收藏（require_user）",
    dependencies=[Depends(require_user)],
)
async def delete(
    fav_id: int,
    service: UserNewsFavoriteService = Depends(get_user_news_favorite_service),
) -> None:
    ok = await service.delete(fav_id)
    if not ok:
        raise HTTPException(
            status_code=404, detail=f"favorite id={fav_id} not found"
        )
