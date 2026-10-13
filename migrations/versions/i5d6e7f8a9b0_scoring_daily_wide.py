"""scoring_daily_wide 表新增（V0.92.0 · 历史打分数据汇总）

Revision ID: i5d6e7f8a9b0
Revises: c4d5e6f7a8b9
Create Date: 2026-10-13 10:00:00.000000

迁移策略（SQLite 友好、可重复执行）
----------------------------------
新建 ``scoring_daily_wide`` 表 —— V0.92.0 汇总页的物化宽表，每日 1 行。
把 4 指数（snapshot）+ 消息面聚合（news_scores）+ 价格涨跌（gold_price_daily）
预拼装成 1 行，避免任何"按日/月/tag 汇总"查询都要 4-6 表 JOIN + JSON parse。

为什么需要
----------
- V0.91.0 timeline / V0.66.0 review / V0.90.0 snapshots 各自有"history"端点
  但**没有"按月按 tag 跨维度汇总"**入口；任何"美元指数标签下 30 日胜率"
  都要 4 表 JOIN + JSON 反序列化 + 内存聚合（~200ms/次）
- ``daily_snapshots`` 16 列已到上限（再加 basis_tags / outcomes 会失控）
- ``daily_snapshots.macro_detail`` / ``tech_detail`` 是 Text JSON，每次查询
  反序列化（与 V0.90.0 修复一致：宽表直接保留反序列化后的最终 score）

字段约定
--------
- ``date`` 主键（1 日 1 行）
- ``user_id``：V0.80.0 #159 数据隔离纪律
- ``snapshot_id``：FK -> ``daily_snapshots.id``（NULL = 当日未捕获快照）
- 4 指数：tech/macro/news/trend_index + index_level（来自 daily_snapshots）
- 价格：close / change_pct / direction / data_source（V0.79.0 #163 来源标记）
- 消息面：slot_count / basis_tags TEXT JSON / backfilled_count
- 共振：signal / subtype（V0.78.0 Step C 当日重建，跨日不持久）
- outcomes：T+1/T+3/T+5 实际涨跌 + 命中判定（pending 期为 NULL）
- 2 个元字段：created_at / updated_at

⚠ V0.78.0 Step D 纪律：所有数值列允许 NULL（数据不足 ≠ 中性），
   **绝不**用 50 / 0 兜底 —— 与 ``daily_snapshots.tech_index=0.0`` 旧行为
   区分（该处只对 tech_index 累加做了 0.0 fallback，snapshot 行级仍可能 NULL）。
⚠ V0.79.0 任务 #162 教训：本表所有列在 ``ScoringWideRepository.upsert``
   字段白名单**必须**列全 —— insert 与 update 路径同步，避免加列后
   "update 路径永远不写新字段"（与 snapshot.tech_detail 同类陷阱）。
⚠ V0.80.0 #159 教训：所有新表必有 ``user_id`` 列；仓储层强制 WHERE 过滤。

⚠ **回滚策略**
``downgrade()`` 删表 —— 历史聚合数据可由 ``backfill_scoring_wide.py`` 重建
（CLI 跑 ``alembic downgrade`` + ``alembic upgrade`` 后重跑回填），无数据丢失风险。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "i5d6e7f8a9b0"
down_revision: str | Sequence[str] | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists() -> bool:
    """探测 ``scoring_daily_wide`` 是否已存在（保证可重复执行）。"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return "scoring_daily_wide" in inspector.get_table_names()


