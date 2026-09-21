"""v1 路由聚合：所有端点挂载到 /api/v1 前缀之下。"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    account,
    analysis,
    backtest,
    central_bank,
    decision,
    health,
    market,
    news,
    portfolio,
    position,
    push,
    resonance,
    review,
    settings,
    snapshot,
    telemetry,
    trades,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(analysis.router)
api_router.include_router(market.router)
api_router.include_router(position.router)
api_router.include_router(account.router)
api_router.include_router(trades.router)
api_router.include_router(decision.router)
api_router.include_router(settings.router)
api_router.include_router(snapshot.router)
api_router.include_router(news.router)
api_router.include_router(review.router)
api_router.include_router(resonance.router)  # V0.70.0 P2 #7
api_router.include_router(central_bank.router)
api_router.include_router(portfolio.router)
api_router.include_router(telemetry.router)
api_router.include_router(backtest.router)  # V0.71.0 P3-a
api_router.include_router(push.router)  # V0.72.0 P3-b Web Push
