"""消息面 Schema（V0.65.0：每日最多 3 次打分机会 + 加权汇总）。

V0.66.0：补充结构化研判依据（``basis`` 标签数组）、事后复盘批注
（``review_note``）以及按指定日期补录（``score_date``）。
"""

import json
from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.models.news import MAX_DAILY_SLOTS
from app.schemas.common import DirectionSignal


class NewsScoreIn(BaseModel):
    """客户消息面打分请求。

    ``slot`` 留空时自动占用当日下一个空闲槽位（第 1 → 2 → 3 次）；
    三次用尽后再提交需显式指定 ``slot`` 以**修改**对应槽位，
    否则返回 400（不再静默覆盖，避免误丢已有研判）。

    ``score_date`` 用于**补录历史研判**：留空即当日；传入非当日日期时
    记录会被标记 ``backfilled``，复盘统计默认排除，避免前视偏差。
    """

    score: float = Field(..., ge=0, le=100, description="看多强度 0-100（>55 看多，<45 看空）")
    direction: DirectionSignal = Field(DirectionSignal.NEUTRAL, description="方向")
    notes: str = Field("", max_length=2000, description="研判备注（参考投行观点/链接）")
    basis: list[str] = Field(
        default_factory=list, description="研判依据标签（来自 /review/meta 的 basis_tags）"
    )
    review_note: str = Field("", max_length=2000, description="事后复盘批注")
    slot: int | None = Field(
        None,
        ge=1,
        le=MAX_DAILY_SLOTS,
        description=f"写入/修改的槽位（1-{MAX_DAILY_SLOTS}）；留空则自动占用下一个空闲槽位",
    )
    score_date: date | None = Field(
        None, description="打分日期；留空为当日，传入历史日期即为补录（标记 backfilled）"
    )

    @field_validator("direction", mode="before")
    @classmethod
    def _parse_direction(cls, v) -> DirectionSignal:
        if isinstance(v, str):
            return DirectionSignal(v)
        return v

    @field_validator("basis", mode="before")
    @classmethod
    def _parse_basis(cls, v) -> list[str]:
        """兼容前端直接提交 JSON 字符串或逗号分隔文本。"""
        if v is None or v == "":
            return []
        if isinstance(v, str):
            text = v.strip()
            if text.startswith("["):
                try:
                    return [str(x) for x in json.loads(text)]
                except json.JSONDecodeError:
                    pass
            return [p.strip() for p in text.split(",") if p.strip()]
        return [str(x) for x in v]


class NewsSlotOut(BaseModel):
    """当日单个打分槽位。"""

    slot: int
    score: float
    direction: DirectionSignal
    notes: str
    weight: int = Field(..., description="该槽位权重（越晚越高：1/2/3）")
    scored_at: datetime | None = Field(None, description="该次打分的提交时刻（UTC）")
    basis: list[str] = Field(default_factory=list, description="该次研判依据标签")
    review_note: str = Field("", description="事后复盘批注")
    backfilled: bool = Field(False, description="是否为事后补录")


class NewsScoreOut(BaseModel):
    """消息面打分输出（含当日槽位明细与加权有效分值）。"""

    score_date: date
    # —— 当日有效分值（多次打分加权合成；单次时即该次分值）——
    score: float
    direction: DirectionSignal
    notes: str
    # 是否已打分（未打分时 score 为中性参考 50）
    scored: bool = True
    # 是否由多次打分加权合成
    weighted: bool = False
    # 当日各槽位明细（按 slot 升序）
    slots: list[NewsSlotOut] = Field(default_factory=list)
    used_slots: int = 0
    max_slots: int = MAX_DAILY_SLOTS
    remaining_slots: int = MAX_DAILY_SLOTS
    # 下一个待用槽位；三次用尽后为 None
    next_slot: int | None = None
    # 加权算式可读说明，如 "(1×40 + 2×65 + 3×70) ÷ 6"
    formula: str = ""
    # 上一次打分（供「沿用上次」），无历史则为 None
    last_score: float | None = None
    last_date: date | None = None
    last_notes: str = ""


class NewsHistoryItem(BaseModel):
    """历史打分记录条目（跨日回看）。"""

    score_date: date
    slot: int
    score: float
    direction: DirectionSignal
    notes: str
    scored_at: datetime | None = None
    weight: int = 1
    basis: list[str] = Field(default_factory=list)
    backfilled: bool = False


class NewsHistoryOut(BaseModel):
    """历史打分记录列表（时间倒序）。"""

    items: list[NewsHistoryItem] = Field(default_factory=list)
    total: int = 0
