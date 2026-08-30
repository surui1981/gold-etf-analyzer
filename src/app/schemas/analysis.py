"""机会分析相关 Schema：请求 / 响应 / 历史记录。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import DirectionSignal, OpportunityWindow
from app.schemas.factors import MacroFactorInput


class OpportunityRequest(BaseModel):
    """机会分析请求：宏观因子 + 可选的参考金价。"""

    factors: MacroFactorInput
    gold_price_usd: float | None = Field(
        default=None,
        gt=0,
        description="参考金价（美元/盎司），仅作展示，不参与评分",
        examples=[2350.5],
    )


class FactorSignal(BaseModel):
    """单个因子的信号明细：方向、权重与对总分的贡献。"""

    factor: str
    value: float
    direction: DirectionSignal
    weight: float = Field(..., ge=0, le=1, description="因子权重")
    contribution: float = Field(..., ge=0, le=100, description="对总分的贡献（友好度分 × 权重）")
    reason: str = Field(..., description="信号解释")


class OpportunityResponse(BaseModel):
    """机会分析结果：综合评分 + 投资窗口 + 因子明细。"""

    score: float = Field(..., ge=0, le=100, description="综合机会评分 0-100")
    window: OpportunityWindow
    signal: DirectionSignal
    summary: str = Field(..., description="一句话结论")
    factors: list[FactorSignal]
    timestamp: datetime
    record_id: int | None = Field(default=None, description="持久化后的记录 ID")


class AnalysisRecordOut(BaseModel):
    """历史分析记录输出（从 ORM 自动转换）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    dxy: float
    us10y_yield: float
    real_rate: float
    inflation_expectation: float
    risk_off: int
    score: float
    window: OpportunityWindow
    signal: DirectionSignal
    factors_detail: str
    created_at: datetime
