"""V0.72.0 P3-b：Web Push 端点。

3 个端点：
- ``GET  /push/vapid-public-key`` —— 返回 VAPID 公钥（前端 subscribe 使用）
- ``POST /push/subscribe``       —— 存储/更新订阅（公开，不需 admin 守卫）
- ``DELETE /push/subscribe``     —— 退订（公开）
- ``POST /push/test``            —— 测试推送（admin 守卫）
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db_session
from app.middleware.admin_auth import require_admin
from app.repositories.push import PushSubscriptionRepository
from app.repositories.settings import SettingRepository
from app.schemas.push import (
    PushSubscriptionIn,
    VapidPublicKeyOut,
)
from app.services.push import PushService
from app.services.settings import (
    VapidKeys,
    get_vapid_keys,
    save_vapid_keys,
)

router = APIRouter(prefix="/push", tags=["push"])


# ─── 依赖注入工厂 ────────────────────────────────────────


def get_push_service(session: AsyncSession = Depends(get_db_session)) -> PushService:
    """PushService 工厂：注入 PushSubscriptionRepository。"""
    return PushService(repo=PushSubscriptionRepository(session))


def get_setting_repository(session: AsyncSession = Depends(get_db_session)) -> SettingRepository:
    return SettingRepository(session)


async def _ensure_vapid_keys(repo: SettingRepository) -> VapidKeys:
    """启动期或首次访问时确保 VAPID 密钥对存在。"""
    keys = await get_vapid_keys(repo)
    if keys is not None:
        return keys
    from app.services.push import generate_vapid_keys

    keys = generate_vapid_keys()
    await save_vapid_keys(repo, keys)
    return keys


# ─── 端点 ────────────────────────────────────────


@router.get(
    "/vapid-public-key",
    response_model=VapidPublicKeyOut,
    summary="获取 VAPID 公钥（前端 subscribe 使用）",
)
async def get_vapid_public_key_endpoint(
    repo: SettingRepository = Depends(get_setting_repository),
) -> VapidPublicKeyOut:
    """返回 base64url 公钥；首次访问会自动生成。"""
    keys = await _ensure_vapid_keys(repo)
    return VapidPublicKeyOut(key=keys.public_key)


@router.post(
    "/subscribe",
    response_model=dict,
    summary="新增/更新 Web Push 订阅",
)
async def subscribe_endpoint(
    payload: PushSubscriptionIn,
    service: PushService = Depends(get_push_service),
) -> dict:
    """前端 pushManager.subscribe() 后调用。同一 endpoint 多次订阅视为同一记录。"""
    sub_id = await service.subscribe(payload)
    return {"id": sub_id, "endpoint": payload.endpoint[:60] + "..."}


@router.delete(
    "/subscribe",
    response_model=dict,
    summary="退订（按 endpoint）",
)
async def unsubscribe_endpoint(
    endpoint: str = Query(..., description="订阅的推送端点 URL"),
    service: PushService = Depends(get_push_service),
) -> dict:
    """用户主动取消通知。"""
    ok = await service.unsubscribe(endpoint)
    return {"deleted": ok}


@router.post(
    "/test",
    response_model=dict,
    summary="测试推送：给所有活跃订阅发一条 hello",
    dependencies=[Depends(require_admin)],
)
async def test_push_endpoint(
    service: PushService = Depends(get_push_service),
    settings_repo: SettingRepository = Depends(get_setting_repository),
) -> dict:
    """管理员手动验证推送链路（实际生产需要 push server 联网；CI 下 dry-run）。"""
    keys = await _ensure_vapid_keys(settings_repo)
    subs = await service.repo.list_active()
    sent, failed = await service.deliver(
        subscriptions=subs,
        vapid=keys,
        subject="黄金 ETF · 测试推送",
        body="这是一条测试推送，验证 VAPID + Web Push 配置正确。",
        url="/portfolio",
        tag="test-push",
    )
    return {"sent": sent, "failed": failed, "total": len(subs)}
