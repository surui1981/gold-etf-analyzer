"""修正 daily_money_flow_factors 的主键（V0.120.0 hotfix）

Revision ID: n2o3p4q5r6a1
Revises: m1n2o3p4q5r6
Create Date: 2026-10-27 21:00:00.000000

背景（实测踩到的坑）
--------------------
``m1n2o3p4q5r6`` 建表时把 id 声明成 ``sa.Column("id", sa.Integer(),
autoincrement=True, nullable=False)`` —— **漏了 ``primary_key=True``**。

SQLite 的 ``INTEGER PRIMARY KEY`` 才是 rowid 的别名（自增靠它）。只写
``INTEGER NOT NULL`` 的话 id 就是普通 NOT NULL 列、没有默认值 ⇒
**每条 INSERT 都必须显式给 id**，ORM 的 insert 直接炸：

    IntegrityError: NOT NULL constraint failed: daily_money_flow_factors.id

（同一批脚本里 ``daily_macro_factors`` 用的是 ``primary_key=True``，
所以它一直是对的 —— 这也说明「照抄兄弟表的迁移」比「照抄兄弟表的一半」安全。）

修法
----
重建表：新建带正确主键的表 → 拷数据 → 删旧表 → 改名。
数据**不丢**（虽然建表至今 0 行，但重建逻辑按有数据写）。

幂等：表已带正确主键时直接返回。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "n2o3p4q5r6a1"
down_revision: Union[str, Sequence[str], None] = "m1n2o3p4q5r6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "daily_money_flow_factors"
TMP_TABLE = "daily_money_flow_factors_pkfix"


def _has_pk(conn) -> bool:
    """id 是否已经是主键。"""
    insp = sa.inspect(conn)
    if not insp.has_table(TABLE):
        return True
    pk = insp.get_pk_constraint(TABLE).get("constrained_columns") or []
    return "id" in pk


def _table_exists(conn) -> bool:
    return sa.inspect(conn).has_table(TABLE)


def upgrade() -> None:
    """重建表，补上缺失的主键。"""
    conn = op.get_bind()
    if not _table_exists(conn):
        return
    if _has_pk(conn):
        return

    op.create_table(
        TMP_TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("target", sa.String(length=16), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("factor_key", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("data_date", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=48), nullable=False, server_default=""),
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
    conn.execute(
        sa.text(
            f"INSERT INTO {TMP_TABLE} "
            "(target, snapshot_date, factor_key, value, data_date, source, created_at) "
            f"SELECT target, snapshot_date, factor_key, value, data_date, source, created_at "
            f"FROM {TABLE}"
        )
    )
    op.drop_table(TABLE)
    op.rename_table(TMP_TABLE, TABLE)
    op.create_index("idx_dmff_snapshot_target", TABLE, ["snapshot_date", "target"])
    op.create_index("idx_dmff_factor_target_date_desc", TABLE, ["factor_key", "target", "snapshot_date"])


def downgrade() -> None:
    """回退：重建回无主键的表（几乎不可能走到，仅为 alembic 完整性）。"""
    conn = op.get_bind()
    if not _table_exists(conn) or not _has_pk(conn):
        return
    op.create_table(
        TMP_TABLE,
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("target", sa.String(length=16), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("factor_key", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("data_date", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=48), nullable=False, server_default=""),
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
    conn.execute(
        sa.text(
            f"INSERT INTO {TMP_TABLE} "
            "(target, snapshot_date, factor_key, value, data_date, source, created_at) "
            f"SELECT target, snapshot_date, factor_key, value, data_date, source, created_at "
            f"FROM {TABLE}"
        )
    )
    op.drop_table(TABLE)
    op.rename_table(TMP_TABLE, TABLE)
    op.create_index("idx_dmff_snapshot_target", TABLE, ["snapshot_date", "target"])
    op.create_index("idx_dmff_factor_target_date_desc", TABLE, ["factor_key", "target", "snapshot_date"])
