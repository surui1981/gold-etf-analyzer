"""前端埋点 Schema（V0.68.0）。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TelemetryEventIn(BaseModel):
    """单条埋点事件（前端上报）。"""

    event_type: str = Field(..., min_length=1, max_length=32, description="事件类型")
    page: str = Field(..., min_length=1, max_length=128, description="事件源页路径")
    payload: dict[str, object] = Field(
        default_factory=dict,
        description="业务负载（自由扩展，服务端不解析）",
    )
    session_id: str = Field(default="-", min_length=1, max_length=32, description="客户端会话 ID")
    client_ts: datetime | None = Field(default=None, description="客户端事件时间（仅作参考）")


class TelemetryBatchIn(BaseModel):
    """批量上报（sendBeacon 攒批）。"""

    events: list[TelemetryEventIn] = Field(..., min_length=1, max_length=200)


class TelemetryIngestResult(BaseModel):
    """上报结果。"""

    accepted: int
    rejected: int = 0
    rejected_reasons: list[str] = Field(default_factory=list)


class TelemetryStats(BaseModel):
    """派生指标：单事件类型计数 + 派生率（服务端从表聚合）。"""

    model_config = ConfigDict(from_attributes=True)

    event_type: str
    count_24h: int
    count_7d: int
    rate: float | None = Field(default=None, description="该事件相对 base 事件的比例（如 7 日）")


class TelemetryStatsOut(BaseModel):
    """派生指标聚合输出。"""

    days: int
    total: int
    by_type: list[TelemetryStats]
