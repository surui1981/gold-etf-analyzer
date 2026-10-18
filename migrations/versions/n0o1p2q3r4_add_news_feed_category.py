"""news_feed_items 加 category 列（V0.105 关键词分类）

Revision ID: n0o1p2q3r4
Revises: m9g0a1b2c3
Create Date: 2026-10-19 12:00:00.000000

迁移背景
----------
V0.102 引入 ``news_feed_items`` 表作为 readhub 财经新闻流。V0.105 加类目筛选
（财经/科技/创投/商业/其他），需要：

- 在 ``news_feed_items`` 加 ``category`` 列（VARCHAR(16) NULL）
- 索引：UI 顶部类目筛选 + ``/api/v1/news-feed/categories`` distinct 查询
- 启动时由 ``NewsFeedRepository.backfill_categories()`` 一次性补齐
  历史数据；**不**在迁移里做 backfill（避免阻塞 alembic upgrade head）

迁移策略
--------
- **加列 + 索引**（additive migration），**不**动现有数据
- ``category=NULL`` 视为「未分类」，由启动钩子补齐
- 严格遵循 V0.79.0 #162 纪律：「不挂 user_id」「不动现有表结构」（仅加列）

为何 nullable
------------
- 历史 ~64378 行一次性分类不现实（迁移里跑 5-10s 会卡 alembic 锁）
- 启动钩子里跑（lifespan 阶段）可独立日志、可重试
- NULL 纪律（V0.78.0）：「未分类就是 NULL」

与既有迁移的关系
----------------
- 紧随 ``m9g0a1b2c3_news_feed_items`` 之后
- 之后是 ``n0a1b2c3d4_user_news_favorites`` —— V0.103 收藏
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "n0o1p2q3r4"
down_revision: str | Sequence[str] | None = "m9g0a1b2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """加 category 列 + 索引（V0.105 类目筛选用）。"""
    op.add_column(
        "news_feed_items",
        sa.Column(
            "category",
            sa.String(length=16),
            nullable=True,
            comment="V0.105 分类（财经/科技/创投/商业/其他），_normalize() 关键词分类器填入；启动 backfill_categories() 一次性补齐历史",
        ),
    )
    op.create_index(
        op.f("ix_news_feed_items_category"),
        "news_feed_items",
        ["category"],
        unique=False,
    )


def downgrade() -> None:
    """删 category 索引 + 列（V0.105 回滚用）。"""
    op.drop_index(op.f("ix_news_feed_items_category"), table_name="news_feed_items")
    op.drop_column("news_feed_items", "category")
