"""行情相关 Schema：报价 + K线 + 趋势追踪 + 趋势评估指数。"""

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.schemas.common import DirectionSignal


class GoldQuoteOut(BaseModel):
    """黄金现货报价输出。"""

    symbol: str
    price_usd: float = Field(..., gt=0)
    change_pct: float = Field(..., description="涨跌幅 %")
    updated_at: datetime


class GoldKlinePoint(BaseModel):
    """单日 K 线（数据源无关，用于接口与页面消费）。"""

    date: date
    open: float
    close: float
    high: float
    low: float
    volume: float = Field(0, description="成交量（手）")


class TrendDirection(StrEnum):
    """趋势方向判定。"""

    UP = "up"  # 上升趋势
    DOWN = "down"  # 下降趋势
    SIDEWAYS = "sideways"  # 震荡


class GoldTrendPoint(BaseModel):
    """趋势序列点：收盘价 + 移动均线。"""

    date: date
    close: float
    ma5: float | None = Field(None, description="5 日均线")
    ma20: float | None = Field(None, description="20 日均线")
    ma40: float | None = Field(None, description="40 日均线")


class GoldTrendMetrics(BaseModel):
    """2 个月趋势指标摘要。"""

    start_date: date
    end_date: date
    trading_days: int = Field(..., description="交易日数量")
    start_price: float
    end_price: float
    change_pct: float = Field(..., description="区间涨跌幅 %")
    high: float = Field(..., description="区间最高价")
    low: float = Field(..., description="区间最低价")
    ma20: float | None = Field(None, description="最新 20 日均线")
    ma40: float | None = Field(None, description="最新 40 日均线")
    direction: TrendDirection
    summary: str


class TrendIndexLevel(StrEnum):
    """市场趋势评估指数等级。"""

    STRONG_UP = "strong_up"  # 强势上升
    UP = "up"  # 上升
    SIDEWAYS = "sideways"  # 震荡
    DOWN = "down"  # 下降
    STRONG_DOWN = "strong_down"  # 弱势下降


class TrendIndicatorOut(BaseModel):
    """单维度趋势参数：分数 + 方向 + 贡献，供页面红绿着色。"""

    name: str = Field(..., description="参数名，如 均线排列")
    value: str = Field(..., description="参数当前值（文本）")
    score: float = Field(..., ge=0, le=100, description="该维度 0-100 评分")
    direction: DirectionSignal = Field(..., description="利多/利空/中性")
    weight: float = Field(..., ge=0, le=1, description="权重")
    contribution: float = Field(..., ge=0, le=100, description="对指数的贡献 = score×weight")
    detail: str = Field(..., description="判定依据")


class TrendIndexOut(BaseModel):
    """市场趋势评估追踪指数（加权合成）。"""

    score: float = Field(..., ge=0, le=100, description="趋势指数 0-100")
    level: TrendIndexLevel
    direction: DirectionSignal
    summary: str


class MacroFactorOut(BaseModel):
    """单宏观因子：当前值 + 黄金友好度评分 + 方向。"""

    key: str = Field(..., description="因子标识 dxy/us10y/us30y/vix/cb_gold")
    name: str
    value: str = Field(..., description="当前值（文本）")
    unit: str
    data_date: str = Field(..., description="数据日期（实时或静态标注）")
    score: float = Field(..., ge=0, le=100, description="黄金友好度 0-100")
    direction: DirectionSignal
    weight: float = Field(..., ge=0, le=1)
    contribution: float = Field(..., ge=0, le=100)
    detail: str


class MacroIndexOut(BaseModel):
    """宏观参考指数（5 因子加权合成）。"""

    score: float = Field(..., ge=0, le=100, description="宏观参考指数 0-100")
    direction: DirectionSignal
    factors: list[MacroFactorOut] = Field(..., description="宏观因子明细")
    summary: str


class GoldTrendOut(BaseModel):
    """黄金趋势追踪输出：序列 + 指标 + 参数 + 追踪指数 + 宏观参考。"""

    symbol: str
    name: str = Field(..., description="品种名称")
    days: int = Field(..., description="覆盖交易日数")
    points: list[GoldTrendPoint]
    metrics: GoldTrendMetrics
    indicators: list[TrendIndicatorOut] = Field(..., description="趋势参数明细（技术面）")
    index: TrendIndexOut = Field(..., description="市场趋势评估追踪指数（综合）")
    macro: MacroIndexOut = Field(..., description="宏观参考指数（美元指数/美债/VIX/央行购金）")


class GoldCompareSeries(BaseModel):
    """对照序列完整指标（单标的）。"""

    symbol: str
    name: str
    start_price: float = Field(..., description="区间起始价")
    end_price: float = Field(..., description="区间结束价（最新价）")
    change_pct: float = Field(..., description="区间涨跌幅 %")
    high: float = Field(..., description="区间最高价")
    low: float = Field(..., description="区间最低价")
    ma20: float | None = Field(None, description="最新 20 日均线")
    ma40: float | None = Field(None, description="最新 40 日均线")
    direction: TrendDirection = Field(..., description="区间方向 up/down/sideways")


class GoldComparePoint(BaseModel):
    """对照点：ETF 与克价均归一化（区间起点 = 100）。"""

    date: date
    etf: float = Field(..., description="ETF 归一化值")
    gram: float = Field(..., description="黄金克价归一化值")


class GoldCompareOut(BaseModel):
    """黄金ETF vs 黄金克价对照输出。"""

    days: int = Field(..., description="对齐后的交易日数")
    etf: GoldCompareSeries
    gram: GoldCompareSeries
    points: list[GoldComparePoint] = Field(..., description="归一化对照序列")
    leader: str = Field(..., description="区间表现领先者 etf/gram/tie")
    lead_gap: float = Field(..., description="涨跌幅差（百分点）")
    summary: str
