"""消息面评估端点：客户每日打分（V0.65.0：每日最多 3 次机会）。"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_news_score_service
from app.schemas.news import NewsHistoryOut, NewsScoreIn, NewsScoreOut
from app.services.news import NewsScoreService

router = APIRouter(prefix="/news-score", tags=["news"])


@router.get("", response_model=NewsScoreOut, summary="当日消息面打分（含 3 个槽位明细）")
async def get_today_score(
    service: NewsScoreService = Depends(get_news_score_service),
) -> NewsScoreOut:
    """当日打分：返回第 1/2/3 次各自的明细与加权有效分值（未打分 scored=false）。"""
    return await service.get_today()


@router.put("", response_model=NewsScoreOut, summary="保存一次消息面打分")
async def save_today_score(
    payload: NewsScoreIn,
    service: NewsScoreService = Depends(get_news_score_service),
) -> NewsScoreOut:
    """客户根据主流财经网站投行黄金展望研判后打分（0-100），汇入每日评估。

    ``slot`` 留空自动占用下一个空闲槽位；三次用尽后留空提交返回 400，
    需显式指定 ``slot`` 以修改对应槽位。
    """
    try:
        return await service.save_today(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{slot}", response_model=NewsScoreOut, summary="撤销当日某一次打分")
async def delete_today_slot(
    slot: int,
    service: NewsScoreService = Depends(get_news_score_service),
) -> NewsScoreOut:
    """撤销当日第 ``slot`` 次打分并释放该槽位；不存在返回 404。"""
    try:
        return await service.delete_slot(slot)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/history", response_model=NewsHistoryOut, summary="历史打分记录（跨日回看）")
async def get_history(
    limit: int = Query(15, ge=1, le=100, description="返回条数上限"),
    service: NewsScoreService = Depends(get_news_score_service),
) -> NewsHistoryOut:
    """最近若干条打分记录，按时间倒序。"""
    return await service.get_history(limit)
