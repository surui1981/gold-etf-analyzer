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
    # ── 扇形形状（前端「形状对照图」要画的两条线）──
    # shape = 离线校准出的类比形状（k=horizon 归一为 1.0）；cone = 对数正态 √k 锥。
    # ⚠ shape 缺失时为空数组 ⇒ 前端只画 √k 锥并显示「形状产物缺失」，
    #   **不拿锥冒充类比形状**。
    shape: list[float] = Field(default_factory=list, description="类比形状曲线（k=1..horizon）")
    cone: list[float] = Field(default_factory=list, description="对数正态 √k 锥（退化基线）")
    # ── 跨窗口形状稳定性（V0.127.1 加）──
    # 同一算法在**另两个窗口**（近 600 段 / 训练段）上的形状曲线。
    # ⚠ 这块只作「已知失效条件」的证据，**不参与**线上扇形计算。
    # ⚠ 页面上的跨窗口倍数必须**现算**（shape ÷ cone），不要写死
    #   —— 产物重算后写死的数字会静默变假话（V0.127.1 教训）。
    # ⚠ 缺失 ⇒ 空字典 ⇒ 页面降级为「不含具体数字的表述」。
    shape_stability: dict = Field(
        default_factory=dict,
        description="跨窗口形状稳定性：{窗口名: {n_days: 样本天数, shape: [float, ...]}}",
    )


# ────────────────────────────── V0.128.0 经济危机金价拟合曲线 ──────────────────────────────
# ⚠ 这是「历史形态参照 + 情景假设」，**不是预测、不是统计回归、不是目标价**。
#   任何「看多/看空/预计金价」语义都不该出现在这套 schema 里。


class CrisisFitPointOut(BaseModel):
    """拟合曲线上的一个月。"""

    model_config = ConfigDict(from_attributes=True)

    t: int = Field(description="距锚点月的月数（锚点 = 0）")
    month: str = Field(description="日历月 YYYY-MM")
    norm: float = Field(description="归一指数（锚点月的月均价 = 100）")
    price: float = Field(description="隐含美元价（锚点月均价 × norm / 100）")


class CrisisCycleEndOut(BaseModel):
    """单轮历史周期各自外推到终点的结果（= 离散区间）。"""

    model_config = ConfigDict(from_attributes=True)

    name: str
    norm: float
    price: float


class CrisisFitSensitivityOut(BaseModel):
    """锚点敏感性（证据门 E5）：锚点月 ±1 时终点的隐含价。"""

    model_config = ConfigDict(from_attributes=True)

    anchor_minus1_price: float | None = None
    anchor_plus1_price: float | None = None
    low: float | None = None
    high: float | None = None
    spread_pct: float | None = Field(default=None, description="锚点 ±1 月造成的终点相对波动（%）")


class CrisisFitOut(BaseModel):
    """经济危机金价拟合曲线的接口响应。"""

    model_config = ConfigDict(from_attributes=True)

    target: str
    available: bool = Field(
        description="是否算出了曲线（false ⇒ 页面显示「样本不足」并写明 reason）"
    )
    reason: str | None = Field(default=None, description="降级原因（如 no_crisis_cycles_artifact）")
    horizon_months: int
    drift: float = Field(description="每月漂移假设（研究示意参数；页面必须同时给出 drift=0 对照）")

    # ── 当前周期定位 ──
    anchor_month: str | None = Field(default=None, description="锚点月（默认 = 月均价最高的月）")
    anchor_avg: float | None = None
    peak_date: str | None = Field(default=None, description="锚点对应的日线峰值日期")
    peak_price: float | None = None
    last_month: str | None = None
    last_avg: float | None = None
    t0: int | None = Field(default=None, description="锚点月 → 末月的月数")
    cur_norm: float | None = Field(default=None, description="当前周期的归一位置（锚点 = 100）")

    # ── 曲线 ──
    template: list[list[float]] = Field(
        default_factory=list, description="等权平均模板 [[t, norm], ...]（形态参照的本体）"
    )
    template_counts: list[int] = Field(
        default_factory=list, description="每个 t 由几轮周期平均而来（尾部轮数少 ⇒ 证据薄）"
    )
    template_max_t: int | None = Field(
        default=None, description="模板覆盖的最大 t（超过它就是**平台外推**，没有历史信息）"
    )
    cycle_paths: list[dict] = Field(
        default_factory=list,
        description="**拟合集**每轮周期各自的归一路径（模板的原料；页面要展示「均值是由什么平均出来的」）",
    )
    reference_paths: list[dict] = Field(
        default_factory=list,
        description="**参照集**（拟合窗口之前的更早周期）的归一路径 —— 只展示，**不进模板**",
    )
    support_at_horizon: int | None = Field(
        default=None,
        description="外推终点处由几轮周期支撑（少 ⇒ 长程外推几乎等于「某一轮怎么走」，页面必须标出）",
    )
    fit_window: dict = Field(default_factory=dict, description="拟合窗口（哪段历史参与等权平均）")
    reference_window: dict = Field(
        default_factory=dict, description="参照窗口（哪段历史只作展示、不进拟合）"
    )
    curve: list[CrisisFitPointOut] = Field(default_factory=list)
    endpoint: CrisisFitPointOut | None = None
    endpoint_drift0: CrisisFitPointOut | None = Field(
        default=None, description="★ drift=0 的同一终点（页面常驻对照 —— drift 是假设不是结论）"
    )
    gain_pct: float | None = None
    cycle_ends: list[CrisisCycleEndOut] = Field(
        default_factory=list, description="单轮周期各自的终点（= 离散区间）"
    )
    sensitivity: CrisisFitSensitivityOut | None = Field(
        default=None, description="锚点 ±1 月的终点敏感度"
    )

    # ── 证据与告警 ──
    provenance: dict = Field(
        default_factory=dict, description="周期数据的来源（来源/覆盖区间/口径）"
    )
    warnings: list[str] = Field(default_factory=list, description="被剔除的周期与原因")
    generated_at: str | None = None
