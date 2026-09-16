"""消息面每日 3 次打分：news_scores 增加 slot/scored_at + 复合唯一索引（V0.65.0）

Revision ID: f2a7b4c9d1e3
Revises: b8e14c7a2f36
Create Date: 2026-09-16 14:20:00.000000

迁移策略（SQLite 友好、可重复执行）
----------------------------------
1. 新增 ``slot``（当日第几次打分，1-3，默认 1）与 ``scored_at``（该次提交时刻）；
2. 存量行 ``scored_at`` 回填 ``updated_at``，保持时间语义；
3. 删除旧的 ``score_date`` 唯一索引 ``ix_news_scores_score_date``
   —— 不删则同一日期无法写入第 2/3 次打分（写入会被唯一约束拒绝）；
4. 建复合唯一索引 ``uq_news_scores_date_slot``(score_date, slot)，
   即「同一天每个槽位最多一条」。

说明：``scored_at`` 在 SQLite 的 ALTER TABLE 中无法以 CURRENT_TIMESTAMP 作为
默认值，故先按可空列加入再回填，与运行时补列路径（``utils/db_migrate.py``）保持一致。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f2a7b4c9d1e3"
down_revision: Union[str, Sequence[str], None] = "b8e14c7a2f36"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "news_scores",
        sa.Column(
            "slot",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment="当日第几次打分：1/2/3",
        ),
    )
    op.add_column(
        "news_scores",
        sa.Column(
            "scored_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="该次打分的提交时刻",
        ),
    )

    # 存量行（旧模型每日一条）统一归入第 1 次，并用 updated_at 回填打分时刻
    op.execute("UPDATE news_scores SET slot = 1 WHERE slot IS NULL")
    op.execute("UPDATE news_scores SET scored_at = updated_at WHERE scored_at IS NULL")

    # 放开「每日一条」约束
    op.execute("DROP INDEX IF EXISTS ix_news_scores_score_date")

    # 同一天每个槽位最多一条
    op.create_index(
        "uq_news_scores_date_slot",
        "news_scores",
        ["score_date", "slot"],
        unique=True,
    )
    op.create_index(
        op.f("ix_news_scores_score_date"),
        "news_scores",
        ["score_date"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_news_scores_date_slot", table_name="news_scores")
    op.drop_index(op.f("ix_news_scores_score_date"), table_name="news_scores")

    # 回退到「每日一条」：仅保留每个日期 slot 最小的一条
    op.execute(
        "DELETE FROM news_scores WHERE id NOT IN "
        "(SELECT MIN(id) FROM news_scores GROUP BY score_date)"
    )
    op.create_index(
        op.f("ix_news_scores_score_date"),
        "news_scores",
        ["score_date"],
        unique=True,
    )

    with op.batch_alter_table("news_scores") as batch:
        batch.drop_column("scored_at")
        batch.drop_column("slot")
