"""权重配置 Schema：技术面/宏观面/合成权重（各组权重和须为 1）。"""

from pydantic import BaseModel, Field, model_validator


class TrendWeightConfig(BaseModel):
    """技术面趋势 5 维度权重。"""

    structure: float = Field(0.30, ge=0, le=1, description="结构（均线排列+MA20斜率）")
    momentum: float = Field(0.20, ge=0, le=1, description="动量（近20日涨幅）")
    support: float = Field(0.20, ge=0, le=1, description="支撑（相对MA20/40乖离）")
    momentum_rsi: float = Field(0.15, ge=0, le=1, description="动能（RSI）")
    drawdown: float = Field(0.15, ge=0, le=1, description="回撤（距高点回撤）")

    @model_validator(mode="after")
    def _sum_to_one(self) -> "TrendWeightConfig":
        total = (
            self.structure + self.momentum + self.support
            + self.momentum_rsi + self.drawdown
        )
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"技术面权重之和须为 1，当前 {total:.3f}")
        return self


class MacroWeightConfig(BaseModel):
    """宏观面 5 因子权重。"""

    dxy: float = Field(0.25, ge=0, le=1, description="美元指数")
    us10y: float = Field(0.20, ge=0, le=1, description="美债10Y收益率")
    us30y: float = Field(0.15, ge=0, le=1, description="美债30Y收益率")
    vix: float = Field(0.15, ge=0, le=1, description="VIX恐慌指数")
    cb_gold: float = Field(0.25, ge=0, le=1, description="国际央行购金量")

    @model_validator(mode="after")
    def _sum_to_one(self) -> "MacroWeightConfig":
        total = self.dxy + self.us10y + self.us30y + self.vix + self.cb_gold
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"宏观面权重之和须为 1，当前 {total:.3f}")
        return self


class CombineWeightConfig(BaseModel):
    """综合指数合成权重：技术面 vs 宏观面 vs 消息面（中短期 ETF 波段操作）。"""

    tech: float = Field(0.30, ge=0, le=1, description="技术面占比（默认 30%）")
    macro: float = Field(0.40, ge=0, le=1, description="宏观面占比（默认 40%）")
    news: float = Field(0.30, ge=0, le=1, description="消息面占比（默认 30%，客户评估）")

    @model_validator(mode="after")
    def _sum_to_one(self) -> "CombineWeightConfig":
        if abs(self.tech + self.macro + self.news - 1.0) > 0.001:
            raise ValueError(f"合成权重之和须为 1，当前 {self.tech + self.macro + self.news:.3f}")
        return self


class WeightConfig(BaseModel):
    """完整权重配置（GET/PUT /settings/weights）。"""

    trend: TrendWeightConfig = Field(default_factory=TrendWeightConfig)
    macro: MacroWeightConfig = Field(default_factory=MacroWeightConfig)
    combine: CombineWeightConfig = Field(default_factory=CombineWeightConfig)
