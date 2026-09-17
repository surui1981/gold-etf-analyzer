"""黄金价格日历 ORM 模型：研判复盘的价格基准（V0.66.0）。

与 ``daily_snapshots`` 的分工：

- ``daily_snapshots`` 记录**评估值**（技术/宏观/消息/综合指数），每日由调度捕获，
  随评估口径变化；
- ``gold_price_daily`` 只记录**客观价格**，可由行情接口一次性回填历史，
  作为「当日研判 → 之后 N 个交易日表现」对比的基准，口径稳定、可长期积累。

复盘默认基准为纽约金 COMEX（``DEFAULT_REVIEW_TARGET``），与投资指引
（``TrendService.GUIDE_TARGET``）保持一致；通过 ``target`` 列支持多标的共存。
"""

from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# 复盘基准标的（与投资指引口径一致：纽约金 COMEX）
DEFAULT_REVIEW_TARGET = "ny"

# 复盘窗口（交易日）：当日研判之后第 N 个交易日的表现
REVIEW_HORIZONS: tuple[int, ...] = (1, 3, 5)

# 中性研判的「走平」容差（%）：涨跌幅绝对值不超过该值即视为横盘命中
NEUTRAL_BAND_PCT = 0.3


class GoldPriceDaily(Base):
    """黄金每日收盘价（按 ``target`` + ``price_date`` 唯一）。"""

    __tablename__ = "gold_price_daily"
    __table_args__ = (UniqueConstraint("target", "price_date", name="uq_gold_price_target_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target: Mapped[str] = mapped_column(
        String(8), default=DEFAULT_REVIEW_TARGET, comment="标的：ny/etf/gram"
    )
    price_date: Mapped[date] = mapped_column(Date, index=True, comment="交易日")
    close: Mapped[float] = mapped_column(Float, comment="当日收盘价")
    change_pct: Mapped[float] = mapped_column(
        Float, default=0.0, comment="相对前一交易日的涨跌幅 %"
    )
    source: Mapped[str] = mapped_column(
        String(32), default="", comment="数据来源标识（live/mock/...）"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
