"""gold_inventory_daily 表：COMEX 黄金库存日频序列（吨）

Revision ID: s1t2u3v4w5x
Revises: q3r4s5t6u7
Create Date: 2026-10-22 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "s1t2u3v4w5x"
down_revision: Union[str, Sequence[str], None] = "q3r4s5t6u7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn) -> bool:
    """表是否已存在。

    ⚠ 这道幂等守卫是**必需**的，不是防御性冗余：``main._migrate_db()`` 在
    alembic 失败时会回退 ``Base.metadata.create_all``，两条建表路径都跑过时，
    下一次启动第二次 create_table 会直接抛「table already exists」而整个
    lifespan 起不来。同族迁移（``p2q3r4s5t6`` / ``q3r4s5t6u7``）都带这个守卫。
    """
    return sa.inspect(conn).has_table("gold_inventory_daily")


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    if _table_exists(conn):
        return
    op.create_table(
        "gold_inventory_daily",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("inv_date", sa.Date(), nullable=False, comment="观测日期"),
        sa.Column("tonnes", sa.Float(), nullable=False, comment="COMEX 黄金库存（吨）"),
        sa.Column(
            "ounces",
            sa.Float(),
            nullable=True,
            comment="COMEX 黄金库存（金衡盎司），原始值留档对账",
        ),
        sa.Column(
            "source",
            sa.String(length=32),
            nullable=False,
            server_default="COMEX",
            comment="数据源标识，如 COMEX",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.UniqueConstraint("inv_date", name="uq_gold_inv_date"),
    )
    op.create_index("ix_gold_inventory_daily_inv_date", "gold_inventory_daily", ["inv_date"])


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    if not _table_exists(conn):
        return
    op.drop_index("ix_gold_inventory_daily_inv_date", table_name="gold_inventory_daily")
    op.drop_table("gold_inventory_daily")