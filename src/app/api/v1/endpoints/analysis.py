"""黄金ETF机会分析端点。"""

from fastapi import APIRouter, Depends, Query

from app.dependencies import get_analysis_service
from app.schemas.analysis import AnalysisRecordOut, OpportunityRequest, OpportunityResponse
from app.services.analysis import AnalysisService

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.post(
    "/opportunity",
    response_model=OpportunityResponse,
    summary="评估黄金ETF交易机会",
    description="提交宏观因子（美元指数/美债收益率/实际利率/通胀预期/避险情绪），"
    "返回加权评分、投资窗口与逐因子多空明细。",
)
async def evaluate_opportunity(
    request: OpportunityRequest,
    service: AnalysisService = Depends(get_analysis_service),
) -> OpportunityResponse:
    """基于宏观因子加权评分，输出交易机会窗口。"""
    return await service.evaluate(request)


@router.get(
    "/history",
    response_model=list[AnalysisRecordOut],
    summary="最近分析记录",
    description="按时间倒序返回历史机会分析记录，默认 20 条。",
)
async def list_history(
    limit: int = Query(default=20, ge=1, le=100, description="返回条数 1-100"),
    service: AnalysisService = Depends(get_analysis_service),
) -> list[AnalysisRecordOut]:
    """历史机会分析记录（倒序）。"""
    return await service.list_history(limit=limit)