def upgrade() -> None:
    """Upgrade schema."""
    if _table_exists():
        return
    op.create_table(
        "scoring_daily_wide",
        sa.Column(
            "date",
            sa.Date(),
            primary_key=True,
            nullable=False,
            comment="快照日期（主键；1 日 1 行）",
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment="V0.80.0 #159 数据隔离",
        ),
        sa.Column(
            "snapshot_id",
            sa.Integer(),
            nullable=True,
            comment="FK -> daily_snapshots.id（NULL=当日未捕获快照）",
        ),
        # ── 4 指数（来自 daily_snapshots）──
        sa.Column("tech_index", sa.Float(), nullable=True, comment="技术面指数（V0.78.0 Step D：数据不足可空）"),
        sa.Column("macro_index", sa.Float(), nullable=True, comment="宏观参考指数"),
        sa.Column("news_index", sa.Float(), nullable=True, comment="消息面指数（NULL=当日无打分）"),
        sa.Column("trend_index", sa.Float(), nullable=True, comment="综合趋势评估指数"),
        sa.Column(
            "index_level",
            sa.String(length=16),
            nullable=True,
            comment="指数等级 strong_bullish/bullish/neutral/bearish/strong_bearish",
        ),
        # ── 价格参数（来自 daily_snapshots）──
        sa.Column("close", sa.Float(), nullable=True, comment="当日收盘价"),
        sa.Column("change_pct", sa.Float(), nullable=True, comment="当日涨跌幅 %"),
        sa.Column("direction", sa.String(length=12), nullable=True, comment="up/down/sideways"),
        sa.Column(
            "data_source",
            sa.String(length=16),
            nullable=True,
            comment="行情来源 live/stale/mock（V0.79.0 #163；历史 NULL=未标记）",
        ),
        # ── 消息面聚合（来自 news_scores 当日所有 slot）──
        sa.Column(
            "news_slot_count",
            sa.Integer(),
            nullable=True,
            comment="当日有效打分次数（0/1/2/3）",
        ),
        sa.Column(
            "news_basis_tags",
            sa.Text(),
            nullable=True,
            comment="依据标签 JSON 数组（去重，跨 slot 合并）",
        ),
        sa.Column(
            "news_backfilled_count",
            sa.Integer(),
            nullable=True,
            comment="当日补录次数（V0.66.0 复盘统计默认排除）",
        ),
        # ── 共振信号（V0.78.0 Step C 当日重建；不持久化跨日）──
        sa.Column(
            "resonance_signal",
            sa.String(length=16),
            nullable=True,
            comment="strong_up/weak_up/divergent/neutral",
        ),
        sa.Column(
            "resonance_subtype",
            sa.String(length=16),
            nullable=True,
            comment="tech_macro/tech_news/macro_news（仅 divergent 有）",
        ),
        # ── 复盘 outcomes（来自 gold_price_daily + news_scores 当日方向）──
        sa.Column("actual_change_pct_t1", sa.Float(), nullable=True, comment="当日 vs T+1 收盘"),
        sa.Column("actual_change_pct_t3", sa.Float(), nullable=True, comment="当日 vs T+3 收盘"),
        sa.Column("actual_change_pct_t5", sa.Float(), nullable=True, comment="当日 vs T+5 收盘"),
        sa.Column("hit_t1", sa.Boolean(), nullable=True, comment="T+1 命中（按当日 news 方向）"),
        sa.Column("hit_t3", sa.Boolean(), nullable=True, comment="T+3 命中"),
        sa.Column("hit_t5", sa.Boolean(), nullable=True, comment="T+5 命中"),
        sa.Column(
            "outcome_pending_until",
            sa.Date(),
            nullable=True,
            comment="T+5 完成日期；NULL=未完成或全部数据就绪",
        ),
        # ── 元 ──
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    # 主键索引（date 单列 PK 索引已隐含）
    # 复合索引：(user_id, date) — V0.80.0 多用户查询主路径
    op.create_index(
        "idx_sdw_user_date",
        "scoring_daily_wide",
        ["user_id", "date"],
    )
    # 全局索引（不带 user_id；V0.93+ 跨租户分析 / 离线 CLI 用）
    op.create_index(
        "idx_sdw_date",
        "scoring_daily_wide",
        ["date"],
    )
    # 趋势极值索引（找"最 bullish / bearish 日"用）
    op.create_index(
        "idx_sdw_user_trend",
        "scoring_daily_wide",
        ["user_id", "trend_index"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    if not _table_exists():
        return
    op.drop_index("idx_sdw_user_trend", table_name="scoring_daily_wide")
    op.drop_index("idx_sdw_date", table_name="scoring_daily_wide")
    op.drop_index("idx_sdw_user_date", table_name="scoring_daily_wide")
    op.drop_table("scoring_daily_wide")
