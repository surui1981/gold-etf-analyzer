"""news_feed_daily 表新增（V0.107 · 按 BJT 日聚合 + 合并 n0a1b2c3d4 / n0o1p2q3r4 双 head）

Revision ID: n1o2p3q4r5
Revises: n0a1b2c3d4, n0o1p2q3r4
Create Date: 2026-10-19 18:00:00.000000

迁移背景
----------
V0.102 起 ``news_feed_items`` 表（共享上下文，无 user_id）已积累约 30 天
readhub 财经新闻。V0.105 加类目列（财经/科技/创投/商业/其他）后，UI 「今日要闻」
顶部的「财经 X · 科技 Y · 共 N 条」类摘要**每次**都靠 ``GROUP BY`` 实时算
（~30 天 × 1 次查询 ~5-20ms），规模化后慢；同时**没有持久化的按日快照**可被
``/headlines`` / ``/home`` 直接读取。

V0.107 引入 ``news_feed_daily`` 物化宽表（仿 ``scoring_daily_wide`` 的
date-as-PK 模式），**1 日 1 行**：

- refresh 后由 ``NewsFeedService.rebuild_daily(target_date)`` 重建当天行
- 启动 lifespan 由 ``backfill_daily(start_date, end_date)`` 一次性回填 30 天
- UI 直接读聚合表（O(1) 行）替代实时 ``GROUP BY``

合并双 head
-----------
V0.103 收藏表（``n0a1b2c3d4``）和 V0.105 类目列（``n0o1p2q3r4``）从
``m9g0a1b2c3``（V0.102 news_feed_items）分叉后**未合并**，导致
``alembic heads`` 返回 2 个 head。V0.107 这次迁移同时承担「合并双 head」+「新建
news_feed_daily 表」两个职责：

- ``down_revision`` = (``n0a1b2c3d4``, ``n0o1p2q3r4``)（tuple）→ 自动合并
- 升级路径：``n0a1b2c3d4 + n0o1p2q3r4 → n1o2p3q4r5``
- 之后是单一 head，未来 V0.108+ 不会再出现多 head 状态

迁移策略（SQLite 友好、可重复执行）
----------------------------------
- 仿 ``i5d6e7f8a9b0_scoring_daily_wide.py`` 的 ``_table_exists()`` 幂等保护
- ``op.create_table(...)`` 1 次 + 1 个 UNIQUE PK 约束（隐含）
- **不**在迁移里做 data backfill（启动 lifespan 阶段由
  ``backfill_daily()`` 独立处理，~~避免阻塞 alembic upgrade head~~）

字段约定
--------
- ``date`` 主键：BJT 日期（YYYY-MM-DD）
- 5 类目计数：finance / tech / vc / biz / other
- ``unique_sites_count``：独立来源站数
- ``en_count`` / ``zh_count``：按 language 区分
- ``first_publish_at`` / ``last_publish_at``：当日首末发布时间（UTC，可能为 NULL）
- ``last_refresh_at``：最近一次 refresh 触发本行重建的时间（UTC）
- ``created_at`` / ``updated_at``：元字段

⚠ V0.80.0 #159 教训：news 是 shared context，**不挂 user_id**（与
   ``news_feed_items`` 一致）。
⚠ **回滚策略** ``downgrade()`` 删表 —— 历史聚合数据可由
   ``NewsFeedService.backfill_daily()`` 重建（启动 lifespan 阶段）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "n1o2p3q4r5"
# tuple down_revision = merge 2 heads（n0a1b2c3d4 V0.103 收藏 + n0o1p2q3r4 V0.105 类目）
down_revision: str | Sequence[str] | None = ("n0a1b2c3d4", "n0o1p2q3r4")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists() -> bool:
    """探测 ``news_feed_daily`` 是否已存在（保证可重复执行）。"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return "news_feed_daily" in inspector.get_table_names()


def upgrade() -> None:
    """建 news_feed_daily 表（date 主键 + 5 类目 + 站点/语种/时间字段）。"""
    if _table_exists():
        return
    op.create_table(
        "news_feed_daily",
        sa.Column(
            "date",
            sa.Date(),
            primary_key=True,
            nullable=False,
            comment="BJT 日期（YYYY-MM-DD，1 日 1 行）",
        ),
        sa.Column(
            "total_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="当日新闻总条数（含未分类）",
        ),
        sa.Column(
            "finance_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="财经类目条数",
        ),
        sa.Column(
            "tech_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="科技类目条数",
        ),
        sa.Column(
            "vc_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="创投类目条数",
        ),
        sa.Column(
            "biz_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="商业类目条数",
        ),
        sa.Column(
            "other_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="其他类目条数",
        ),
        sa.Column(
            "unique_sites_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="当日独立来源站数",
        ),
        sa.Column(
            "en_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="英文条数（language='en'）",
        ),
        sa.Column(
            "zh_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="中文条数（language 任意 zh- 前缀）",
        ),
        sa.Column(
            "first_publish_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="当日首篇发布时间（UTC）",
        ),
        sa.Column(
            "last_publish_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="当日末篇发布时间（UTC）",
        ),
        sa.Column(
            "last_refresh_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="最近一次 refresh 触发本行重建的时间（UTC）",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    """删 news_feed_daily 表（PK 索引自动跟随 drop）。"""
    if not _table_exists():
        return
    op.drop_table("news_feed_daily")
