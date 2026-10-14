"""scoring_daily_wide 加 gold_ny_close 列（V0.95.0 · NY金美元/盎司收盘）

Revision ID: k7e8f9a0b1c2
Revises: j6d7e8f9a0b1
Create Date: 2026-10-15 00:00:00.000000

迁移背景
----------
V0.92.0 起的 ``scoring_daily_wide`` 宽表里 ``close`` 字段是 **沪金 ETF 收盘价**
（元/份，标 target='etf'），用户**没有**用 NY 金（COMEX，美元/盎司）作为
价格基准。

V0.95.0 加 ``gold_ny_close``：从 ``gold_price_daily.target='ny'`` 同步 NY 金
美元/盎司收盘价到宽表，4 指数时序表用其替换「横盘日数」列（用户原话：
"把横盘日数 修改成当日 美元的收盘价"，澄清后"美元"= 黄金每盎司美元收盘价）。

迁移策略
--------
- 仅 ``add_column``，**不**重命名、不删列（V0.78.0 Step D 兼容：所有数值列
  允许 NULL，老行新列默认 NULL，符合"数据不足"语义）
- 无需新索引：``gold_ny_close`` 是**展示列**（前端 4 指数时序表用），不参与
  hit-stats 过滤或 summary 聚合（聚合时按 group_by=day/week/month 内存
  取桶内最后一日值，不依赖 SQL 索引）
- 无需 backfill：现有行的 ``gold_ny_close`` 留 NULL，跑
  ``python -m scripts.backfill_scoring_wide`` 即可回填所有历史日
  （脚本会调 ``service.rebuild(date)`` → ``_build_row`` → 读 NY 金 close 落新列）

⚠ V0.79.0 任务 #162 教训：``ScoringWideRepository.upsert`` 字段白名单
   **必须**同步加这 1 个字段 —— insert 与 update 路径同步。
⚠ V0.78.0 Step D 纪律：所有数值列允许 NULL（**绝不**用 0 / 0.0 兜底）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "k7e8f9a0b1c2"
down_revision: str | Sequence[str] | None = "j6d7e8f9a0b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """加 gold_ny_close 1 列（nullable，老行 = NULL 视为缺数据）。"""
    op.add_column(
        "scoring_daily_wide",
        sa.Column(
            "gold_ny_close",
            sa.Float(),
            nullable=True,
            comment="NY 金（COMEX）美元/盎司收盘价（V0.95.0 · 4 指数时序表用）",
        ),
    )


def downgrade() -> None:
    """回滚：删 gold_ny_close 列。"""
    op.drop_column("scoring_daily_wide", "gold_ny_close")
