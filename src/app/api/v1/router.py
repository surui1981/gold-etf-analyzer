"""v1 路由聚合：所有端点挂载到 /api/v1 前缀之下。"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    analysis,
    decision,
    health,
    market,
    position,
    settings,
    snapshot,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(analysis.router)
api_router.include_router(market.router)
api_router.include_router(position.router)
api_router.include_router(decision.router)
api_router.include_router(settings.router)
api_router.include_router(snapshot.router)
