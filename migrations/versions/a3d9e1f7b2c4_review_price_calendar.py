"""研判复盘：新增 gold_price_daily 价格日历 + news_scores 研判依据字段（V0.66.0）

Revision ID: a3d9e1f7b2c4
Revises: f2a7b4c9d1e3
Create Date: 2026-09-16 15:10:00.000000

迁移策略（SQLite 友好、可重复执行）
----------------------------------
1. 新建 ``gold_price_daily``：按 (target, price_date) 唯一的客观价格日历，
   作为「当日研判 → 之后 N 个交易日表现」的对比基准。历史可由行情接口回填。
2. ``news_scores`` 增加三列：
   - ``basis``：研判依据标签（JSON 数组字符串）
   - ``review_note``：事后复盘批注
   - ``backfilled``：补录标记（1=事后补录，统计默认排除，避免前视偏差）

说明：``gold_price_daily`` 属新表，``create_all`` 亦可创建；此处显式声明
以保证 Alembic 链条完整（``upgrade head`` 一次到位）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a3d9e1f7b2c4"
down_revision: Union[str, Sequence[str], None] = "f2a7b4c9d1e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "gold_price_daily",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("target", sa.String(length=8), nullable=False, server_default="ny",
                  comment="标的：ny/etf/gram"),
        sa.Column("price_date", sa.Date(), nullable=False, comment="交易日"),
        sa.Column("close", sa.Float(), nullable=False, comment="当日收盘价"),
        sa.Column("change_pct", sa.Float(), nullable=False, server_default="0",
                  comment="相对前一交易日的涨跌幅 %"),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="",
                  comment="数据来源标识"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("target", "price_date", name="uq_gold_price_target_date"),
    )
    op.create_index(
        op.f("ix_gold_price_daily_price_date"), "gold_price_daily", ["price_date"], unique=False
    )

    op.add_column(
        "news_scores",
        sa.Column("basis", sa.Text(), nullable=False, server_default="",
                  comment="研判依据标签（JSON 数组字符串）"),
    )
    op.add_column(
        "news_scores",
        sa.Column("review_note", sa.Text(), nullable=False, server_default="",
                  comment="事后复盘批注"),
    )
    op.add_column(
        "news_scores",
        sa.Column("backfilled", sa.Integer(), nullable=False, server_default="0",
                  comment="1=事后补录（统计默认排除）"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("news_scores") as batch:
        batch.drop_column("backfilled")
        batch.drop_column("review_note")
        batch.drop_column("basis")

    op.drop_index(op.f("ix_gold_price_daily_price_date"), table_name="gold_price_daily")
    op.drop_table("gold_price_daily")
