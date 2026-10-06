"""daily_snapshots 增 data_source 列（V0.79.0 · 任务 #163）

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-10-06 09:45:00.000000

迁移策略（SQLite 友好、可重复执行）
----------------------------------
``daily_snapshots`` 新增可空列 ``data_source``（VARCHAR(16)），
记录该日快照的行情来源：``live`` / ``stale`` / ``mock``。

为什么需要（2026-10-06 实测根因）
--------------------------------
24 条历史快照中，**5 条的 ``close`` 值完全相同**（4725.07），
逐日对照真实 K 线后确认那是 **mock 序列的末值**：

- ``_mock_us_history()`` 以 ``base=4430.0`` 按「距今天数」生成确定性序列；
- subprocess 取数失败 → 仓储降级 mock → ``capture_today()`` **照样落库**；
- 而快照此前**没有任何来源标记** ⇒ 事后无法区分真值与 mock 产物。

⚠ 讽刺之处：``_us_gold_via_subprocess`` 恰好在**今天**返回了 4725.07
（真实 10-05 收盘价），与历史快照里的 mock 值撞号 —— 所以「值相同」是巧合，
不能作为判据，**必须有显式来源列**。

⚠ **历史行保持 NULL，不回填**
NULL 表示「未标记」，**不可当作 live**。理由：那 5 条 mock 行无法事后准确区分
（无时间戳记录当时的 mock 末值），若猜测回填等于伪造溯源信息。
下游（回测）须把 NULL 视为「来源未知」并排除或单独统计。

``create_all`` 不会给已存在的表加列，本迁移是新建库之外路径的必需项；
老库另有 ``utils/db_migrate.py`` 的幂等补列兜底（两处都声明，双保险）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists() -> bool:
    """探测 ``daily_snapshots.data_source`` 是否已存在（保证可重复执行）。

    ⚠ Alembic 迁移通常只跑一次，但本仓要求迁移**可重复执行**
    （老库经 ``db_migrate.py`` 补过列时，``upgrade head`` 仍会执行到这里），
    故必须先探测再 ADD COLUMN，否则「已补列的老库」会因
    ``duplicate column name`` 而升级失败。
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "daily_snapshots" not in inspector.get_table_names():
        return True  # 表不存在（新建库由 create_all 负责），跳过
    return any(c["name"] == "data_source" for c in inspector.get_columns("daily_snapshots"))


def upgrade() -> None:
    """Upgrade schema."""
    if _column_exists():
        return
    op.add_column(
        "daily_snapshots",
        sa.Column(
            "data_source",
            sa.String(length=16),
            nullable=True,
            comment="行情来源 live/stale/mock（V0.79.0；NULL=未标记，不可当作 live）",
        ),
    )


def downgrade() -> None:
    """Downgrade schema.

    ⚠ 本列是**溯源信息**，删列会永久失去「哪些快照是 mock 产物」的能力。
    宁可报错也不静默丢数据。
    """
    if _column_exists():
        op.drop_column("daily_snapshots", "data_source")
