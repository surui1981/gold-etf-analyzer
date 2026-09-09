"""世界央行黄金购买 ORM 模型：按国家 / 季度净购金（吨）的历史数据。

数据来源：
- IMF IRFCL（International Reserves and Foreign Currency Liquidity）月度 fine troy ounces，
  在应用层 oz → tonnes 转换 + 月 → 季聚合；
- WGC 月报手工补丁（UZB / IRN 不向 IMF 披露）。

字段单位约定：
- ``tonnes_net``：季度净购金（吨），正=买入/负=卖出；俄罗斯/土耳其历史上多次卖出。
- ``quarter``：6 字符串 "2026Q2"（年+季度），便于按字典序排序与范围筛选。
- ``country_iso``：ISO 3 字母代码（CHN/POL/.../UZB/IRN），唯一约束的右半段。
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CentralBankPurchase(Base):
    """央行季度净购金（吨）。

    - 唯一约束：``(country_iso, quarter)``，避免重复插入同一国家同一季度；
    - ``source`` 字段标识数据来源（"IMF IRFCL" / "WGC 手工"），UI 可展示徽章；
    - ``data_date`` 标识数据截止日（通常为季度最后一个月），便于前端做时效提示。
    """

    __tablename__ = "central_bank_purchases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_iso: Mapped[str] = mapped_column(String(3), index=True, comment="ISO 3 字母代码")
    country_name: Mapped[str] = mapped_column(String(64), comment="国家中文名")
    quarter: Mapped[str] = mapped_column(String(6), index=True, comment="季度，如 2026Q2")
    tonnes_net: Mapped[float] = mapped_column(
        Float, comment="季度净购金（吨），正=买入/负=卖出"
    )
    source: Mapped[str] = mapped_column(
        String(32), default="IMF IRFCL", comment="数据源：IMF IRFCL / WGC 手工"
    )
    data_date: Mapped[date] = mapped_column(Date, comment="数据截止日（季度最后一日）")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("country_iso", "quarter", name="uq_cb_country_quarter"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<CentralBankPurchase {self.country_iso} {self.quarter} "
            f"{self.tonnes_net:+.1f}t>"
        )
