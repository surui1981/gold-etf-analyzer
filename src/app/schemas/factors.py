"""宏观因子输入 Schema（Pydantic v2）。"""

from pydantic import BaseModel, Field, field_validator


class MacroFactorInput(BaseModel):
    """黄金定价的核心宏观因子输入。

    基于 PM-Evaluator 的预期评估架构：
    美元指数 / 美债收益率 / 实际利率 / 通胀预期 / 避险情绪。
    """

    dxy: float = Field(..., description="美元指数 DXY 点位", examples=[103.5])
    us10y_yield: float = Field(..., description="美债10年期收益率（%）", examples=[4.28])
    real_rate: float = Field(
        ...,
        description="实际利率（%），即 10Y 名义收益率 - 盈亏平衡通胀率",
        examples=[2.1],
    )
    inflation_expectation: float = Field(
        ...,
        description="通胀预期（%），即 10Y 盈亏平衡通胀率",
        examples=[2.6],
    )
    risk_off: int = Field(
        5,
        ge=0,
        le=10,
        description="避险情绪 0-10（0=贪婪，10=恐慌）",
        examples=[7],
    )

    @field_validator("dxy", "us10y_yield", "real_rate", "inflation_expectation")
    @classmethod
    def _non_negative(cls, value: float) -> float:
        """宏观指标不应为负数，防御脏数据。"""
        if value < 0:
            raise ValueError("宏观因子不能为负数")
        return value
