"""购买决策端点。"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_decision_service
from app.schemas.position import DecisionOut
from app.services.decision import DecisionService

router = APIRouter(prefix="/decision", tags=["decision"])


@router.get("/etf", response_model=DecisionOut, summary="黄金ETF购买决策")
async def etf_decision(
    days: int = Query(60, ge=20, le=250, description="趋势指数覆盖交易日数"),
    account_id: int | None = Query(None, description="账本 ID；不传=全部账本（持仓摘要合并口径）"),
    service: DecisionService = Depends(get_decision_service),
) -> DecisionOut:
    """综合参数面（趋势评估指数）× 交易面（持仓盈亏）输出买入/持有/卖出建议。"""
    try:
        return await service.evaluate(days=days, account_id=account_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
