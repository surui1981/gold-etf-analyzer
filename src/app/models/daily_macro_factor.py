"""每日宏观因子原始值时序化（V0.79.0 Step E）。

为 V0.79.0 Step E「动态化宏观阈值」提供历史窗口：

- ``daily_snapshots.macro_detail`` 存的是「当日的 score」（已计算），本表存的是
  「当日的原始 value」（输入）；
- 两者来源相同（同一 ``_collect()`` 输出），但 ``macro_detail`` 是结果，
  本表是输入；
- 每日 07:00 BJT 调度 upsert；唯一键 ``(target, snapshot_date, factor_key)``
  保证幂等。

字段约定
--------
- ``target``：标的维度（V0.79.0 Step E 默认所有 target 共享 ``"default"``，
  因为 5 个因子都是单一全市场源：H.15 / WGC / 静态参考）；
- ``factor_key``：dxy / us10y / us30y / vix / cb_gold 五种之一；
- ``data_date``：因子本身的数据日期（cb_gold 可能跨季度，写成
  ``"2025Q3–2026Q2 滚动12月"`` 形式）；
- ``snapshot_date``：采集日，每日一条，正好凑成滚动窗口的天然粒度。
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DailyMacroFactor(Base):
    """每日宏观因子原始值时序化（V0.79.0 Step E）。"""

    __tablename__ = "daily_macro_factors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target: Mapped[str] = mapped_column(
        String(16),
        index=True,
        comment='标的维度（默认 "default" — 5 因子全市场共享源）',
    )
    snapshot_date: Mapped[date] = mapped_column(
        Date,
        comment="采集日（滚动窗口的天然粒度）",
    )
    factor_key: Mapped[str] = mapped_column(
        String(16),
        comment="dxy / us10y / us30y / vix / cb_gold",
    )
    value: Mapped[float] = mapped_column(Float, comment="当日该因子原始数值")
    data_date: Mapped[str] = mapped_column(
        String(32),
        comment='因子本身的数据日期（cb_gold 写 "2025Q3–2026Q2" 形式）',
    )
    source: Mapped[str] = mapped_column(
        String(32),
        default="",
        comment='数据源标识（"美联储 H.15" / "静态参考值" / "央行购金表自动汇总"）',
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "target",
            "snapshot_date",
            "factor_key",
            name="uq_dmf_target_date_factor",
        ),
        Index("idx_dmf_snapshot_target", "snapshot_date", "target"),
        Index(
            "idx_dmf_factor_target_date_desc",
            "factor_key",
            "target",
            "snapshot_date",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<DailyMacroFactor {self.factor_key} {self.snapshot_date} "
            f"{self.value:g}>"
        )
