"""消息面 Schema。"""

from datetime import date

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import DirectionSignal


class NewsScoreIn(BaseModel):
    """客户消息面打分请求。"""

    score: float = Field(..., ge=0, le=100, description="看多强度 0-100（>55 看多，<45 看空）")
    direction: DirectionSignal = Field(DirectionSignal.NEUTRAL, description="方向")
    notes: str = Field("", max_length=2000, description="研判备注（参考投行观点/链接）")

    @field_validator("direction", mode="before")
    @classmethod
    def _parse_direction(cls, v) -> DirectionSignal:
        if isinstance(v, str):
            return DirectionSignal(v)
        return v


class NewsScoreOut(BaseModel):
    """消息面打分输出。"""

    score_date: date
    score: float
    direction: DirectionSignal
    notes: str
    # 是否已打分（未打分时 score 为中性参考 50）
    scored: bool = True
    # 上一次打分（供「沿用上次」），无历史则为 None
    last_score: float | None = None
    last_date: date | None = None
    last_notes: str = ""
