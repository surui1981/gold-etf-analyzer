"""消息面评估端点：客户每日打分。"""

from fastapi import APIRouter, Depends

from app.dependencies import get_news_score_service
from app.schemas.news import NewsScoreIn, NewsScoreOut
from app.services.news import NewsScoreService

router = APIRouter(prefix="/news-score", tags=["news"])


@router.get("", response_model=NewsScoreOut, summary="当日消息面打分")
async def get_today_score(
    service: NewsScoreService = Depends(get_news_score_service),
) -> NewsScoreOut:
    """当日消息面打分；未打分返回中性参考（scored=false）。"""
    return await service.get_today()


@router.put("", response_model=NewsScoreOut, summary="保存当日消息面打分")
async def save_today_score(
    payload: NewsScoreIn,
    service: NewsScoreService = Depends(get_news_score_service),
) -> NewsScoreOut:
    """客户根据主流财经网站投行黄金展望研判后打分（0-100），汇入每日评估。"""
    return await service.save_today(payload)
