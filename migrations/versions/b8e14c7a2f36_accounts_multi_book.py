"""单用户多账本：新增 accounts 表 + positions.account_id（P1 #6）

Revision ID: b8e14c7a2f36
Revises: c1b3a1d27e9f
Create Date: 2026-09-13 06:00:00.000000

迁移策略（SQLite 友好、可重复执行）
----------------------------------
1. 建 ``accounts`` 表；
2. **幂等**插入 id=1 的「默认账户」（``is_default=1``）——历史数据全部归入该账本；
3. 给 ``positions`` 加 ``account_id`` 列，server_default="1"（SQLite 对已有行回填默认值）；
4. 兜底把 ``account_id IS NULL`` 的行置 1（老库经运行时补列路径进入时可能为 NULL）；
5. 建 ``ix_positions_account_id`` 索引。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b8e14c7a2f36"
down_revision: Union[str, Sequence[str], None] = "c1b3a1d27e9f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment="预留多用户，当前单用户=1",
        ),
        sa.Column(
            "name", sa.String(length=64), nullable=False, comment="账本名称，如 主账户 / 家人账户"
        ),
        sa.Column(
            "note", sa.String(length=255), nullable=False, server_default="", comment="备注"
        ),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default="0",
            comment="是否为默认账本",
        ),
        sa.Column(
            "sort_order", sa.Integer(), nullable=False, server_default="0", comment="展示排序"
        ),
        sa.Column(
            "archived_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="归档时间戳；非空表示已归档（可恢复）",
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
    )
    op.create_index(op.f("ix_accounts_user_id"), "accounts", ["user_id"], unique=False)

    # 幂等 seed 默认账本：历史持仓/流水全部归入 id=1
    op.execute(
        "INSERT INTO accounts (id, user_id, name, note, is_default, sort_order) "
        "SELECT 1, 1, '默认账户', 'V0.62.0 迁移：既有持仓与流水归入此账本', 1, 0 "
        "WHERE NOT EXISTS (SELECT 1 FROM accounts)"
    )

    op.add_column(
        "positions",
        sa.Column(
            "account_id",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment="所属账本（单用户多账本，P1 #6）",
        ),
    )
    op.execute("UPDATE positions SET account_id = 1 WHERE account_id IS NULL")
    op.create_index(
        op.f("ix_positions_account_id"), "positions", ["account_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_positions_account_id"), table_name="positions")
    with op.batch_alter_table("positions") as batch:
        batch.drop_column("account_id")
    op.drop_index(op.f("ix_accounts_user_id"), table_name="accounts")
    op.drop_table("accounts")
