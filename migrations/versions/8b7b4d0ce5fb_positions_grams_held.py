"""positions 表新增 grams_held 列（V0.70.0 P2 #8）

Revision ID: 8b7b4d0ce5fb
Revises: b7c5d9e3f1a2
Create Date: 2026-09-19 10:00:00.000000

迁移策略（SQLite 友好、可重复执行）
----------------------------------
为 ``positions`` 增加 ``grams_held``（克数持有，``Numeric(12, 3) NULL``）：

1. ``add_column`` 加可空列（不动存量行的 quantity / avg_cost）；
2. 幂等 ``UPDATE``（存量行 grams_held 保持 NULL，等用户首次按克交易时回填）；
3. 建 ``ix_positions_grams_held`` 索引（仅供未来按克筛选，本次业务查询暂未用）；
4. downgrade：drop 索引 + batch_alter_table drop_column。

为什么不直接 ``server_default="0"``：历史 quantity 数据在「按份」口径下未必有可信
的克数换算（克价缺失时强行回填会污染决策）。可空让业务层（Service.open）在用户显式
传入 grams 时落库；旧持仓 grams_held 留空，由 UI 显示「—」并跳过克数汇总。

依赖：V0.68.0 telemetry_events（b7c5d9e3f1a2）
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8b7b4d0ce5fb"
down_revision: Union[str, Sequence[str], None] = "b7c5d9e3f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "positions",
        sa.Column(
            "grams_held",
            sa.Numeric(precision=12, scale=3),
            nullable=True,
            comment="当前持仓克数（g）；可空——历史「按份」持仓未回填",
        ),
    )
    # 幂等：存量行留 NULL（业务含义：克数未知）；后续不再做 UPDATE
    op.execute("UPDATE positions SET grams_held = NULL WHERE grams_held IS NULL")
    op.create_index(
        op.f("ix_positions_grams_held"), "positions", ["grams_held"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_positions_grams_held"), table_name="positions")
    with op.batch_alter_table("positions") as batch:
        batch.drop_column("grams_held")
