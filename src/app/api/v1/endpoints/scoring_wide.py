"""打分数据宽表端点（V0.92.0 · 历史打分数据汇总）

4 个端点：
- ``GET /api/v1/scoring/summary?from=&to=&group_by=day|week|month&tag=``
- ``GET /api/v1/scoring/by-date/{date}``
- ``GET /api/v1/scoring/hit-stats?from=&to=&horizon=t1|t3|t5``
- ``GET /api/v1/scoring/by-tag?from=&to=``

全部走 ``scoring_daily_wide`` 物化宽表（O(天数) 索引扫描），不走
4-6 表 JOIN + JSON parse（V0.91.0 timeline 之前的痛点）。
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_scoring_wide_service
from app.schemas.scoring_wide import (
    ScoringByTagOut,
    ScoringHitStatsAllOut,
    ScoringHitStatsOut,
    ScoringSummaryOut,
    ScoringVerdictOut,
    ScoringWideListOut,
    ScoringWideOut,
)
from app.services.scoring_wide import ScoringWideService

router = APIRouter(prefix="/scoring", tags=["scoring"])


def _validate_range(start: date, end: date, max_days: int = 730) -> None:
    """统一区间校验：start > end 报 400；范围 > max_days 报 400。"""
    if start > end:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_date_range",
                "message": f"start={start} > end={end}",
            },
        )
    if (end - start) > timedelta(days=max_days):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "date_range_too_wide",
                "message": f"范围 {(end - start).days} 天 > {max_days} 天上限",
            },
        )


@router.get(
    "/summary",
    response_model=ScoringSummaryOut,
    summary="V0.92.0：按 day/week/month 分桶聚合 4 指数 + 命中率",
)
async def scoring_summary(
    from_date: date = Query(..., alias="from", description="下界（含）"),
    to_date: date = Query(..., alias="to", description="上界（含）"),
    group_by: str = Query("day", pattern="^(day|week|month)$", description="分桶粒度"),
    tag: str | None = Query(None, description="按 basis_tags 包含过滤（可选）"),
    # V0.92.1 hotfix：行级命中筛选（默认 "all"）+ 所选 horizon（默认 t1）
    hit: str = Query(
        "all",
        alias="hit",
        pattern="^(all|yes|no)$",
        description="行级命中筛选：yes=仅命中 / no=仅未命中 / all=全部",
    ),
    horizon: str = Query(
        "t1",
        pattern="^(t0|t1|t3|t5)$",  # V0.93.0：加 t0
        description="命中筛选与 bucket.hit 字段所用的 horizon",
    ),
    service: ScoringWideService = Depends(get_scoring_wide_service),
) -> ScoringSummaryOut:
    """按 day/week/month 分桶聚合。可选 tag 过滤（如 "美元指数"）。"""
    _validate_range(from_date, to_date)
    return await service.summary(
        start=from_date,
        end=to_date,
        group_by=group_by,
        tag=tag,
        hit_filter=hit,
        horizon=horizon,
    )


@router.get(
    "/by-date/{target_date}",
    response_model=ScoringWideOut,
    summary="V0.92.0：按日期取单日宽表行",
)
async def scoring_by_date(
    target_date: date,
    service: ScoringWideService = Depends(get_scoring_wide_service),
) -> ScoringWideOut:
    """按日期取单日打分宽表行（4 指数 + 消息面 + 共振 + outcomes）。"""
    row = await service.get_by_date(target_date)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "scoring_wide_not_found",
                "date": target_date.isoformat(),
                "message": f"{target_date} 无宽表行（可能未捕获快照 + 无打分 + 无价格）",
            },
        )
    return row


@router.get(
    "/hit-stats",
    response_model=ScoringHitStatsOut,
    summary="V0.92.0：按 horizon 聚合命中率（按方向 / 按月 / 校准曲线）",
)
async def scoring_hit_stats(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    horizon: str = Query("t5", pattern="^(t0|t1|t3|t5)$"),  # V0.93.0：加 t0
    service: ScoringWideService = Depends(get_scoring_wide_service),
) -> ScoringHitStatsOut:
    """按 horizon 聚合命中率（按方向 / 按月 / 校准曲线 3 维）。"""
    _validate_range(from_date, to_date)
    return await service.hit_stats(start=from_date, end=to_date, horizon=horizon)


@router.get(
    "/hit-stats-all",
    response_model=ScoringHitStatsAllOut,
    summary="V0.96.0：4 horizon (t0/t1/t3/t5) by_month + mini card 摘要",
)
async def scoring_hit_stats_all(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    service: ScoringWideService = Depends(get_scoring_wide_service),
) -> ScoringHitStatsAllOut:
    """1 次调用取 4 horizon 全部数据 + 3 mini card 摘要（最近 30 天 / MoM / 最佳 horizon）。

    V0.96.0 配套「命中分析」Tab：1 张柱状图 + 3 mini card。
    旧 ``/hit-stats?horizon=tN`` 单 horizon 端点保留，向后兼容。
    """
    _validate_range(from_date, to_date)
    return await service.hit_stats_all_horizons(start=from_date, end=to_date)


@router.get(
    "/by-tag",
    response_model=ScoringByTagOut,
    summary="V0.92.0：按依据标签统计出现次数与各 horizon 命中率",
)
async def scoring_by_tag(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    service: ScoringWideService = Depends(get_scoring_wide_service),
) -> ScoringByTagOut:
    """按 basis_tags 维度统计 12 个标签的出现次数与 T+1/T+3/T+5 命中率。"""
    _validate_range(from_date, to_date)
    return await service.by_tag(start=from_date, end=to_date)


@router.post(
    "/rebuild/{target_date}",
    response_model=ScoringWideOut | None,
    summary="V0.92.0：手动重算单日宽表行（CLI/补调用）",
)
async def scoring_rebuild(
    target_date: date,
    service: ScoringWideService = Depends(get_scoring_wide_service),
) -> ScoringWideOut | None:
    """手动重算单日宽表行。返回 None = 当日 3 个源表都无数据，不写空行。"""
    return await service.rebuild(target_date)


# 复用：list_in_range 端点供前端 detail 视图用
@router.get(
    "",
    response_model=ScoringWideListOut,
    summary="V0.92.0：按日期范围取宽表行（升序，含首尾）",
)
async def scoring_list(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    service: ScoringWideService = Depends(get_scoring_wide_service),
) -> ScoringWideListOut:
    """按日期范围取宽表行（升序，含首尾）—— 供前端 detail 视图用。"""
    _validate_range(from_date, to_date)
    return await service.list_in_range(start=from_date, end=to_date)


# V0.94.0：预测评估卡端点（scoring 页顶部）
@router.get(
    "/verdict",
    response_model=ScoringVerdictOut,
    summary="V0.94.0：单日预测评估卡（方向 + 4 horizon 状态 + 一句话总结）",
)
async def scoring_verdict(
    target_date: date = Query(..., alias="date", description="评估日期（默认今天）"),
    service: ScoringWideService = Depends(get_scoring_wide_service),
) -> ScoringVerdictOut:
    """取单日预测评估卡：方向 + 4 horizon 状态 + 一句话 summary。

    4 个 horizon 状态：
    - ``ready``：hit 字段已就绪（可显示「命中/未命中 + 实际涨跌」）
    - ``pending``：等待 T+N 收盘（显示「等待中」）
    - ``missing``：字段不一致 / 无方向
    """
    return await service.verdict(target_date=target_date)
