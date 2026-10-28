"""资金流因子原始值时序化（V0.120.0）。

为「资金流面」的滚动分位提供历史窗口。与宏观面的 ``daily_macro_factors``
有一个**关键差异**：

- 宏观面因子是**日频**的 —— ``snapshot_date`` 就是采集日，每天一行；
- 资金流因子是**周频 / 月频**的 —— ``snapshot_date`` 存的是**因子自身的观测日**
  （CFTC 的周二 / 月末 / 周四），而且**只在出现新观测时才写一行**。

为什么必须这样
--------------
若照抄宏观面的「每天写一行」，同一个周值会被重复约 5 次、同一个月值被重复约 21 次
⇒ 滚动窗口里 P10 == P90 ⇒ 阈值退化（``_friendly_score`` 撞 ``best == worst``
恒返回 50），且样本数虚高会让「已启用滚动分位」的标识假阳性。

按**观测日**落表（一个观测日一行）后，窗口内天然是不同观测 ⇒ 阈值不退化。

⚠ 另一个后果：观测日不连续（周频中间有 3 天空档、月频中间有 20 多天空档），
所以「窗口」必须用**日历天**换算而不是「行数」：周频 104 周 = 728 天、
月频 60 月 = 1826 天。见 ``services/money_flow.py::MONEY_FLOW_FACTOR_RULES``
的 ``window_days`` 字段。

字段约定
--------
- ``target``：标的维度（默认 ``"default"`` —— 资金流因子都是全市场源）；
- ``factor_key``：``services/money_flow.py::MONEY_FLOW_FACTOR_RULES`` 里的 key 之一
  （cot_gold_net / cot_gold_flow / gold_etf_flow / us_liq_net /
  cn_margin_flow / cn_money_gap）；
- ``snapshot_date``：**因子自身的观测日**（不是采集日）；
- ``data_date``：给前端看的口径说明（可以是自由文本，如「近 4 周累计」）；
- ``source``：数据源标识（「CFTC 分类持仓」「东财 518880」…）。
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DailyMoneyFlowFactor(Base):
    """资金流因子原始值时序化（V0.120.0）。"""

    __tablename__ = "daily_money_flow_factors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target: Mapped[str] = mapped_column(
        String(16),
        index=True,
        comment='标的维度（默认 "default" — 全部因子全市场共享源）',
    )
    snapshot_date: Mapped[date] = mapped_column(
        Date,
        comment="**因子自身的观测日**（CFTC 周二 / 月末 / 周四），不是采集日",
    )
    factor_key: Mapped[str] = mapped_column(
        String(32),
        comment="资金流因子 key（见 MONEY_FLOW_FACTOR_RULES，V0.120.0 起 6 个）",
    )
    value: Mapped[float] = mapped_column(Float, comment="该次观测的原始数值")
    data_date: Mapped[str] = mapped_column(
        String(32),
        default="",
        comment='口径说明（自由文本，如 "近 4 周累计" / "2026-09 月度"）',
    )
    source: Mapped[str] = mapped_column(
        String(48),
        default="",
        comment='数据源标识（"CFTC 分类持仓" / "东财 518880" / "FRED" / "akshare 交易所"）',
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "target",
            "snapshot_date",
            "factor_key",
            name="uq_dmff_target_date_factor",
        ),
        Index("idx_dmff_snapshot_target", "snapshot_date", "target"),
        Index(
            "idx_dmff_factor_target_date_desc",
            "factor_key",
            "target",
            "snapshot_date",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DailyMoneyFlowFactor {self.factor_key} {self.snapshot_date} {self.value:g}>"
