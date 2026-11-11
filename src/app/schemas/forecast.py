"""金价区间预测 Schema（V0.127.0）。

⚠ **这个接口回答的是「未来 N 个交易日的金价大致在什么区间」，不是「涨还是跌」。**
中心恒等于最新收盘价（``drift_mode="none"``）。

⚠ **实测覆盖率必须与名义覆盖率一起返回**
名义 80% 的带子实测只覆盖 79.2%（样本外）⇒ 前端要显示**实测值**，
不能只显示名义值（否则用户在拿一个偏乐观的数当承诺）。

⚠ 所有面向用户的文案走**代码**（``reason`` / ``cross_check.status``），
不在服务端硬编码中文 —— 渲染交给前端的 i18n 字典（3 语）。
"""

from datetime import date as _Date
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ForecastPointOut(BaseModel):
    """扇形上的一点（k 个交易日后的上下沿）。"""

    model_config = ConfigDict(from_attributes=True)

    k: int = Field(..., description="第 k 个交易日（1 起）")
    date: _Date = Field(..., description="该交易日的日历日期（按工作日外推，不含假日修正）")
    lower: float = Field(..., description="区间下沿（美元/盎司）")
    upper: float = Field(..., description="区间上沿（美元/盎司）")


class ForecastMeasuredOut(BaseModel):
    """实测覆盖率（**不是**名义覆盖率）。"""

    model_config = ConfigDict(from_attributes=True)

    nominal: float = Field(..., description="名义覆盖率（如 0.8）")
    train: float | None = Field(None, description="训练段实测覆盖率")
    out_of_sample: float | None = Field(None, description="样本外实测覆盖率（**主口径**）")
    recent: float | None = Field(None, description="近段实测覆盖率")
    source: str = Field("", description="主口径取自哪个 span")
    n_out_of_sample: int | None = Field(None, description="样本外样本量")


class ForecastCrossCheckOut(BaseModel):
    """两法交叉校验（EWMA 宽度 vs 历史类比宽度）。"""

    model_config = ConfigDict(from_attributes=True)

    status: str | None = Field(
        None,
        description=(
            "None=一致；analog_unusually_wide=类比带异常宽（已取更宽的一条）；"
            "analog_unusually_narrow=类比带异常窄（仍用 EWMA，更宽）；"
            "disagree=没有实测分布时的兜底判据"
        ),
    )
    ratio: float | None = Field(None, description="类比带半宽 ÷ EWMA 带半宽")
    normal_band: list[float] | None = Field(
        None, description="比值的实测正常区间 [p05, p95]（判据用这个，不是「两法相等」）"
    )
    ewma_half_width: float | None = Field(None, description="EWMA 带半宽（对数空间）")
    analog_half_width: float | None = Field(None, description="类比带半宽（对数空间）")
    analog_n_sim: int | None = Field(None, description="参与类比的相似日数量")


class PriceForecastOut(BaseModel):
    """一条金价区间预测。"""

    model_config = ConfigDict(from_attributes=True)

    target: str = Field(..., description="标的（ny=COMEX 纽约金）")
    base_date: _Date = Field(..., description="基准日（价格日历里最新的一行）")
    base_close: float = Field(..., description="基准收盘价（区间中心就是它）")
    horizon: int = Field(..., description="期限（交易日）")
    coverage: float = Field(..., description="名义覆盖率")
    z: float = Field(..., description="该覆盖率对应的正态分位")
    sigma: float = Field(..., description="日波动率（EWMA λ=0.94）")
    sigma_annual: float = Field(..., description="年化波动率（%）")
    method: str = Field(
        ...,
        description=(
            "ewma_shape=EWMA 定宽 + 类比定形；ewma_widened=交叉校验后取更宽的一条；"
            "vol_only=只有波动率模型（退化）"
        ),
    )
    drift_mode: str = Field("none", description="中心漂移方式（恒为 none = 不做方向预测）")
    shape_source: str = Field("cone", description="形状来源：analog=类比形状；cone=对数正态 √k 锥")
    lower: float = Field(..., description="horizon 处的区间下沿")
    upper: float = Field(..., description="horizon 处的区间上沿")
    points: list[ForecastPointOut] = Field(..., description="扇形路径（长度 = horizon）")
    measured: ForecastMeasuredOut = Field(..., description="实测覆盖率")
    cross_check: ForecastCrossCheckOut = Field(..., description="两法交叉校验")
    reason: str | None = Field(
        None,
        description="降级原因代码：insufficient_analogs=相似日不足；no_shape_artifact=没有形状产物",
    )
    n_bars: int = Field(0, description="参与计算的历史行数")
    first_date: _Date | None = Field(None, description="历史区间起点")
    min_sim: int = Field(30, description="相似日数量下限（降级判据用）")
    generated_at: datetime = Field(..., description="生成时刻（UTC）")


class ForecastCalibrationOut(BaseModel):
    """校准产物（供新页展示「这个区间历史上准不准」）。"""

    model_config = ConfigDict(from_attributes=True)

    target: str
    horizon: int
    generated_at: str | None = None
    method: str | None = None
    source: dict = Field(default_factory=dict)
    params: dict = Field(default_factory=dict)
    spans: dict = Field(default_factory=dict)
    coverages: dict = Field(default_factory=dict)
    cross_check: dict = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    available: bool = Field(True, description="产物是否存在（false ⇒ 页面显示「未校准」）")
