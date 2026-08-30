"""分析记录 ORM 模型：持久化每次机会评估的输入因子与输出结论。"""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AnalysisRecord(Base):
    """单次黄金ETF交易机会分析记录。"""

    __tablename__ = "analysis_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ---- 输入：宏观因子 ----
    dxy: Mapped[float] = mapped_column(Float, comment="美元指数 DXY 点位")
    us10y_yield: Mapped[float] = mapped_column(Float, comment="美债10年期收益率 %")
    real_rate: Mapped[float] = mapped_column(Float, comment="实际利率 %（10Y名义 - 盈亏平衡通胀）")
    inflation_expectation: Mapped[float] = mapped_column(Float, comment="通胀预期 %（盈亏平衡）")
    risk_off: Mapped[int] = mapped_column(Integer, comment="避险情绪 0-10（0=贪婪，10=恐慌）")

    # ---- 输出：评分与结论 ----
    score: Mapped[float] = mapped_column(Float, comment="综合机会评分 0-100")
    window: Mapped[str] = mapped_column(String(16), comment="投资窗口 strong/medium/weak/standby")
    signal: Mapped[str] = mapped_column(String(16), comment="方向信号 bullish/bearish/neutral")
    factors_detail: Mapped[str] = mapped_column(Text, comment="各因子明细 JSON 字符串")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="创建时间",
    )
