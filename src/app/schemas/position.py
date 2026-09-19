"""交易面 Schema：开仓/持仓视图/流水/操作请求。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.market import TrendIndexOut


class PositionCreate(BaseModel):
    """开仓请求。

    V0.70.0（P2 #8）起支持按「克」开仓（实物金 / 积存金业务）：
    ``grams`` 与 ``quantity`` **二选一**（互斥）——按克时由服务端按当前克价折算
    份数后落库。
    """

    symbol: str = Field("518880", description="品种代码，默认 518880 华安黄金ETF")
    quantity: float | None = Field(None, gt=0, le=1e9, description="买入数量（份），需大于 0；与 grams 二选一")
    grams: float | None = Field(None, gt=0, le=1e6, description="买入克数（g），需大于 0；与 quantity 二选一（V0.70.0 P2 #8）")
    price: float = Field(..., gt=0, le=1e6, description="成交价（元/份），需大于 0")
    fee: float = Field(0, ge=0, le=1e6, description="手续费（元），需大于等于 0")

    @field_validator("quantity", "price", "fee", "grams")
    @classmethod
    def _round(cls, value: float | None) -> float | None:
        if value is None:
            return value
        return round(value, 4)

    @model_validator(mode="after")
    def _xor_grams(self) -> "PositionCreate":
        # 二选一互斥（两个都填 / 都不填 均报错）
        has_q = self.quantity is not None
        has_g = self.grams is not None
        if has_q == has_g:  # 都是 True 或都是 False
            raise ValueError("quantity 与 grams 必须二选一（不可同时填写，也不可同时省略）")
        return self


class TradeRequest(BaseModel):
    """加仓/减仓请求。

    V0.70.0（P2 #8）起支持按「克」加减仓：``grams`` 与 ``quantity`` **二选一**。
    """

    side: str = Field(..., description="buy 加仓 / sell 减仓")
    quantity: float | None = Field(None, gt=0, le=1e9, description="数量（份），需大于 0；与 grams 二选一")
    grams: float | None = Field(None, gt=0, le=1e6, description="克数（g），需大于 0；与 quantity 二选一（V0.70.0 P2 #8）")
    price: float = Field(..., gt=0, le=1e6, description="成交价（元/份），需大于 0")
    fee: float = Field(0, ge=0, le=1e6, description="手续费（元），需大于等于 0")

    @field_validator("side")
    @classmethod
    def _validate_side(cls, value: str) -> str:
        if value not in {"buy", "sell"}:
            raise ValueError("side 必须为 buy 或 sell")
        return value

    @field_validator("quantity", "price", "fee", "grams")
    @classmethod
    def _round(cls, value: float | None) -> float | None:
        if value is None:
            return value
        return round(value, 4)

    @model_validator(mode="after")
    def _xor_grams(self) -> "TradeRequest":
        has_q = self.quantity is not None
        has_g = self.grams is not None
        if has_q == has_g:
            raise ValueError("quantity 与 grams 必须二选一（不可同时填写，也不可同时省略）")
        return self


class PositionOut(BaseModel):
    """持仓视图（含实时市值盈亏）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int = Field(1, description="所属账本 ID（单用户多账本，P1 #6）")
    symbol: str
    name: str
    quantity: float
    avg_cost: float
    grams_held: float | None = Field(None, description="当前持仓克数（g，可空；V0.70.0 P2 #8）")
    status: str
    opened_at: datetime
    # 实时估值（由服务层补充）
    market_price: float = Field(0, description="最新价")
    market_value: float = Field(0, description="持仓市值 = 数量×最新价")
    pnl: float = Field(0, description="浮动盈亏（元）")
    pnl_pct: float = Field(0, description="收益率 %（相对成本）")


class TradeRecordOut(BaseModel):
    """交易流水输出。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    position_id: int
    side: str
    quantity: float
    price: float
    fee: float
    traded_at: datetime


class PositionDeleteOut(BaseModel):
    """软删除/撤销结果。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    deleted: bool = Field(..., description="true=已软删除；false=已撤销恢复")
    deleted_at: datetime | None = None


class PositionSummary(BaseModel):
    """持仓摘要（供决策引擎）。"""

    has_position: bool = False
    quantity: float = 0
    avg_cost: float = 0
    pnl_pct: float = 0
    pnl: float = 0
    position_ratio: float = Field(0, description="仓位占用比例 0-1（估算）")
    grams_held: float | None = Field(
        None,
        description="汇总克数（g）；仅当全部持仓都按克开仓时有值（V0.70.0 P2 #8）",
    )


class ReasonItem(BaseModel):
    """决策理由明细项：文字 + 方向（利多/利空/中性），供前端红绿着色对照展示。"""

    text: str = Field(..., description="理由文字（面向客户）")
    direction: str = Field("neutral", description="bullish 利多 / bearish 利空 / neutral 中性")


class DecisionOut(BaseModel):
    """购买决策输出：行动 + 置信度 + 仓位推荐 + 理由明细。"""

    action: str = Field(..., description="BUY/ADD/HOLD/REDUCE/SELL/WAIT")
    action_label: str = Field(..., description="中文行动名")
    confidence: str = Field(..., description="high/medium/low")
    signal_summary: str = Field(..., description="参数面信号摘要")
    trend_index: TrendIndexOut = Field(..., description="当前趋势评估指数")
    position: PositionSummary = Field(..., description="当前持仓摘要")
    suggested_position: float = Field(
        ..., ge=0, le=100, description="建议黄金仓位比例 0-100%（由评估指数映射）"
    )
    position_level: str = Field(..., description="仓位等级：重仓/中高仓位/中性仓位/轻仓/观望空仓")
    reasons: list[str] = Field(..., description="决策理由明细（纯文本，向后兼容）")
    reason_items: list[ReasonItem] = Field(
        default_factory=list, description="决策理由明细（结构化：含利多/利空方向，供红绿对照条）"
    )
    summary: str = Field(..., description="决策总结")
