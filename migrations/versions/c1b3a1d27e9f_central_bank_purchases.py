"""central_bank_purchases 表：按国家 × 季度的央行净购金（吨）

Revision ID: c1b3a1d27e9f
Revises: d39845be5408
Create Date: 2026-09-09 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c1b3a1d27e9f"
down_revision: Union[str, Sequence[str], None] = "d39845be5408"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "central_bank_purchases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "country_iso",
            sa.String(length=3),
            nullable=False,
            comment="ISO 3 字母代码",
        ),
        sa.Column(
            "country_name",
            sa.String(length=64),
            nullable=False,
            comment="国家中文名",
        ),
        sa.Column(
            "quarter",
            sa.String(length=6),
            nullable=False,
            comment="季度，如 2026Q2",
        ),
        sa.Column(
            "tonnes_net",
            sa.Float(),
            nullable=False,
            comment="季度净购金（吨），正=买入/负=卖出",
        ),
        sa.Column(
            "source",
            sa.String(length=32),
            nullable=False,
            server_default="IMF IRFCL",
            comment="数据源：IMF IRFCL / WGC 手工",
        ),
        sa.Column(
            "data_date",
            sa.Date(),
            nullable=False,
            comment="数据截止日（季度最后一日）",
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("country_iso", "quarter", name="uq_cb_country_quarter"),
    )
    op.create_index(
        op.f("ix_central_bank_purchases_country_iso"),
        "central_bank_purchases",
        ["country_iso"],
        unique=False,
    )
    op.create_index(
        op.f("ix_central_bank_purchases_quarter"),
        "central_bank_purchases",
        ["quarter"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_central_bank_purchases_quarter"), table_name="central_bank_purchases"
    )
    op.drop_index(
        op.f("ix_central_bank_purchases_country_iso"),
        table_name="central_bank_purchases",
    )
    op.drop_table("central_bank_purchases")
