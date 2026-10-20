"""权重配置 Schema：技术面/宏观面/合成权重（各组权重和须为 1）。

V0.110.0 起另含**宏观因子手动校准**（``MacroFactorOverrideSet``）—— 解决
``dxy`` / ``vix`` 长期停在 ``STATIC_REF``（2026-08-28）导致宏观面评分失真的问题。
"""

from datetime import date

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
        total = self.structure + self.momentum + self.support + self.momentum_rsi + self.drawdown
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
    # V0.79.0 Step F：技术面 5 维度合成方式开关。True=组内平均（默认；降低内部相关性），
    # False=单维度加权（历史行为，向后兼容）。不影响宏观/消息面合成。
    group_combine: bool = Field(
        True,
        description="技术面 5 维度是否按组内平均合成（V0.79.0 Step F，默认开启）",
    )


# ───────────────────── V0.110.0：宏观因子手动校准 ─────────────────────

#: 手动校准覆盖的因子集合（与 ``services/macro.py::MACRO_FACTOR_RULES`` 的 key 一一对应）
MACRO_FACTOR_KEYS: tuple[str, ...] = ("dxy", "us10y", "us30y", "vix", "cb_gold")


class MacroFactorOverride(BaseModel):
    """单个宏观因子的手动读数覆盖。

    背景（V0.110.0）：``dxy`` / ``vix`` 没有实时源，长期使用 ``STATIC_REF`` 里
    2026-08-28 的硬编码值（96.5 / 18.5）。这两个因子在宏观面内部合计权重 0.40，
    宏观面又占综合指数 0.40 —— 相当于**综合指数的 16% 建立在两个半月前的常量上**。
    本模型允许用户从行情终端抄入当日真实读数临时顶替内置静态值。
    """

    value: float = Field(..., description="覆盖值（与因子单位一致：点位 / % / 吨每年）")
    as_of: date = Field(..., description="该读数对应的交易日；用于计算滞后天数")
    note: str | None = Field(None, max_length=120, description="备注（可选，如数据来源）")


class MacroFactorOverrideSet(BaseModel):
    """5 个宏观因子的手动覆盖集合；``None`` 表示该因子走自动数据源。"""

    dxy: MacroFactorOverride | None = None
    us10y: MacroFactorOverride | None = None
    us30y: MacroFactorOverride | None = None
    vix: MacroFactorOverride | None = None
    cb_gold: MacroFactorOverride | None = None

    def active(self) -> dict[str, MacroFactorOverride]:
        """返回已设置覆盖的因子（key → override），供 MacroFactorService 消费。"""
        return {
            key: getattr(self, key) for key in MACRO_FACTOR_KEYS if getattr(self, key, None) is not None
        }

    def is_empty(self) -> bool:
        return not self.active()
