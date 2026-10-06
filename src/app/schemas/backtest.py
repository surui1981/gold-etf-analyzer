"""回测（V0.71.0）：参数扫描 + Sharpe / 最大回撤 / 校准曲线。

V0.79.0 Step G：新增 ``trend_weights`` / ``macro_weights`` 嵌套权重 + 上限 1000。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import ClassVar, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# V0.71.0：5 种标的共享回测基准（与前端 select 一致）
BacktestTarget = Literal["ny", "etf", "gram", "silver_ny", "silver_etf", "silver_gram"]

# V0.79.0 Step G：嵌套权重的字段名常量（与 ``weights.html`` ``TREND_FIELDS`` /
# ``MACRO_FIELDS`` 同步取值，前后端任何一处改名必须同步；测试 ``test_weight_grid_
# field_names_match_*`` 锁死此口径）。
TREND_DIM_FIELDS: tuple[str, ...] = ("结构", "动量", "支撑", "动能", "回撤")
MACRO_DIM_FIELDS: tuple[str, ...] = ("美元", "利率", "通胀", "地缘", "避险")


class NestedWeights(BaseModel):
    """嵌套权重候选（V0.79.0 Step G）。

    每个候选是 ``{字段名: 权重}`` 字典，必须**恰好覆盖**子类 ``_expected_fields``
    全部字段（不多不少）、且和 ``=1.0``（允许 1e-3 浮点误差）。子类通过覆盖
    ``_expected_fields`` 复用同一段 validator，不复制粘贴。
    """

    weights: list[dict[str, float]] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="权重候选列表（每个 dict 须覆盖且仅覆盖子类声明的字段，和≈1.0）",
    )
    # 子类覆盖：声明此 nested 必须覆盖的字段集合
    _expected_fields: ClassVar[tuple[str, ...]] = ()

    @field_validator("weights")
    @classmethod
    def _validate_weights(cls, value: list[dict[str, float]]) -> list[dict[str, float]]:
        fields = cls._expected_fields
        for j, w in enumerate(value):
            missing = set(fields) - set(w.keys())
            extra = set(w.keys()) - set(fields)
            if missing or extra:
                raise ValueError(
                    f"第 {j + 1} 项必须覆盖且仅覆盖 {fields}，缺 {sorted(missing) or '∅'},"
                    f" 多 {sorted(extra) or '∅'}"
                )
            s = sum(w.values())
            if not (0.999 <= s <= 1.001):
                raise ValueError(f"第 {j + 1} 项权重和必须为 1.0，实际 {s:.4f}")
            if any(v < 0 or v > 1 for v in w.values()):
                raise ValueError(f"第 {j + 1} 项权重必须在 [0, 1] 范围内")
        return [{k: round(v, 4) for k, v in w.items()} for w in value]


class TrendWeights(NestedWeights):
    """技术面 5 维度内部权重候选（结构 / 动量 / 支撑 / 动能 / 回撤）。"""

    _expected_fields: ClassVar[tuple[str, ...]] = TREND_DIM_FIELDS


class MacroWeights(NestedWeights):
    """宏观面 5 因子内部权重候选（美元 / 利率 / 通胀 / 地缘 / 避险）。"""

    _expected_fields: ClassVar[tuple[str, ...]] = MACRO_DIM_FIELDS


class WeightGrid(BaseModel):
    """权重扫描网格。

    V0.71.0：3 维扁平（tech / macro / news 各为标量候选列表）。
    V0.79.0 Step G：增 ``trend_weights`` / ``macro_weights`` 嵌套，使回测可扫
    「技术面 5 维度内部权重」与「宏观 5 因子内部权重」。嵌套为可选（None = 旧行为），
    默认走 ``tech_index`` / ``macro_index`` 扁平分（向后兼容）。
    """

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
    trend_weights: TrendWeights | None = Field(
        None,
        description="技术面 5 维度内部权重候选（V0.79.0 Step G；None = 用 tech_index 扁平）",
    )
    macro_weights: MacroWeights | None = Field(
        None,
        description="宏观 5 因子内部权重候选（V0.79.0 Step G；None = 用 macro_index 扁平）",
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
        """网格组合数 = tech×macro×news×bullish×bearish×(trend_5 or 1)×(macro_5 or 1)。

        V0.79.0 Step G：上限 125 → 1000。125 是 V0.71.0 的扁平 5×5×5 边界；
        1000 是包含 7 维笛卡尔积的新边界（默认 3×1×1 × 4×4 × 1×1 = 48，
        引入 trend_5/macro_5 后留 20× 余量供嵌套扫描使用）。
        """
        wg = self.weight_grid
        n = (
            len(wg.tech)
            * len(wg.macro)
            * len(wg.news)
            * len(self.threshold_bands.bullish)
            * len(self.threshold_bands.bearish)
            * len(wg.trend_weights.weights if wg.trend_weights else [None])
            * len(wg.macro_weights.weights if wg.macro_weights else [None])
        )
        if n > 1000:
            raise ValueError(
                f"权重网格组合 {n} 超过上限 1000，请缩减候选数"
                f"（tech={len(wg.tech)}, macro={len(wg.macro)}, news={len(wg.news)},"
                f" trend_5={len(wg.trend_weights.weights) if wg.trend_weights else 0},"
                f" macro_5={len(wg.macro_weights.weights) if wg.macro_weights else 0}）"
            )
        return self


class BacktestGridRow(BaseModel):
    """单组参数组合的回测结果。

    V0.79.0 Step G：增 ``tech_dim_weights`` / ``macro_dim_weights`` 两字段。
    当本次请求**未启用嵌套**时两字段为 None（向后兼容，扁平回测结果保持原形状）。
    启用嵌套时为 `{字段: 权重}` 字典 —— 让 UI 能在「胜出组合」上展示其权重分布。
    """

    tech_w: float
    macro_w: float
    news_w: float
    bullish_threshold: float
    bearish_threshold: float
    sharpe: float
    max_drawdown_pct: float
    win_rate: float = Field(..., ge=0, le=1, description="命中率 0-1")
    samples: int = Field(..., ge=0, description="样本天数")
    tech_dim_weights: dict[str, float] | None = Field(
        None,
        description="技术面 5 维度内部权重（V0.79.0 Step G；None = 用扁平 tech_index）",
    )
    macro_dim_weights: dict[str, float] | None = Field(
        None,
        description="宏观 5 因子内部权重（V0.79.0 Step G；None = 用扁平 macro_index）",
    )


class BacktestSummary(BaseModel):
    """回测整体汇总。

    ⚠ ``usable=False`` 表示本汇总是**填充值而非回测结论**（继承
    ``coverage.usable``）。此时 ``best_sharpe=0.0`` 与偏高的 ``avg_win_rate``
    都源于「T+1 收益全为 0」，**不可解读为「策略表现差」**。
    取保守侧默认 ``False``：``_aggregate()`` 单独调用时无从判断数据是否可用。
    """

    total_rows: int
    best_sharpe: float
    worst_sharpe: float
    avg_sharpe: float
    best_max_drawdown: float = Field(..., description="最小最大回撤 %（越低越好）")
    avg_win_rate: float
    usable: bool = Field(False, description="继承 coverage.usable；False = 填充值非结论")


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
    """回测数据覆盖期（V0.71.0 必填：明示样本窗口与可用天数）。

    V0.79.0（Step G 前置修复）：增价格日历维度。
    ⚠ **回测需要两类数据，缺一不可**：
      ① ``daily_snapshots`` —— 每日评估分（决定「有哪些日子可评」）；
      ② ``gold_price_daily`` —— 收盘价日历（决定「每日的对错如何判定」）。
    此前只披露 ①，而 ② 由 ``/review`` 页手工复盘才写入 ⇒ ② 为空时回测照常返回
    ``best_sharpe=0.0`` 与虚高命中率，且 ``sample_warning`` 为 ``False``（因为它只看
    快照天数）。**这是静默假结果** —— 用户无法从返回值分辨「回测无效」与「回测有效但
    表现差」。故新增 ``price_calendar_days`` / ``returns_available_days`` /
    ``returns_missing_days`` / ``usable`` 四个字段显式披露。
    """

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
    price_calendar_days: int = Field(
        0,
        ge=0,
        description="价格日历覆盖天数（gold_price_daily 落在覆盖期内的交易日数）",
    )
    returns_available_days: int = Field(
        0,
        ge=0,
        description="可算出 T+1 涨跌幅的样本天数（真正参与 Sharpe / 命中率计算）",
    )
    returns_missing_days: int = Field(
        0,
        ge=0,
        description="因缺后继交易日价格而无法判定对错的天数",
    )
    usable: bool = Field(
        False,
        description=(
            "回测结果是否可用于决策。为 False 时 rows 里的 sharpe / win_rate 是"
            "**填充值而非实测值**，页面必须显式提示，不得当作回测结论展示。"
            "⚠ **默认 False（保守侧）**：拿不到数据时不能宣称结果可用 —— "
            "默认 True 会让任何遗漏该字段的旧构造方式静默变成「假结果可用」"
        ),
    )


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


# ─────────────── V0.79.0 Step G · 异步回测接口 ───────────────


class BacktestTaskAcceptedOut(BaseModel):
    """``POST /api/v1/backtest/run-async`` 202 Accepted 响应。

    立即返回，客户端随后轮询 ``poll_url`` 获取结果。
    """

    task_id: str = Field(..., description="任务 ID（uuid4 hex，32 字符）")
    status: Literal["pending"] = "pending"
    poll_url: str = Field(..., description="轮询 GET 端点路径（相对 /api/v1）")
    accepted_at: datetime


class BacktestTaskResultOut(BaseModel):
    """``GET /api/v1/backtest/result/{task_id}`` 响应。

    状态机：
      - ``pending`` / ``running`` → ``result`` 为 None
      - ``completed`` → ``result`` 是完整 ``BacktestResultOut``（model_dump 形态）
      - ``failed`` → ``error`` 字符串非空，``result`` 为 None

    ``progress`` 字段在 V0.79.0 Step G 接口预留（恒 None），实际进度上报逻辑
    留 V0.79.1 维护线 —— 当前实现同步计算、一次性 complete。
    """

    task_id: str
    status: Literal["pending", "running", "completed", "failed"]
    accepted_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: float | None = None
    error: str | None = None
    result: BacktestResultOut | None = None
