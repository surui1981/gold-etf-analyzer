"""每日快照端点：捕获与历史查询。"""

from fastapi import APIRouter, Depends, Query

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
