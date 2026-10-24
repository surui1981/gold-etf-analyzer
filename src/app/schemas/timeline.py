"""决策时间线回放 Schema（V0.90.0）。

``TimelineOut`` 把交易流水与每日快照按日期对齐，输出决策点 + 空闲段序列，
供 review.html 时间线视图直接渲染。
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.snapshot import SnapshotOut
from app.schemas.trade import TradeHistoryItem


class TimelineSegment(BaseModel):
    """时间线一段：决策点（单日 trade + 对齐快照）或空闲段（连续 N 天无 trade）。"""

    type: Literal["decision", "idle"]
    start: date = Field(..., description="段开始日期（含）")
    end: date = Field(..., description="段结束日期（含）；decision 单日 = end == start")

    # decision 段独有字段
    trade: TradeHistoryItem | None = Field(None, description="决策段对应的交易流水（单条 trade）")
    snapshot: SnapshotOut | None = Field(
        None,
        description=(
            "对齐的快照：trade 当日若不存在快照，回退取最近前一日（沿用 "
            "``DailySnapshotService.get_previous`` 语义）。无任何快照则为 None"
        ),
    )

    # idle 段独有字段
    idle_days: int | None = Field(None, description="空闲段跨度（天）")
    compressed: bool | None = Field(
        None,
        description=(
            "是否折叠：空闲天数 > compress_threshold_days 时为 True。False/None = 正常展示未折叠"
        ),
    )


class TimelineOut(BaseModel):
    """决策时间线回放响应。"""

    from_date: date
    to_date: date
    span_days: int = Field(..., description="总跨度（含首尾）")
    active_days: int = Field(
        ...,
        description=("活跃天数：有 trade 或 snapshot 的日期去重数。用于前端展示「覆盖密度」"),
    )
    decision_count: int = Field(..., description="决策点（trade）总数")
    segments: list[TimelineSegment]
