"""交易业绩端点：收益曲线 + 获利分析总结评估（V0.61.0）。"""

from fastapi import APIRouter, Depends, Query

from app.dependencies import get_portfolio_analytics_service
from app.schemas.portfolio import EquityCurveOut, PerformanceOut
from app.services.portfolio import PortfolioAnalyticsService

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/equity-curve", response_model=EquityCurveOut, summary="收益曲线（回放重建）")
async def equity_curve(
    days: int = Query(90, ge=7, le=730, description="展示区间（自然日，默认 90）"),
    account_id: int | None = Query(None, description="账本 ID；不传=全部账本（合并口径）"),
    service: PortfolioAnalyticsService = Depends(get_portfolio_analytics_service),
) -> EquityCurveOut:
    """由交易流水 + ETF 历史价回放重建每日收益曲线。

    产出每日持有份数、成本、市值、已实现 / 浮动盈亏与累计收益率；
    成本口径与持仓页一致（均价法）；非交易日成交顺延至其后的首个交易日生效。
    无交易记录时返回空点位（前端展示引导文案）。
    """
    return await service.equity_curve(days=days, account_id=account_id)


@router.get("/performance", response_model=PerformanceOut, summary="获利分析总结评估")
async def performance(
    account_id: int | None = Query(None, description="账本 ID；不传=全部账本"),
    service: PortfolioAnalyticsService = Depends(get_portfolio_analytics_service),
) -> PerformanceOut:
    """已实现 / 浮动盈亏、胜率、盈亏比、平均持仓天数与中文总结。

    无交易与持仓时返回空态与引导文案，不报错。
    """
    return await service.performance(account_id=account_id)
