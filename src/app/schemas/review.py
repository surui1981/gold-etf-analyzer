"""研判复盘 Schema（V0.66.0）。

回答三个问题：

1. **按日期归档**：每天的研判依据、备注、打分明细（``JournalDayOut``）；
2. **对比结果**：当日研判之后第 1/3/5 个交易日的金价涨跌与命中与否（``OutcomeOut``）；
3. **准确率**：整体命中率、按方向分组、分值分箱校准、依据标签胜率（``ReviewStatsOut``）。
"""

from datetime import date as DateType
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.review import DEFAULT_REVIEW_TARGET, NEUTRAL_BAND_PCT, REVIEW_HORIZONS
from app.schemas.common import DirectionSignal

# 预置研判依据标签：覆盖黄金定价的主要驱动，便于统计「哪类依据更可靠」。
# 前端多选渲染，服务端做白名单外的宽松接受（允许自定义补充）。
BASIS_TAGS: tuple[str, ...] = (
    "美元指数",
    "美债收益率",
    "实际利率",
    "通胀预期",
    "美联储政策",
    "央行购金",
    "地缘风险",
    "避险情绪",
    "ETF资金流",
    "人民币汇率",
    "技术面",
    "投行观点",
)


class ReviewMetaOut(BaseModel):
    """复盘页配置元信息（前端据此渲染选择器与标签多选）。"""

    target: str = DEFAULT_REVIEW_TARGET
    targets: list[dict] = Field(
        default_factory=list, description="可选基准标的 [{key,label}]"
    )
    horizons: list[int] = Field(default_factory=lambda: list(REVIEW_HORIZONS))
    basis_tags: list[str] = Field(default_factory=lambda: list(BASIS_TAGS))
    neutral_band_pct: float = NEUTRAL_BAND_PCT
    price_days: int = Field(0, description="已积累的交易日数量")
    latest_price_date: DateType | None = Field(None, description="最新价格日期")
    latest_price: float | None = Field(None, description="最新收盘价")


class BackfillOut(BaseModel):
    """价格回填结果。"""

    target: str
    requested_days: int
    written: int = Field(..., description="写入（新增 + 更新）条数")
    price_days: int = Field(..., description="回填后累计交易日数量")
    start_date: DateType | None = None
    end_date: DateType | None = None
    source: str = ""


class OutcomeOut(BaseModel):
    """单个窗口的对比结果（当日研判 → 之后第 N 个交易日）。"""

    horizon: int = Field(..., description="交易日跨度：1/3/5")
    date: DateType | None = Field(None, description="第 N 个交易日的日期")
    close: float | None = Field(None, description="该日收盘价")
    change_pct: float | None = Field(None, description="相对研判日的涨跌幅 %")
    hit: bool | None = Field(None, description="是否命中；None 表示尚待验证")
    status: str = Field("pending", description="hit / miss / flat / pending")
    label: str = Field("", description="结果可读说明")


class JournalSlotOut(BaseModel):
    """复盘卡片中的单次打分明细。"""

    slot: int
    score: float
    direction: DirectionSignal
    notes: str = ""
    basis: list[str] = Field(default_factory=list)
    review_note: str = ""
    scored_at: datetime | None = None
    backfilled: bool = False


class JournalDayOut(BaseModel):
    """某一天的研判归档 + 后续表现。"""

    score_date: DateType
    weekday: str = Field("", description="周几（中文）")
    evaluated: bool = Field(True, description="该日是否有打分记录")
    effective_score: float = Field(50.0, description="当日加权有效分值")
    direction: DirectionSignal = DirectionSignal.NEUTRAL
    weighted: bool = False
    formula: str = ""
    slots: list[JournalSlotOut] = Field(default_factory=list)
    basis: list[str] = Field(default_factory=list, description="当日全部依据标签（去重）")
    notes: str = ""
    review_note: str = ""
    backfilled: bool = Field(False, description="当日全部记录均为补录时为 True")
    price_date: DateType | None = Field(None, description="基准日价格日期")
    price_close: float | None = Field(None, description="基准日收盘价")
    outcomes: list[OutcomeOut] = Field(default_factory=list)


class JournalOut(BaseModel):
    """研判日志（按日期倒序）。"""

    target: str
    days: int
    horizon: int = Field(1, description="卡片主判定窗口（交易日）")
    total: int = 0
    pending: int = Field(0, description="尚待验证的天数")
    price_days: int = 0
    latest_price_date: DateType | None = None
    items: list[JournalDayOut] = Field(default_factory=list)


class DirectionStatsOut(BaseModel):
    """按研判方向分组的命中统计。"""

    direction: DirectionSignal
    label: str = ""
    samples: int = 0
    hits: int = 0
    hit_rate: float | None = Field(None, description="命中率 %；样本为 0 时为 None")


class HorizonStatsOut(BaseModel):
    """按窗口分组的命中统计。"""

    horizon: int
    samples: int = 0
    hits: int = 0
    hit_rate: float | None = None


class CalibrationBucketOut(BaseModel):
    """分值分箱校准：看「打多少分时实际上涨概率多大」。"""

    key: str = Field(..., description="分箱标识，如 60-80")
    lower: float = 0
    upper: float = 100
    samples: int = 0
    avg_score: float | None = None
    up_rate: float | None = Field(None, description="该箱内 T+H 上涨的比例 %")
    hit_rate: float | None = Field(None, description="该箱内方向命中率 %")


class TagStatsOut(BaseModel):
    """研判依据标签胜率：哪类依据更可靠。"""

    tag: str
    samples: int = 0
    hits: int = 0
    hit_rate: float | None = None


class ReviewStatsOut(BaseModel):
    """复盘统计汇总。"""

    target: str
    days: int
    horizon: int = 1
    total_days: int = Field(0, description="区间内有研判的天数")
    evaluated: int = Field(0, description="已参与统计的天数（不含补录与待验证）")
    hits: int = 0
    hit_rate: float | None = Field(None, description="整体方向命中率 %")
    pending: int = Field(0, description="尚待验证天数")
    backfilled_excluded: int = Field(0, description="因补录被排除的天数")
    avg_score: float | None = Field(None, description="平均研判分值")
    avg_change: float | None = Field(None, description="平均后续涨跌幅 %")
    by_direction: list[DirectionStatsOut] = Field(default_factory=list)
    by_horizon: list[HorizonStatsOut] = Field(default_factory=list)
    calibration: list[CalibrationBucketOut] = Field(default_factory=list)
    tags: list[TagStatsOut] = Field(default_factory=list)
    sample_warning: bool = Field(
        False, description="样本不足（<20）时置 True，前端标注仅供参考"
    )
    note: str = ""
