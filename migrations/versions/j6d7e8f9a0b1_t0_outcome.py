"""scoring_daily_wide 加 T+0 outcome 列（V0.93.0 · 当日尾盘验证）

Revision ID: j6d7e8f9a0b1
Revises: i5d6e7f8a9b0
Create Date: 2026-10-15 00:00:00.000000

迁移背景
----------
V0.92.0 只有 T+1/T+3/T+5 三个 outcome 窗口 —— 都是「未来窗口」验证，
最快也要等次日 15:30 沪金尾盘才有 T+1 数据。

V0.93.0 加 T+0 outcome：
- ``actual_change_pct_t0``: 当日 close vs 上一交易日 close 的涨跌幅 %
- ``hit_t0``: 当日 news 方向 vs 当日 close 涨跌方向的命中判定

定位：**「快速反馈」**——用户做今日打分后无需等次日即可知「今日沪金」
是否印证其研判方向。注意 T+0 含打分时刻已发生的盘内信息（数据泄露），
不在评估「预测能力」时使用，仅作快速 sanity check（前端加 tip 注明）。

迁移策略
--------
- 仅 ``add_column``，**不**重命名、不删列（V0.78.0 Step D 兼容：所有数值列
  允许 NULL，老行新列默认 NULL，符合"pending 期"语义）
- 无需新索引：``hit_t0`` 的过滤走与 ``hit_t1`` 同一查询路径（应用层 row
  filter + 内存聚合），不依赖 SQL 索引
- 无需 backfill：现有行的 ``actual_change_pct_t0 / hit_t0`` 留 NULL，
  跑 ``python -m scripts.backfill_scoring_wide`` 即可回填所有历史日

⚠ V0.79.0 任务 #162 教训：``ScoringWideRepository.upsert`` 字段白名单
   **必须**同步加这 2 个字段 —— insert 与 update 路径同步。
⚠ V0.78.0 Step D 纪律：所有数值列允许 NULL（**绝不**用 0 / 0.0 兜底）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "j6d7e8f9a0b1"
down_revision: str | Sequence[str] | None = "i5d6e7f8a9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """加 T+0 outcome 2 列（nullable，老行 = NULL 视为 pending）。"""
    op.add_column(
        "scoring_daily_wide",
        sa.Column(
            "actual_change_pct_t0",
            sa.Float(),
            nullable=True,
            comment="当日 vs 上一交易日收盘的涨跌幅 %（V0.93.0 T+0 验证）",
        ),
    )
    op.add_column(
        "scoring_daily_wide",
        sa.Column(
            "hit_t0",
            sa.Boolean(),
            nullable=True,
            comment="T+0 命中（按当日 news 方向 vs 上一交易日→当日 close 方向）",
        ),
    )


def downgrade() -> None:
    """回滚：删 T+0 2 列。"""
    op.drop_column("scoring_daily_wide", "hit_t0")
    op.drop_column("scoring_daily_wide", "actual_change_pct_t0")
