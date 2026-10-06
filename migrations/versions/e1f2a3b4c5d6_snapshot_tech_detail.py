"""daily_snapshots 增 tech_detail 列（V0.79.0 · 任务 #162）

Revision ID: e1f2a3b4c5d6
Revises: d5f81a3c9b47
Create Date: 2026-10-06 08:10:00.000000

迁移策略（SQLite 友好、可重复执行）
----------------------------------
``daily_snapshots`` 新增可空 TEXT 列 ``tech_detail``，存技术面 5 维度分 JSON：
``{"结构": {"score": .., "weight": .., "contribution": ..}, ...}``。

为什么需要
----------
``tech_index`` 是「5 个子维度分 × 各自权重」的**最终加权和，拆不回去**；
而 V0.79.0 Step G 要在回测里扫描**技术面内部权重**（``trend_5`` 网格），
没有子维度原始分就算不出来。

宏观侧不需要额外列 —— ``macro_detail`` 里已经存了 5 个因子的 ``score``，
故 ``macro_5`` 网格开箱可用；技术面此前缺此落库，本迁移补齐该缺口。

⚠ **可空且不回填历史**
上游 K 线只覆盖 24 条历史快照中的 16-17 天（``ny`` 有 365 根真实 K 线，
``etf`` / ``gram`` 上游仅给 42 根，且 ``etf`` 当前降级为 mock），
**回填不可能完整**。因此：

- 列**可空**，历史 24 行保持 NULL；
- 读到 NULL 即表示「该日无子维度分」，调用方**必须显式跳过**，
  **不可用中性 50 兜底**（沿用 V0.78.0 Step D「数据不足 ≠ 中性」的纪律）；
- 缺失日期**绝不可用邻近日期顶替** —— 那是伪造历史。

``create_all`` 不会给已存在的表加列，故本迁移是新建库之外路径的必需项；
老库另有 ``utils/db_migrate.py`` 的幂等补列兜底（两处都声明，双保险）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: str | Sequence[str] | None = "d5f81a3c9b47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_exists() -> bool:
    """探测 ``daily_snapshots.tech_detail`` 是否已存在（保证可重复执行）。

    ⚠ Alembic 迁移通常只跑一次，但本仓要求迁移**可重复执行**
    （老库经 ``db_migrate.py`` 补过列时，``upgrade head`` 仍会执行到这里），
    故必须先探测再 ADD COLUMN，否则「已补列的老库」会因
    ``duplicate column name`` 而升级失败。
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "daily_snapshots" not in inspector.get_table_names():
        return True  # 表不存在（新建库由 create_all 负责），跳过
    return any(c["name"] == "tech_detail" for c in inspector.get_columns("daily_snapshots"))


def upgrade() -> None:
    """Upgrade schema."""
    if _column_exists():
        return
    op.add_column(
        "daily_snapshots",
        sa.Column(
            "tech_detail",
            sa.Text(),
            nullable=True,
            comment="技术面 5 维度 JSON（V0.79.0；历史行为 NULL）",
        ),
    )


def downgrade() -> None:
    """Downgrade schema.

    ⚠ SQLite（3.35 前）不支持 DROP COLUMN，早期版本会直接报错。
    这是**有意为之**：``tech_detail`` 是纯增量列，删列会丢历史数据，
    而 downgrade 在本仓几乎不被使用。宁可报错也不静默丢数据。
    """
    if _column_exists():
        op.drop_column("daily_snapshots", "tech_detail")
