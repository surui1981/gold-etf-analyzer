"""消息面评估 ORM 模型：客户对投行黄金展望的每日打分。"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class NewsScore(Base):
    """消息面每日打分（客户评估）。

    - ``score`` 0-100：>55 看多展望、<45 看空、50 中性
    - ``notes`` 客户研判备注（参考的投行观点/链接）
    """

    __tablename__ = "news_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    score_date: Mapped[date] = mapped_column(Date, unique=True, index=True, comment="打分日期（每日一条）")
    score: Mapped[float] = mapped_column(Float, comment="消息面看多强度 0-100")
    direction: Mapped[str] = mapped_column(String(12), default="neutral", comment="bullish/bearish/neutral")
    notes: Mapped[str] = mapped_column(Text, default="", comment="客户研判备注（参考投行观点/链接）")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
