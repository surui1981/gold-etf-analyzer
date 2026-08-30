"""每日评估快照 ORM 模型：参数 + 评估值的日频持久化（本地历史数据）。"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DailySnapshot(Base):
    """每日快照：当日价格参数与趋势/宏观评估值。

    - 每日一条（snapshot_date 唯一），重复捕获为更新
    - ``macro_detail`` 存宏观 5 因子 JSON：{key: {value, score, direction}}
    """

    __tablename__ = "daily_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_date: Mapped[date] = mapped_column(Date, unique=True, index=True, comment="快照日期")

    symbol: Mapped[str] = mapped_column(String(16), default="518880")
    name: Mapped[str] = mapped_column(String(64), default="黄金ETF华安")

    # 价格参数
    close: Mapped[float] = mapped_column(Float, comment="最新收盘价")
    change_pct: Mapped[float] = mapped_column(Float, comment="区间涨跌幅 %")
    high: Mapped[float] = mapped_column(Float, comment="区间最高")
    low: Mapped[float] = mapped_column(Float, comment="区间最低")
    ma20: Mapped[float] = mapped_column(Float, comment="MA20")
    ma40: Mapped[float] = mapped_column(Float, comment="MA40")
    direction: Mapped[str] = mapped_column(String(12), comment="趋势方向 up/down/sideways")

    # 评估值
    tech_index: Mapped[float] = mapped_column(Float, comment="技术面指数")
    macro_index: Mapped[float] = mapped_column(Float, comment="宏观参考指数")
    trend_index: Mapped[float] = mapped_column(Float, comment="综合趋势评估指数")
    index_level: Mapped[str] = mapped_column(String(16), comment="指数等级")

    # 宏观因子明细（JSON）
    macro_detail: Mapped[str] = mapped_column(Text, comment="宏观 5 因子 JSON")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
