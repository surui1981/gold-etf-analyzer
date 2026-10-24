"""交易历史端点：多条件查询 + CSV 导出（P1 #6）。"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    get_db_session,
    get_trade_history_service,
)
from app.schemas.timeline import TimelineOut
from app.schemas.trade import TradeHistoryOut
from app.services.timeline import TimelineService
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


@router.get(
    "/timeline",
    response_model=TimelineOut,
    summary="V0.90.0\uff1a\u51b3\u7b56\u65f6\u95f4\u7ebf\uff08trades + snapshots \u6309\u65e5\u5bf9\u9f50 + \u7a7a\u95f2\u6bb5\u6298\u53e0\uff09",
)
async def trades_timeline(
    account_id: int | None = Query(
        None, description="\u8d26\u672c ID\uff1b\u4e0d\u4f20=\u5168\u90e8\u8d26\u672c"
    ),
    from_date: date | None = Query(
        None, description="\u4e0b\u754c\uff08\u542b\uff09\uff1b\u9ed8\u8ba4 90 \u5929\u524d"
    ),
    to_date: date | None = Query(
        None, description="\u4e0a\u754c\uff08\u542b\uff09\uff1b\u9ed8\u8ba4\u4eca\u65e5"
    ),
    compress_threshold_days: int = Query(
        7,
        ge=0,
        le=365,
        description=(
            "\u7a7a\u95f2\u6bb5\u6298\u53e0\u9608\u503c\uff08> N \u5929\u7684\u7a7a\u95f2\u6bb5\u6298\u53e0\u4e3a 1 \u4e2a compressed=True \u6bb5\uff09\uff1b"
            "0 = \u4e0d\u6298\u53e0"
        ),
    ),
    session: AsyncSession = Depends(get_db_session),
) -> TimelineOut:
    """\u6309\u65e5\u671f\u533a\u95f4\u805a\u5408\u4ea4\u6613\u6d41\u6c34 + \u6bcf\u65e5\u5feb\u7167\u4e3a\u65f6\u95f4\u7ebf\u5e8f\u5217\u3002

    \u6bcf\u4e2a\u51b3\u7b56\u70b9\u9644\u300c\u5f53\u65e5\u6216\u6700\u8fd1\u524d\u4e00\u65e5\u300d\u5feb\u7167\uff1b\u8fde\u7eed\u7a7a\u95f2\u671f\u8d85\u9608\u503c\u5219\u6298\u53e0\u3002
    V0.90.1 \u524d\u7aef review.html \u65f6\u95f4\u7ebf\u89c6\u56fe\u76f4\u63a5\u6d88\u8d39\u672c\u54cd\u5e94\u3002
    """
    today = date.today()
    if to_date is None:
        to_date = today
    if from_date is None:
        from_date = to_date - timedelta(days=90)

    if from_date > to_date:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_date_range",
                "message": f"from_date={from_date} > to_date={to_date}",
            },
        )
    if (to_date - from_date) > timedelta(days=730):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "date_range_too_wide",
                "message": (
                    f"\u8303\u56f4 {(to_date - from_date).days} \u5929 > 730 \u5929\u3002"
                    "\u524d\u7aef\u9ed8\u8ba4 90 \u5929\u7a97\u53e3\uff1b\u5982\u9700\u66f4\u957f\u8bf7\u5206\u9875"
                ),
            },
        )

    svc = TimelineService(session=session)
    return await svc.build(
        account_id=account_id,
        from_date=from_date,
        to_date=to_date,
        compress_threshold_days=compress_threshold_days,
    )
