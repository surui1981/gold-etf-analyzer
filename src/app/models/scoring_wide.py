"""打分数据宽表 ORM 模型（V0.92.0 · 历史打分数据汇总）

把 4 指数（snapshot）+ 消息面聚合（news_scores）+ 价格涨跌（gold_price_daily）
预拼装成 1 行/日，避免任何"按日/月/tag 汇总"查询都要 4-6 表 JOIN + JSON parse。

V0.93.0 加 T+0 outcome 列（``actual_change_pct_t0`` / ``hit_t0``）——
定位「当日尾盘快速反馈」，T+1 仍为「未来窗口」主战场。详见 migration
``j6d7e8f9a0b1``。

⚠ **字段设计纪律**
- 所有数值列允许 NULL（V0.78.0 Step D：数据不足 ≠ 中性，**绝不**用 50 / 0 兜底）
- ``news_basis_tags`` 存 JSON 文本（应用层 ``json.loads`` 后做 tag 维度 filter）
- ``snapshot_id`` 可空（当日可能未捕获快照，宽表仍记录 partial 数据）
- 4 个 outcome 列在 pending 期为 NULL（``outcome_pending_until`` 标记完成日）
"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ScoringDailyWide(Base):
    """打分数据日级宽表：4 指数 + 消息面 + 共振 + 复盘 outcomes + 实际涨跌。

    V0.92.0 汇总页 / ``/api/v1/scoring/summary`` 的事实真相。
    每日 1 行，由 :class:`~app.services.scoring_wide.ScoringWideService.rebuild`
    在 ``DailySnapshotService.capture_today`` 与 ``NewsScoreService.save_today``
    写时 hook 触发 ETL。

    Attributes:
        date: 快照日期（主键，1 日 1 行）。
        user_id: V0.80.0 #159 数据隔离。
        snapshot_id: FK -> ``daily_snapshots.id``（NULL=当日未捕获快照）。
        tech_index/macro_index/news_index/trend_index: 4 指数（可空）。
        index_level: ``strong_bullish`` / ``bullish`` / ``neutral`` / ``bearish`` / ``strong_bearish``。
        close/change_pct/direction: 价格参数（来自 snapshot）。
        data_source: 行情来源（V0.79.0 #163；历史 NULL=未标记）。
        news_slot_count: 当日有效打分次数（0/1/2/3）。
        news_basis_tags: 依据标签 JSON 数组（去重，跨 slot 合并）。
        news_backfilled_count: 当日补录次数。
        resonance_signal: ``strong_up`` / ``weak_up`` / ``divergent`` / ``neutral``。
        resonance_subtype: ``tech_macro`` / ``tech_news`` / ``macro_news``（仅 divergent）。
        actual_change_pct_t1/t3/t5: T+1/T+3/T+5 实际涨跌（来自 gold_price_daily）。
        hit_t1/t3/t5: T+1/T+3/T+5 命中判定（按当日 news 方向）。
        outcome_pending_until: T+5 完成日期；NULL=未完成。
        created_at/updated_at: 元。
    """

    __tablename__ = "scoring_daily_wide"

    # ── 主键 + 隔离 ──
    date: Mapped[date] = mapped_column(Date, primary_key=True, comment="快照日期（主键）")
    user_id: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1", comment="V0.80.0 #159 数据隔离"
    )
    snapshot_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="FK -> daily_snapshots.id（NULL=当日未捕获快照）"
    )

    # ── 4 指数（V0.78.0 Step D：可空）──
    tech_index: Mapped[float | None] = mapped_column(Float, nullable=True, comment="技术面指数")
    macro_index: Mapped[float | None] = mapped_column(Float, nullable=True, comment="宏观参考指数")
    news_index: Mapped[float | None] = mapped_column(Float, nullable=True, comment="消息面指数")
    trend_index: Mapped[float | None] = mapped_column(Float, nullable=True, comment="综合趋势评估指数")
    index_level: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="指数等级 strong_bullish/bullish/..."
    )

    # ── 价格参数 ──
    close: Mapped[float | None] = mapped_column(Float, nullable=True, comment="当日收盘价")
    change_pct: Mapped[float | None] = mapped_column(Float, nullable=True, comment="当日涨跌幅 %")
    direction: Mapped[str | None] = mapped_column(
        String(12), nullable=True, comment="up/down/sideways"
    )
    data_source: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="行情来源 live/stale/mock（V0.79.0 #163）"
    )
    # V0.95.0：NY 金（COMEX）美元/盎司收盘价 —— 与 ``close``（沪金 ETF 元/份）
    # 是 2 个不同标的，4 指数时序表用其替换「横盘日数」列。
    # 数据源：``gold_price_daily.target='ny'``（DEFAULT_REVIEW_TARGET）。
    gold_ny_close: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="NY 金美元/盎司收盘价（V0.95.0）"
    )

    # ── 消息面聚合 ──
    news_slot_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="当日有效打分次数（0/1/2/3）"
    )
    news_basis_tags: Mapped[str | None] = mapped_column(
        # V0.92.0：用 String(2048) 存 JSON 数组 —— 12 个标签最长 24 字
        # 即 12 × 24 + 引号逗号 ≈ 350B，2048 富余 5 倍
        String(2048),
        nullable=True,
        comment="依据标签 JSON 数组（去重，跨 slot 合并）",
    )
    news_backfilled_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="当日补录次数（V0.66.0 复盘统计默认排除）"
    )

    # ── 共振信号 ──
    resonance_signal: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="strong_up/weak_up/divergent/neutral"
    )
    resonance_subtype: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="tech_macro/tech_news/macro_news（仅 divergent）"
    )

    # ── 复盘 outcomes ──
    actual_change_pct_t1: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="当日 vs T+1 收盘"
    )
    actual_change_pct_t3: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="当日 vs T+3 收盘"
    )
    actual_change_pct_t5: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="当日 vs T+5 收盘"
    )
    hit_t1: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, comment="T+1 命中（按当日 news 方向）"
    )
    hit_t3: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, comment="T+3 命中"
    )
    hit_t5: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, comment="T+5 命中"
    )
    # V0.93.0：T+0 outcome —— 当日 close vs 上一交易日 close 的命中判定。
    # 定位「快速反馈」（打分时刻已发生盘内信息，仅 sanity check，不作预测能力评估）。
    actual_change_pct_t0: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="当日 vs 上一交易日收盘（V0.93.0 T+0 验证）"
    )
    hit_t0: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, comment="T+0 命中（当日 close vs 上一交易日 close）"
    )
    outcome_pending_until: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="T+5 完成日期；NULL=未完成"
    )

    # ── 元 ──
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # ── 索引（与 alembic migration 同步）──
    __table_args__ = (
        Index("idx_sdw_user_date", "user_id", "date"),
        Index("idx_sdw_date", "date"),
        Index("idx_sdw_user_trend", "user_id", "trend_index"),
    )
