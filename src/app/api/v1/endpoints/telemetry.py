"""前端埋点端点（V0.68.0）：批量入库 + 派生指标查询。

POST /api/v1/telemetry/ingest    —— 前端 sendBeacon 上报（白名单校验）
GET  /api/v1/telemetry/stats     —— 派生指标聚合（按事件类型 24h / 7d）
"""

from fastapi import APIRouter, Depends, Query, Request

from app.dependencies import get_telemetry_service
from app.middleware.trace import get_current_trace_id
from app.schemas.telemetry import TelemetryBatchIn, TelemetryIngestResult, TelemetryStatsOut
from app.services.telemetry import TelemetryService

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


@router.post(
    "/ingest",
    response_model=TelemetryIngestResult,
    summary="前端埋点批量入库（白名单校验）",
)
async def ingest_events(
    batch: TelemetryBatchIn,
    request: Request,
    service: TelemetryService = Depends(get_telemetry_service),
) -> TelemetryIngestResult:
    """前端 sendBeacon / fetch keepalive 上报。

    透传 :class:`app.middleware.trace.TraceIdMiddleware` 注入的 trace_id，
    用于「同一会话内」浏览 → 操作的串联。
    """
    return await service.ingest(batch, trace_id=get_current_trace_id())


@router.get(
    "/stats",
    response_model=TelemetryStatsOut,
    summary="派生指标聚合（按事件类型）",
)
async def get_stats(
    days: int = Query(7, ge=1, le=30, description="聚合窗口（天）"),
    service: TelemetryService = Depends(get_telemetry_service),
) -> TelemetryStatsOut:
    """最近 N 天各事件类型计数 + 占比。

    仅聚合、不含原始 payload —— 前端应在 payload 里只放必要字段。
    """
    return await service.stats(days=days)
