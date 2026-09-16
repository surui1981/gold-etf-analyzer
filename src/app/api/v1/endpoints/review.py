"""研判复盘端点（V0.66.0）：按日期归档研判 + 次日金价对比 + 准确率统计。"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_review_service
from app.models.review import DEFAULT_REVIEW_TARGET, REVIEW_HORIZONS
from app.schemas.review import (
    BackfillOut,
    JournalOut,
    ReviewMetaOut,
    ReviewStatsOut,
)
from app.services.review import ReviewService

router = APIRouter(prefix="/review", tags=["review"])


@router.get("/meta", response_model=ReviewMetaOut, summary="复盘配置（标的/窗口/依据标签）")
async def get_meta(
    target: str = Query(DEFAULT_REVIEW_TARGET, description="基准标的：ny/etf/gram"),
    service: ReviewService = Depends(get_review_service),
) -> ReviewMetaOut:
    """返回可选标的、判定窗口、预置研判依据标签与价格日历积累情况。"""
    return await service.meta(target)


@router.get("/journal", response_model=JournalOut, summary="研判日志（按日期归档 + 后续表现）")
async def get_journal(
    days: int = Query(30, ge=1, le=365, description="回看天数（自然日）"),
    horizon: int = Query(1, description="卡片主判定窗口：1/3/5 个交易日"),
    target: str = Query(DEFAULT_REVIEW_TARGET, description="基准标的：ny/etf/gram"),
    service: ReviewService = Depends(get_review_service),
) -> JournalOut:
    """按日期倒序返回每日研判：分值/方向/依据/备注 + T+1/T+3/T+5 金价对比。"""
    return await service.journal(days=days, target=target, horizon=horizon)


@router.get("/stats", response_model=ReviewStatsOut, summary="命中率与校准统计")
async def get_stats(
    days: int = Query(90, ge=1, le=730, description="统计回看天数（自然日）"),
    horizon: int = Query(1, description="主判定窗口：1/3/5 个交易日"),
    target: str = Query(DEFAULT_REVIEW_TARGET, description="基准标的：ny/etf/gram"),
    service: ReviewService = Depends(get_review_service),
) -> ReviewStatsOut:
    """整体命中率、按方向分组、分值分箱校准曲线、依据标签胜率。

    含补录记录（``backfilled``）的日期默认排除，避免前视偏差抬高准确率。
    """
    return await service.stats(days=days, target=target, horizon=horizon)


@router.post("/backfill", response_model=BackfillOut, summary="回填历史金价（建立对比基准）")
async def post_backfill(
    days: int = Query(60, ge=5, le=730, description="回填交易日数量"),
    target: str = Query(DEFAULT_REVIEW_TARGET, description="基准标的：ny/etf/gram"),
    service: ReviewService = Depends(get_review_service),
) -> BackfillOut:
    """从行情接口拉取历史日收盘价写入价格日历（幂等，可重复执行）。"""
    try:
        return await service.backfill(days=days, target=target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/hint", summary="打分前的历史提示（该分值区间的历史命中率）")
async def get_hint(
    score: float = Query(..., ge=0, le=100, description="拟打分值"),
    days: int = Query(90, ge=1, le=730, description="统计回看天数"),
    target: str = Query(DEFAULT_REVIEW_TARGET, description="基准标的"),
    service: ReviewService = Depends(get_review_service),
) -> dict:
    """给定分值返回其所在分值分箱的历史命中率与上涨概率，供打分页即时提示。

    样本不足时 ``sample_warning=true``，前端应标注「样本积累中」。
    """
    return await service.hint_for_score(score, days=days, target=target)


@router.get("/horizons", summary="可用判定窗口")
async def get_horizons() -> dict:
    """返回支持的判定窗口（交易日）与默认值。"""
    return {"horizons": list(REVIEW_HORIZONS), "default": REVIEW_HORIZONS[0]}
