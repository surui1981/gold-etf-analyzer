"""news_feed 多源化：external_id 改文本 + UNIQUE 改复合 + url 可空（V0.114.0）

Revision ID: q3r4s5t6u7
Revises: p2q3r4s5t6
Create Date: 2026-10-22 00:00:00.000000

迁移背景
----------
V0.102 至今新闻流只有 readhub **一个**源，单点无冗余（本轮实测中 readhub 已超时
过一次）。V0.114.0 接入华尔街见闻 / 金十数据 / 东方财富三源做链式 failover，
这直接撞上三处单源时代留下的结构假设：

1. ``news_feed_items.external_id`` 是 ``Integer`` + **单列** UNIQUE
   - 金十的 id 是 20 位数字串（``20261022052115590800``）。⚠ 实测发现它连
     **int64 都装不下**：SQLite ``INTEGER`` 是有符号 64 位（上限
     9223372036854775807 ≈ 9.22e18），而该 id ≈ 2.02e19，是上限的 2.2 倍。
     绑值时直接抛 ``OverflowError: Python int too large to convert to
     SQLite INTEGER`` —— 改 BigInteger **不够**，列类型必须是文本
   - 四个源的 id 空间互不相干，单列 UNIQUE 必然撞车（华尔街见闻 700 万级 vs
     金十 2e19 起点，理论上会同时存在同号不同源的两条新闻）

2. ``url`` NOT NULL
   - 金十 / 东方财富的快讯接口**根本没有** URL 字段（实测 30/30 条无链接）
   - V0.78.0 NULL 纪律 + V0.77.1「不给假 affordance」⇒ 存 NULL，UI 渲染成
     **不可点的纯文本**，而不是合成 ``#`` 假链接

3. ``user_news_favorites.url`` NOT NULL + ``news_external_id`` Integer
   - 收藏走全量快照，源条目 URL 为空时快照也为空 ⇒ 原先的必填校验会 422
     把这类条目挡在收藏之外（实测：url-less 条目**根本收藏不了**）
   - ``news_external_id`` 同样要扩 BigInteger，否则金十条目收藏也会溢出

迁移策略
--------
- 全部走 ``batch_alter_table``（SQLite 不支持直接 ALTER COLUMN / 改约束）
- **无数据迁移**：readhub 历史行的 ``external_id`` 原值不变、``source`` 早已是
  ``'readhub'``（``server_default`` + 列存在）⇒ 新复合 UNIQUE 下语义等价
- ``_table_exists()`` 幂等守卫：``main._migrate_db()`` 在 alembic 失败时会回退
  ``Base.metadata.create_all``，两条路径都跑过时第二次启动必须安全跳过
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "q3r4s5t6u7"
down_revision: str | Sequence[str] | None = "p2q3r4s5t6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 旧单列 UNIQUE 约束名（models/news_feed.py 的 UniqueConstraint name）
_OLD_UQ = "uq_news_feed_external_id"
_NEW_UQ = "uq_news_feed_source_external"


def _table_exists(name: str) -> bool:
    """表是否已存在（幂等守卫，仿 n1o2p3q4r5_news_feed_daily.py）。"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return name in inspector.get_table_names()


def upgrade() -> None:
    """多源化 news_feed_items + 放宽 user_news_favorites 的 url / id。"""
    if _table_exists("news_feed_items"):
        with op.batch_alter_table("news_feed_items") as batch:
            # 金十 id ≈2.02e19 超出 int64 ⇒ 必须 String（BigInteger 不够）
            batch.alter_column(
                "external_id",
                existing_type=sa.Integer(),
                type_=sa.String(length=32),
                existing_nullable=False,
            )
            # 金十 / 东财无 URL ⇒ NULL 纪律，UI 侧渲染成不可点纯文本
            batch.alter_column(
                "url",
                existing_type=sa.Text(),
                nullable=True,
                existing_comment="原文链接（浏览器外链跳转）",
            )
            # 单列 UNIQUE → (source, external_id) 复合
            batch.drop_constraint(_OLD_UQ, type_="unique")
            batch.create_unique_constraint(_NEW_UQ, ["source", "external_id"])

    if _table_exists("user_news_favorites"):
        with op.batch_alter_table("user_news_favorites") as batch:
            batch.alter_column(
                "news_external_id",
                existing_type=sa.Integer(),
                type_=sa.String(length=32),
                existing_nullable=False,
            )
            batch.alter_column(
                "url",
                existing_type=sa.Text(),
                nullable=True,
                existing_comment="收藏时的原文链接快照（直接打开此 URL，不回查源表）",
            )


def downgrade() -> None:
    """回退到单源结构。

    ⚠ **不可逆**：复合 UNIQUE 无法还原成单列 —— 四源数据已经存在同一个
    ``external_id`` 上，强行还原会在建约束时报 UNIQUE violation。
    列类型**不回退成 Integer** —— 金十 20 位 id 会被 SQLite 拒绝绑值。
    调用方必须先清理非 readhub 数据再 downgrade。
    """
    if _table_exists("news_feed_items"):
        with op.batch_alter_table("news_feed_items") as batch:
            batch.drop_constraint(_NEW_UQ, type_="unique")
            batch.create_unique_constraint(_OLD_UQ, ["external_id"])
            batch.alter_column(
                "url",
                existing_type=sa.Text(),
                nullable=False,
                existing_comment="原文链接（浏览器外链跳转）",
            )
    if _table_exists("user_news_favorites"):
        with op.batch_alter_table("user_news_favorites") as batch:
            batch.alter_column(
                "url",
                existing_type=sa.Text(),
                nullable=False,
                existing_comment="收藏时的原文链接快照（直接打开此 URL，不回查源表）",
            )