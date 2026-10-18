"""news_feed_items 表：readhub 财经新闻流（V0.102）

Revision ID: m9g0a1b2c3
Revises: l8f9a0b1c2
Create Date: 2026-10-19 01:00:00.000000

迁移背景
----------
V0.100.0 之前所有数据来自「本应用产生或采购」—— 行情、用户打分、央行购金、推送告警。
「外部财经新闻」这一类**完全空白**：用户在 /ask 与 AI 助手对话时，模型只看到本应用
的 5 类只读 tool（market / scoring / portfolio / warning / etf_flows），拿不到当下
宏观新闻 + 同行研判的**实时上下文**。

V0.102 起新增「今日要闻」页（/news-feed）：
- 后台每 6 小时从 readhub 内部 API（``https://api.readhub.cn/news``，非官方但匿名
  稳定，无 429）抓取最新 ~20 条
- 落 ``news_feed_items`` 表，本地存
- 前端列表页按日期 + 来源 + 关键词筛选 + 跳原文

迁移策略
--------
- 单表，**完全不碰**既有表（V0.79.0 #162 纪律）
- ``external_id`` 是 readhub 自增主键，整型；唯一约束做 dedup（同一新闻不重复入库）
- ``site_name`` + ``language`` 单列索引，UI 频繁按来源/语种筛选
- ``publish_date`` 索引，UI 按日期倒序展示
- ``fetched_at`` 单列索引，scheduler 算「过去 24h 新增」用
- ``source`` 字段预留，默认 "readhub"，未来可接 华尔街见闻 / 36Kr / 财联社
- 所有 nullable 字段遵循 NULL 纪律（V0.78.0）：「未知就是未知，不是 0 不是 ''」

⚠ V0.80.0 #159 教训：本表**不挂 user_id** —— 财经新闻是**共享上下文**（不是用户
   私有数据），多用户模式下不隔离。AI 助手读取也只看全局视图。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "m9g0a1b2c3"
down_revision: str | Sequence[str] | None = "l8f9a0b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """建 news_feed_items 表 + 5 索引。"""
    op.create_table(
        "news_feed_items",
        sa.Column(
            "id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
            comment="本地自增主键",
        ),
        sa.Column(
            "external_id",
            sa.Integer(),
            nullable=False,
            comment="readhub 的 news id（dedup 主键）",
        ),
        sa.Column(
            "title",
            sa.Text(),
            nullable=False,
            comment="新闻标题",
        ),
        sa.Column(
            "summary",
            sa.Text(),
            nullable=False,
            server_default="",
            comment="新闻摘要（readhub 自带）",
        ),
        sa.Column(
            "url",
            sa.Text(),
            nullable=False,
            comment="原文链接（打开浏览器外链跳转）",
        ),
        sa.Column(
            "mobile_url",
            sa.Text(),
            nullable=True,
            comment="移动端链接（如有）",
        ),
        sa.Column(
            "site_name",
            sa.String(64),
            nullable=False,
            comment="来源站（华尔街见闻 / 36Kr / 财联社 / 格隆汇）",
        ),
        sa.Column(
            "language",
            sa.String(8),
            nullable=True,
            comment="语种代码（zh-cn / en）",
        ),
        sa.Column(
            "author_name",
            sa.String(128),
            nullable=True,
            comment="作者名（可选）",
        ),
        sa.Column(
            "publish_date",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="新闻发布时间（readhub 给定）",
        ),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="本地入库时间（scheduler 6h 一次刷新）",
        ),
        sa.Column(
            "source",
            sa.String(32),
            nullable=False,
            server_default="readhub",
            comment="数据源：readhub（未来可扩展多家）",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id", name="uq_news_feed_external_id"),
    )
    op.create_index(
        op.f("ix_news_feed_items_site_name"),
        "news_feed_items",
        ["site_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_news_feed_items_language"),
        "news_feed_items",
        ["language"],
        unique=False,
    )
    op.create_index(
        op.f("ix_news_feed_items_publish_date"),
        "news_feed_items",
        ["publish_date"],
        unique=False,
    )
    op.create_index(
        op.f("ix_news_feed_items_fetched_at"),
        "news_feed_items",
        ["fetched_at"],
        unique=False,
    )


def downgrade() -> None:
    """删 news_feed_items 表（按依赖反序）。"""
    op.drop_index(op.f("ix_news_feed_items_fetched_at"), table_name="news_feed_items")
    op.drop_index(op.f("ix_news_feed_items_publish_date"), table_name="news_feed_items")
    op.drop_index(op.f("ix_news_feed_items_language"), table_name="news_feed_items")
    op.drop_index(op.f("ix_news_feed_items_site_name"), table_name="news_feed_items")
    op.drop_table("news_feed_items")
