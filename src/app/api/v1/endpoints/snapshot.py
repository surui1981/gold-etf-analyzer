"""每日快照端点：捕获与历史查询。"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_snapshot_service
from app.schemas.snapshot import SnapshotListOut, SnapshotOut
from app.services.snapshot import DailySnapshotService

router = APIRouter(prefix="/snapshots", tags=["snapshots"])


@router.post("/capture", response_model=SnapshotOut, summary="捕获当日评估快照")
async def capture_today(
    service: DailySnapshotService = Depends(get_snapshot_service),
) -> SnapshotOut:
    """抓取当日价格参数与评估值并持久化（同日重复为更新）。"""
    return await service.capture_today()


@router.get("", response_model=SnapshotListOut, summary="历史评估快照（自动补当日）")
async def list_snapshots(
    days: int = Query(30, ge=1, le=365, description="返回最近 N 天"),
    service: DailySnapshotService = Depends(get_snapshot_service),
) -> SnapshotListOut:
    """返回历史每日快照（价格参数 + 技术/宏观/综合指数），当日缺省时自动捕获。"""
    return await service.list_history(days=days)


@router.get(
    "/by-date/{snapshot_date}",
    response_model=SnapshotOut,
    summary="V0.90.0：按日期取单日快照详情",
)
async def get_snapshot_by_date(
    snapshot_date: date,
    service: DailySnapshotService = Depends(get_snapshot_service),
) -> SnapshotOut:
    """按日期取单日快照（含 ``macro_detail`` 已反序列化为 dict）。

    V0.90.0 决策时间线回放的核心查询：决策点点击 → 取当时状态卡片。

    错误：
    - 404 ``snapshot_not_found``：当日无快照（节假日 / 数据缺失）
    """
    snap = await service.get_by_date(snapshot_date)
    if snap is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "snapshot_not_found",
                "date": snapshot_date.isoformat(),
                "message": f"{snapshot_date} 无快照（可能为节假日 / 数据未捕获）",
            },
        )
    return snap


@router.get(
    "/in-range",
    response_model=SnapshotListOut,
    summary="V0.90.0：按日期范围取快照列表",
)
async def list_snapshots_in_range(
    start: date = Query(..., description="下界（含）"),
    end: date = Query(..., description="上界（含）"),
    service: DailySnapshotService = Depends(get_snapshot_service),
) -> SnapshotListOut:
    """按日期范围取快照列表（按日期升序，含首尾）。

    V0.90.0 timeline 聚合复用：批量取时间窗内所有快照，避免 N+1。

    错误：
    - 400 ``invalid_date_range``：``start > end``
    - 400 ``date_range_too_wide``：范围 > 2 年（防前端渲染卡）
    """
    if start > end:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_date_range",
                "message": f"start={start} > end={end}",
            },
        )
    if (end - start) > timedelta(days=730):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "date_range_too_wide",
                "message": (
                    f"范围 {(end - start).days} 天 > 730 天（2 年上限）。"
                    "前端默认 90 天窗口；如需更长请分页"
                ),
            },
        )
    rows = await service.get_in_range(start, end)
    return SnapshotListOut(total=len(rows), snapshots=rows)
