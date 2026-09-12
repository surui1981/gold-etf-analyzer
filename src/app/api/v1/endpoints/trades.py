"""交易历史端点：多条件查询 + CSV 导出（P1 #6）。"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse

from app.dependencies import get_trade_history_service
from app.schemas.trade import TradeHistoryOut
from app.services.trades import TradeHistoryService

router = APIRouter(prefix="/trades", tags=["trades"])


@router.get("", response_model=TradeHistoryOut, summary="交易历史查询（多条件 + 分页）")
async def list_trades(
    account_id: int | None = Query(None, description="账本 ID；不传=全部账本"),
    side: str | None = Query(None, description="buy 买入 / sell 卖出；不传=全部"),
    position_id: int | None = Query(None, description="指定持仓 ID"),
    symbol: str | None = Query(None, description="品种代码，如 518880"),
    keyword: str | None = Query(None, description="持仓名称或代码模糊匹配"),
    start: date | None = Query(None, description="成交日期下界（含当日）"),
    end: date | None = Query(None, description="成交日期上界（含当日）"),
    page: int = Query(1, ge=1, description="页码（从 1 起）"),
    page_size: int = Query(50, ge=1, le=500, description="每页条数（1-500）"),
    service: TradeHistoryService = Depends(get_trade_history_service),
) -> TradeHistoryOut:
    """按账本 / 方向 / 日期区间 / 持仓筛选交易流水。

    每条卖出附带**已实现盈亏**与**成交后剩余份额**（均价法逐笔回放，
    与持仓页成本口径一致）；汇总覆盖全部匹配行而非当前页。
    """
    if side is not None and side not in {"buy", "sell"}:
        raise HTTPException(status_code=422, detail="side 必须为 buy 或 sell")
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="起始日期不能晚于结束日期")
    return await service.query(
        account_id=account_id,
        side=side,
        position_id=position_id,
        symbol=symbol,
        keyword=keyword,
        start=start,
        end=end,
        page=page,
        page_size=page_size,
    )


@router.get("/export", response_class=PlainTextResponse, summary="导出交易历史 CSV")
async def export_trades(
    account_id: int | None = Query(None, description="账本 ID；不传=全部账本"),
    side: str | None = Query(None, description="buy 买入 / sell 卖出；不传=全部"),
    position_id: int | None = Query(None, description="指定持仓 ID"),
    symbol: str | None = Query(None, description="品种代码"),
    keyword: str | None = Query(None, description="持仓名称或代码模糊匹配"),
    start: date | None = Query(None, description="成交日期下界（含当日）"),
    end: date | None = Query(None, description="成交日期上界（含当日）"),
    service: TradeHistoryService = Depends(get_trade_history_service),
) -> PlainTextResponse:
    """按当前筛选条件导出**全部**匹配流水（UTF-8 BOM，Excel 友好），末尾附汇总。"""
    csv_text = await service.export_csv(
        account_id=account_id,
        side=side,
        position_id=position_id,
        symbol=symbol,
        keyword=keyword,
        start=start,
        end=end,
    )
    return PlainTextResponse(
        "\ufeff" + csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=trade_history.csv"},
    )
