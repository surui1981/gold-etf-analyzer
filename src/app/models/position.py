"""交易面 ORM 模型：持仓与交易流水。"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Position(Base):
    """个人持仓记录（单用户模式，预留 user_id 支持多用户）。"""

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, default=1, comment="预留多用户，当前单用户=1")

    symbol: Mapped[str] = mapped_column(String(16), comment="品种代码，如 518880")
    name: Mapped[str] = mapped_column(String(64), comment="品种名称")

    quantity: Mapped[float] = mapped_column(Float, comment="当前持仓数量（份）")
    avg_cost: Mapped[float] = mapped_column(Float, comment="摊薄成本（元/份）")

    status: Mapped[str] = mapped_column(String(16), default="open", comment="open/closed")
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TradeRecord(Base):
    """交易流水：开仓/加仓/减仓/清仓的每一笔成交。"""

    __tablename__ = "trade_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position_id: Mapped[int] = mapped_column(
        ForeignKey("positions.id", ondelete="CASCADE"),
        index=True,
        comment="关联持仓",
    )
    side: Mapped[str] = mapped_column(String(8), comment="buy 买入 / sell 卖出")
    quantity: Mapped[float] = mapped_column(Float, comment="成交数量（份）")
    price: Mapped[float] = mapped_column(Float, comment="成交价（元/份）")
    fee: Mapped[float] = mapped_column(Float, default=0.0, comment="手续费")
    traded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="成交时间",
    )
