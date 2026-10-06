"""merge e1f2a3b4c5d6 (tech_detail) 和 f2a3b4c5d6e7 (snapshot_data_source)

Revision ID: h4c5d6e7f8a9
Revises: e1f2a3b4c5d6, f2a3b4c5d6e7
Create Date: 2026-10-06 09:30:00.000000

合并两个 head 分支，为 V0.79.0 Step E daily_macro_factors 表迁移铺平路径。
本迁移是纯空 migration（无 schema 变更），仅声明依赖关系。
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "h4c5d6e7f8a9"
down_revision: str | Sequence[str] | None = ("e1f2a3b4c5d6", "f2a3b4c5d6e7")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema. 空操作：仅声明依赖关系。"""
    pass


def downgrade() -> None:
    """Downgrade schema. 空操作。"""
    pass
