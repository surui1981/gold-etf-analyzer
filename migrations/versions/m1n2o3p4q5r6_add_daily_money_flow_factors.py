"""daily_money_flow_factors 表新增（V0.120.0 · 资金流面）

Revision ID: m1n2o3p4q5r6
Revises: s1t2u3v4w5x
Create Date: 2026-10-27 10:00:00.000000

新建 ``daily_money_flow_factors`` 表，存资金流因子**原始 value**（输入），
供 ``MacroThresholdCalculator``（按因子 ``window_days``）算滚动 90/10 分位。

⚠ 与 ``daily_macro_factors`` 的关键差异：``snapshot_date`` 存的是
**因子自身的观测日**（CFTC 周二 / 月末 / 周四），**不是采集日**。
周频 / 月频因子若按采集日逐日落表，同一个值会被重复 5 次 / 21 次
⇒ 滚动分位窗口里 P10 == P90 ⇒ 阈值退化。

唯一键 ``(target, snapshot_date, factor_key)`` 保证幂等。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "m1n2o3p4q5r6"
down_revision: Union[str, Sequence[str], None] = "s1t2u3v4w5x"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn) -> bool:
    """表是否已存在（幂等守卫，同族迁移惯例）。"""
    return sa.inspect(conn).has_table("daily_money_flow_factors")


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    if _table_exists(conn):
        return
    op.create_table(
        "daily_money_flow_factors",
        # ⚠ ``primary_key=True`` 不能少：SQLite 的 ``INTEGER PRIMARY KEY`` 才是
        # rowid 的别名（自增主键靠它）。只写 ``INTEGER NOT NULL`` 的话，
        # 每条 INSERT 都必须显式给 id ⇒ 任何 ORM insert 直接
        # 「NOT NULL constraint failed: daily_money_flow_factors.id」。
        # （``daily_macro_factors`` 用的是同款写法，所以它一直是对的。）
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "target",
            sa.String(length=16),
            nullable=False,
            comment='标的维度（默认 "default"）',
        ),
        sa.Column(
            "snapshot_date",
            sa.Date(),
            nullable=False,
            comment="因子自身的观测日（不是采集日）",
        ),
        sa.Column(
            "factor_key",
            sa.String(length=32),
            nullable=False,
            comment="资金流因子 key",
        ),
        sa.Column("value", sa.Float(), nullable=False, comment="该次观测的原始数值"),
        sa.Column(
            "data_date",
            sa.String(length=32),
            nullable=False,
            server_default="",
            comment="口径说明（自由文本）",
        ),
        sa.Column(
            "source",
            sa.String(length=48),
            nullable=False,
            server_default="",
            comment="数据源标识",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "target",
            "snapshot_date",
            "factor_key",
            name="uq_dmff_target_date_factor",
        ),
    )
    op.create_index(
        "idx_dmff_snapshot_target",
        "daily_money_flow_factors",
        ["snapshot_date", "target"],
    )
    op.create_index(
        "idx_dmff_factor_target_date_desc",
        "daily_money_flow_factors",
        ["factor_key", "target", "snapshot_date"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    if not _table_exists(conn):
        return
    op.drop_index(
        "idx_dmff_factor_target_date_desc",
        table_name="daily_money_flow_factors",
    )
    op.drop_index("idx_dmff_snapshot_target", table_name="daily_money_flow_factors")
    op.drop_table("daily_money_flow_factors")
