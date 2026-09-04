"""持仓管理端点：开仓 / 列表 / 加减仓 / 清仓 / 软删除 / 撤销 / 导出。"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from app.dependencies import get_position_service
from app.schemas.position import (
    PositionCreate,
    PositionDeleteOut,
    PositionOut,
    TradeRequest,
)
from app.services.position import PositionService

router = APIRouter(prefix="/positions", tags=["positions"])


@router.post("", response_model=PositionOut, status_code=201, summary="开仓")
async def open_position(
    request: PositionCreate,
    service: PositionService = Depends(get_position_service),
) -> PositionOut:
    """建仓买入黄金ETF，记录成本与流水。"""
    try:
        return await service.open(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[PositionOut], summary="持仓列表（含实时盈亏）")
async def list_positions(
    service: PositionService = Depends(get_position_service),
) -> list[PositionOut]:
    """当前未平仓且未删除持仓，实时市价估值。"""
    return await service.list_positions()


@router.get("/export", response_class=PlainTextResponse, summary="导出持仓与流水 CSV")
async def export_positions(
    service: PositionService = Depends(get_position_service),
) -> PlainTextResponse:
    """导出当前持仓 + 交易流水为 CSV（UTF-8 BOM，Excel 友好）。"""
    csv_text = await service.export_csv()
    return PlainTextResponse(
        "\ufeff" + csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=positions_export.csv"},
    )


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


@router.delete("/{position_id}", response_model=PositionDeleteOut, summary="软删除（可撤销）")
async def delete_position(
    position_id: int,
    service: PositionService = Depends(get_position_service),
) -> PositionDeleteOut:
    """软删除持仓：数据保留，可经 /restore 撤销恢复。"""
    try:
        return await service.delete(position_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{position_id}/restore", response_model=PositionDeleteOut, summary="撤销软删除")
async def restore_position(
    position_id: int,
    service: PositionService = Depends(get_position_service),
) -> PositionDeleteOut:
    """撤销软删除：恢复持仓显示。"""
    try:
        return await service.restore(position_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
