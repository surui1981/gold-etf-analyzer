"""共振信号端点（V0.70.0 P2 #7）。

提供 3 个 GET：
- ``/signal``：今日共振信号（最强信号 + 置信度 + 三维分值）
- ``/history``：近 N 天共振历史（按日期倒序）
- ``/strength-up``：STRONG_UP 在 T+H 的命中率（用于回看强信号的胜率）
"""

from fastapi import APIRouter, Depends, Query

from app.dependencies import get_resonance_service
from app.schemas.resonance import (
    ResonanceHistoryOut,
    ResonanceSignalOut,
    StrengthUpStatsOut,
)
from app.services.resonance import ResonanceService

router = APIRouter(prefix="/resonance", tags=["resonance"])


@router.get(
    "/signal",
    response_model=ResonanceSignalOut,
    summary="今日共振信号",
)
async def get_resonance_signal(
    service: ResonanceService = Depends(get_resonance_service),
) -> ResonanceSignalOut:
    """今日宏观/技术/消息面三维共振信号（4 类 + 置信度 0-100）。"""
    return await service.signal_today()


@router.get(
    "/history",
    response_model=ResonanceHistoryOut,
    summary="近 N 天共振历史（按日期倒序）",
)
async def get_resonance_history(
    days: int = Query(30, ge=1, le=90, description="回看天数（1-90）"),
    service: ResonanceService = Depends(get_resonance_service),
) -> ResonanceHistoryOut:
    """按日期倒序返回共振信号；V0.70.0 MVP 仅历史消息面维度有值。"""
    return await service.history(days=days)


@router.get(
    "/strength-up",
    response_model=StrengthUpStatsOut,
    summary="STRONG_UP 命中统计（强共振看多在 T+H 的胜率）",
)
async def get_strength_up_stats(
    days: int = Query(90, ge=1, le=365, description="回看天数（1-365）"),
    horizon: int = Query(1, description="T+H 窗口（1/3/5）"),
    service: ResonanceService = Depends(get_resonance_service),
) -> StrengthUpStatsOut:
    """STRONG_UP 信号在 T+H 窗口的命中率（用于复盘强共振信号的胜率）。"""
    return await service.strength_up(days=days, horizon=horizon)
