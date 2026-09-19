"""购买决策端点。"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_decision_service
from app.schemas.position import DecisionOut
from app.services.decision import DecisionService

router = APIRouter(prefix="/decision", tags=["decision"])


@router.get("/etf", response_model=DecisionOut, summary="黄金/白银购买决策")
async def etf_decision(
    days: int = Query(60, ge=20, le=250, description="趋势指数覆盖交易日数"),
    target: str = Query(
        "etf",
        pattern="^(ny|etf|gram|silver_etf|silver_ny)$",
        description="指引标的（V0.71.0 扩展白银）："
        "ny=纽约金COMEX / etf=黄金ETF 518880 / gram=上海金Au99.99 / "
        "silver_etf=白银ETF 562800 / silver_ny=纽约白银COMEX SI",
    ),
    account_id: int | None = Query(None, description="账本 ID；不传=全部账本（持仓摘要合并口径）"),
    service: DecisionService = Depends(get_decision_service),
) -> DecisionOut:
    """综合参数面（趋势评估指数）× 交易面（持仓盈亏）输出买入/持有/卖出建议。

    V0.71.0：``target`` 支持白银双市场（silver_etf / silver_ny），黄金/白银共享
    同一决策引擎，仅「建议仓位」文案按 target 切换（黄金/白银）。旧调用方不传 target
    仍走默认 etf 路径，完全向后兼容。
    """
    try:
        return await service.evaluate(days=days, target=target, account_id=account_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
