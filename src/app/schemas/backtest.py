"""回测（V0.71.0）：参数扫描 + Sharpe / 最大回撤 / 校准曲线。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# V0.71.0：5 种标的共享回测基准（与前端 select 一致）
BacktestTarget = Literal["ny", "etf", "gram", "silver_ny", "silver_etf", "silver_gram"]


class WeightGrid(BaseModel):
    """权重扫描网格（3 维：tech / macro / news）。"""

    tech: list[float] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="技术面权重候选列表（如 [0.3, 0.4, 0.5]）",
    )
    macro: list[float] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="宏观面权重候选列表",
    )
    news: list[float] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="消息面权重候选列表",
    )

    @field_validator("tech", "macro", "news")
    @classmethod
    def _round(cls, value: list[float]) -> list[float]:
        if any(v < 0 or v > 1 for v in value):
            raise ValueError("权重候选必须在 [0, 1] 范围内")
        return [round(v, 4) for v in value]


class ThresholdBand(BaseModel):
    """方向判定阈值带（看多 / 看空 阈值各 4 节点）。"""

    bullish: list[float] = Field(
        default_factory=lambda: [55, 60, 65, 70],
        description="看多阈值候选（综合分 ≥ 此值判 BULLISH）",
    )
    bearish: list[float] = Field(
        default_factory=lambda: [45, 40, 35, 30],
        description="看空阈值候选（综合分 ≤ 此值判 BEARISH）",
    )

    @field_validator("bullish", "bearish")
    @classmethod
    def _check_range(cls, value: list[float]) -> list[float]:
        if any(v < 0 or v > 100 for v in value):
            raise ValueError("阈值必须在 [0, 100] 范围内")
        return [round(v, 2) for v in value]


class BacktestRequestIn(BaseModel):
    """回测请求：基准标的 + 回看窗口 + 权重网格 + 阈值带。"""

    days: int = Field(
        90,
        ge=20,
        le=365,
        description="回看窗口（交易日数，默认 90；上限 365）",
    )
    target: BacktestTarget = Field(
        "etf",
        description="基准标的：ny / etf / gram / silver_ny / silver_etf / silver_gram",
    )
    weight_grid: WeightGrid = Field(
        default_factory=lambda: WeightGrid(tech=[0.3, 0.4, 0.5], macro=[0.4], news=[0.3]),
        description="3 维权重扫描网格（默认 27 组合）",
    )
    threshold_bands: ThresholdBand = Field(
        default_factory=ThresholdBand,
        description="方向判定阈值带（bullish / bearish 各 4 节点）",
    )

    @model_validator(mode="after")
    def _check_grid_size(self) -> BacktestRequestIn:
        """网格组合数 = tech×macro×news；超过 125 警告并截断（前端 UI 性能边界）。"""
        n = len(self.weight_grid.tech) * len(self.weight_grid.macro) * len(self.weight_grid.news)
        if n > 125:
            raise ValueError(
                f"权重网格组合 {n} 超过 UI 性能上限 125（5×5×5），请缩减候选数"
            )
        return self


class BacktestGridRow(BaseModel):
    """单组参数组合的回测结果。"""

    tech_w: float
    macro_w: float
    news_w: float
    bullish_threshold: float
    bearish_threshold: float
    sharpe: float
    max_drawdown_pct: float
    win_rate: float = Field(..., ge=0, le=1, description="命中率 0-1")
    samples: int = Field(..., ge=0, description="样本天数")


class BacktestSummary(BaseModel):
    """回测整体汇总。"""

    total_rows: int
    best_sharpe: float
    worst_sharpe: float
    avg_sharpe: float
    best_max_drawdown: float = Field(..., description="最小最大回撤 %（越低越好）")
    avg_win_rate: float


class BacktestResultOut(BaseModel):
    """回测完整输出。"""

    target: BacktestTarget
    days: int
    coverage: BacktestCoverageOut
    rows: list[BacktestGridRow]
    summary: BacktestSummary
    cached: bool = Field(False, description="是否命中 5 分钟节流缓存")
    cached_age_seconds: int = Field(0, description="缓存命中时距存储已过秒数")


class BacktestCoverageOut(BaseModel):
    """回测数据覆盖期（V0.71.0 必填：明示样本窗口与可用天数）。"""

    target: BacktestTarget
    start_date: date | None
    end_date: date | None
    available_days: int = Field(..., ge=0, description="实际可用样本天数")
    available_window_trading_days: int = Field(
        ...,
        ge=0,
        description="有效交易样本天数（tech_index 非空）",
    )
    note: str = Field("", description="数据覆盖期备注（不足时提示）")
    sample_warning: bool = Field(False, description="样本 < 20 时为 True")


class BacktestConfigIn(BaseModel):
    """回测前端配置（持久化到 settings 表）。"""

    days: int = Field(90, ge=20, le=365)
    target: BacktestTarget = "etf"
    weight_grid: WeightGrid = Field(
        default_factory=lambda: WeightGrid(tech=[0.3, 0.4, 0.5], macro=[0.4], news=[0.3]),
    )
    threshold_bands: ThresholdBand = Field(default_factory=ThresholdBand)


class BacktestConfigOut(BacktestConfigIn):
    """回测配置输出（含保存时间）。"""

    updated_at: datetime | None = None