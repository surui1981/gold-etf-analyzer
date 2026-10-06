"""daily_macro_factors 表新增（V0.79.0 · Step E）

Revision ID: g3b4c5d6e7f8
Revises: e1f2a3b4c5d6
Create Date: 2026-10-06 09:00:00.000000

迁移策略（SQLite 友好、可重复执行）
----------------------------------
新建 ``daily_macro_factors`` 表，存每日宏观因子**原始 value**（输入），
与 ``daily_snapshots.macro_detail``（已 score 结果）互为备份。

为什么需要
----------
- V0.79.0 Step E 要把 ``MACRO_FACTOR_RULES`` 的静态 ``best/worst``
  替换成「近 252 个交易日滚动 90/10 分位」；
- ``daily_snapshots.macro_detail`` 只存 score，缺 raw value → 滚动百分位
  算不出来；
- ``daily_macro_factors`` 时序化 raw value，每日 07:00 BJT 调度 upsert，
  唯一键 ``(target, snapshot_date, factor_key)`` 保证幂等。

字段约定
--------
- ``target``：默认 ``"default"``（5 因子全市场共享源，target 维度留给后续重写）；
- ``factor_key``：dxy / us10y / us30y / vix / cb_gold 五种之一；
- ``data_date``：因子本身的数据日期（cb_gold 可能跨季度，写成
  ``"2025Q3–2026Q2 滚动12月"`` 形式）；
- ``snapshot_date``：采集日，每日一条，滚动窗口的天然粒度。

⚠ **回滚策略**
``downgrade()`` 删表 —— 历史 raw value 不可重建（采集当时的快照数据已过期），
但因为本表与 ``macro_detail``（score）互为备份，删表不影响最终评分能力。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "g3b4c5d6e7f8"
down_revision: str | Sequence[str] | None = "h4c5d6e7f8a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists() -> bool:
    """探测 ``daily_macro_factors`` 是否已存在（保证可重复执行）。"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return "daily_macro_factors" in inspector.get_table_names()


def upgrade() -> None:
    """Upgrade schema."""
    if _table_exists():
        return
    op.create_table(
        "daily_macro_factors",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "target",
            sa.String(length=16),
            nullable=False,
            comment='标的维度（默认 "default" — 5 因子全市场共享源）',
        ),
        sa.Column(
            "snapshot_date",
            sa.Date(),
            nullable=False,
            comment="采集日（滚动窗口的天然粒度）",
        ),
        sa.Column(
            "factor_key",
            sa.String(length=16),
            nullable=False,
            comment="dxy / us10y / us30y / vix / cb_gold",
        ),
        sa.Column(
            "value",
            sa.Float(),
            nullable=False,
            comment="当日该因子原始数值",
        ),
        sa.Column(
            "data_date",
            sa.String(length=32),
            nullable=False,
            comment='因子本身的数据日期（cb_gold 写 "2025Q3–2026Q2" 形式）',
        ),
        sa.Column(
            "source",
            sa.String(length=32),
            nullable=False,
            server_default="",
            comment='数据源标识（"美联储 H.15" / "静态参考值" / "央行购金表自动汇总"）',
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "target",
            "snapshot_date",
            "factor_key",
            name="uq_dmf_target_date_factor",
        ),
    )
    # 索引：滚动窗口范围查询走 (snapshot_date, target)
    op.create_index(
        "idx_dmf_snapshot_target",
        "daily_macro_factors",
        ["snapshot_date", "target"],
    )
    # 索引：因子 + target + 日期倒序（回溯单因子历史窗口）
    op.create_index(
        "idx_dmf_factor_target_date_desc",
        "daily_macro_factors",
        ["factor_key", "target", "snapshot_date"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    if not _table_exists():
        return
    op.drop_index("idx_dmf_factor_target_date_desc", table_name="daily_macro_factors")
    op.drop_index("idx_dmf_snapshot_target", table_name="daily_macro_factors")
    op.drop_table("daily_macro_factors")
