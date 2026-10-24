"""全球黄金交易所库存 ORM 模型：COMEX 黄金库存日频序列（吨）。

数据来源
--------
COMEX（纽约商品交易所）黄金注册+合格库存总量，经 AKShare
``ak.futures_comex_inventory`` 抓取（底层为公开表格页 ``pandas.read_html``）。

为什么是 COMEX 而不是别处
--------------------------
候选实测（V0.115.0 落地前逐个跑过）：
- ``ak.spot_quotations_sge`` —— 上金所现货行情，**只有价格没有库存字段**，不可用；
- ``ak.fund_etf_scale_sse`` —— 上交所 ETF 份额，是**单截面**（无历史序列），
  且实测最新统计日期停在 2025-01-15，陈旧 21 个月，拿它当「库存变化」是编数据；
- ``ak.futures_comex_inventory`` —— 2021-10-25 起 1234 个交易日，日频连续，
  截至 2026-10-20 —— 唯一合格来源。

口径说明
--------
- COMEX 库存是**交易所仓库里的黄金总量**，去库存在实务中常被解读为
  近月合约支撑增强的信号。它**不等于**全球央行持有量（那是 ``central_bank_purchases``
  表的活），也不等于 ETF 持仓。两张表口径不同，前端必须分开标注，别混谈。
- ``tonnes`` 为吨（1 吨 = 32,150.7466 金衡盎司），``ounces`` 保留原始值便于对账；
  akshare 两列都给了，存下来省一次换算争议。
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class GoldInventoryDaily(Base):
    """COMEX 黄金库存日频快照（吨）。

    - 唯一约束：``inv_date``，同一天重复抓取走 upsert 而不是插重复行；
    - ``source`` 标识数据来源，将来接第二个交易所时可直接并存；
    - 只存**观测值**，不存变化率 —— 变化率按日历日回看算（见
      ``services/gold_inventory.py``），存下来会和「今天往前数 N 天」的口径漂移。
    """

    __tablename__ = "gold_inventory_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inv_date: Mapped[date] = mapped_column(Date, index=True, comment="观测日期")
    tonnes: Mapped[float] = mapped_column(Float, comment="COMEX 黄金库存（吨）")
    ounces: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="COMEX 黄金库存（金衡盎司），原始值留档对账"
    )
    source: Mapped[str] = mapped_column(
        String(32),
        default="COMEX",
        server_default="COMEX",
        comment="数据源标识，如 COMEX",
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (UniqueConstraint("inv_date", name="uq_gold_inv_date"),)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<GoldInventoryDaily {self.inv_date} {self.tonnes:.2f}t>"
