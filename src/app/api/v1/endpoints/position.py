"""持仓管理端点：开仓 / 列表 / 加减仓 / 清仓。"""

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_position_service
from app.schemas.position import PositionCreate, PositionOut, TradeRequest
from app.services.position import PositionService

router = APIRouter(prefix="/positions", tags=["positions"])


@router.post("", response_model=PositionOut, status_code=201, summary="开仓")
async def open_position(
    request: PositionCreate,
    service: PositionService = Depends(get_position_service),
) -> PositionOut:
    """建仓买入黄金ETF，记录成本与流水。"""
    return await service.open(request)


@router.get("", response_model=list[PositionOut], summary="持仓列表（含实时盈亏）")
async def list_positions(
    service: PositionService = Depends(get_position_service),
) -> list[PositionOut]:
    """当前未平仓持仓，实时市价估值。"""
    return await service.list_positions()


@router.post("/{position_id}/trades", response_model=PositionOut, summary="加仓/减仓")
async def add_trade(
    position_id: int,
    request: TradeRequest,
    service: PositionService = Depends(get_position_service),
) -> PositionOut:
    """buy=加仓（摊薄成本）；sell=减仓（均价不变）。"""
    try:
        return await service.add_trade(position_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{position_id}/close", response_model=PositionOut, summary="清仓")
async def close_position(
    position_id: int,
    service: PositionService = Depends(get_position_service),
) -> PositionOut:
    """按最新市价全部卖出并平仓。"""
    try:
        return await service.close(position_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
