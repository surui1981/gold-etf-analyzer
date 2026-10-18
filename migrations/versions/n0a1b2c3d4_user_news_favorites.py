"""user_news_favorites 表：用户对今日要闻的「收藏/永久存储」（V0.103）

Revision ID: n0a1b2c3d4
Revises: m9g0a1b2c3
Create Date: 2026-10-19 02:00:00.000000

迁移背景
----------
V0.102 落地的 ``news_feed_items`` 是「共享上下文」(migration m9g0a1b2c3 第 30 行明文
不挂 user_id），6h 抓取 / 无清理 / 字段外部所有。用户在翻 今日要闻 时看到「这条值得
长期参考」想存下来，目前**项目里没有任何「用户标记数据」的表或字段**（Explore 全仓
grep 0 命中 watchlist / favorite / bookmark / starred / pinned / user_note 业务实体）。

V0.103 起新增「我的收藏」全栈：
- /headlines / /home 每条加 `⭐ 收藏` 按钮 → 一键入库
- 新增 /favorites 档案管理页：时间线 + tag 筛选 + 重要度 + 自由笔记 + 统计侧栏
- 帮用户「掌握市场动态」：按 tag 维度（黄金 / 美元 / 美联储 / 地缘 等 12 个白名单
  + 自定义）聚合 + 按月 / 按来源站统计

迁移策略
--------
- **单表，5 索引**，完全不碰既有表（V0.79.0 #162 纪律）
- **字段冗余快照**：title / summary / url / site_name / publish_date / source 全部
  收藏时复制。与 news_feed_items 表完全松耦合，**防 readhub 端撤稿 / URL 失效时
  收藏断链**（Explore 模块 4 末尾防断链论证）
- **单用户（共享）模式**：不挂 user_id（与 news_feed_items 共享语义对齐；用户
  已通过 AskUserQuestion 锁定此模式）
- ``news_external_id + news_source`` 复合 UNIQUE → 同一新闻只能收藏一次（POST
  dedup 走 INSERT OR FAIL；重复时 409 Conflict）
- ``user_tags`` TEXT 存 JSON 数组（去重 + 字母序），与 scoring_daily_wide.news_basis_tags
  完全同模式（`String(512)` 足够；tag 数 0-12 个，平均 50 字符）
- ``importance`` INTEGER 1-3 星，默认 1
- ``user_note`` TEXT 自由笔记，默认 ''（非 NULL 纪律，笔记可为空但占位）
- 索引：
  - ``(news_external_id, news_source)`` UNIQUE — dedup 主键
  - ``(archived_at)`` — 倒序时间线
  - ``(importance, archived_at)`` 复合 — 「3 星 + 最近」高优列表
  - ``(site_name)`` — 来源站统计
- ``user_tags`` 用 LIKE 模式搜索（``LIKE '%"美联储"%'`` 命中 JSON 数组中的字符串），
  千级数据够用；万级再考虑 FTS5（V0.103+ backlog）

⚠ V0.80.0 #159 教训：本表**不挂 user_id** —— 与 news_feed_items 一致走「共享上下文」
   语义边界。`auth_enabled=true` 多用户模式启用后，POST/PATCH/DELETE 仍走
   `Depends(require_user)` 校验登录态（即使不写 user_id 字段），但**所有人看到
   同一份收藏**。若未来需要 per-user 隔离，加迁移：``ALTER TABLE user_news_favorites
   ADD COLUMN user_id INTEGER`` + 索引。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "n0a1b2c3d4"
down_revision: str | Sequence[str] | None = "m9g0a1b2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """建 user_news_favorites 表 + 5 索引。"""
    op.create_table(
        "user_news_favorites",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "news_external_id",
            sa.Integer(),
            nullable=False,
            comment="readhub news id（仅做溯源，无 FK；允许 readhub 端撤稿后收藏仍完整）",
        ),
        sa.Column(
            "news_source",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'readhub'"),
            comment="数据源标识（默认 readhub；预留多源扩展）",
        ),
        sa.Column(
            "title",
            sa.Text(),
            nullable=False,
            comment="收藏时的标题快照（防 readhub 端撤稿 / 修改）",
        ),
        sa.Column(
            "summary",
            sa.Text(),
            nullable=False,
            server_default=sa.text("''"),
            comment="收藏时的摘要快照",
        ),
        sa.Column(
            "url",
            sa.Text(),
            nullable=False,
            comment="收藏时的原文链接快照（直接打开此 URL，不回查 news_feed_items）",
        ),
        sa.Column(
            "mobile_url",
            sa.Text(),
            nullable=True,
            comment="移动端 URL 快照（可空）",
        ),
        sa.Column(
            "site_name",
            sa.Text(),
            nullable=False,
            comment="来源站快照（例：格隆汇 / 财联社 / techradar.com）",
        ),
        sa.Column(
            "language",
            sa.Text(),
            nullable=True,
            comment="语种快照（NULL = 未知）",
        ),
        sa.Column(
            "author_name",
            sa.Text(),
            nullable=True,
            comment="作者快照（NULL = 未知）",
        ),
        sa.Column(
            "publish_date",
            sa.DateTime(),
            nullable=False,
            comment="新闻发布时间快照（区分「新闻何时发生」与「我何时收藏」）",
        ),
        sa.Column(
            "user_tags",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'[]'"),
            comment="用户自定义 tag JSON 数组（去重 + 字母序，LIKE 模式搜索）",
        ),
        sa.Column(
            "user_note",
            sa.Text(),
            nullable=False,
            server_default=sa.text("''"),
            comment="用户自由笔记（默认空字符串，占位）",
        ),
        sa.Column(
            "importance",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
            comment="重要度 1-3 星（1 默认 / 2 关注 / 3 必看）",
        ),
        sa.Column(
            "archived_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            comment="收藏时间（手动 archive_at 字段，不用 fetched_at）",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            comment="笔记 / tag / importance 改动时刷新",
        ),
        sa.UniqueConstraint(
            "news_external_id",
            "news_source",
            name="uq_user_news_fav_external_source",
        ),
    )
    # 5 索引（与 V0.102 news_feed_items 模式一致）
    op.create_index(
        "ix_user_news_fav_archived_at",
        "user_news_favorites",
        ["archived_at"],
    )
    op.create_index(
        "ix_user_news_fav_importance_archived",
        "user_news_favorites",
        ["importance", "archived_at"],
    )
    op.create_index(
        "ix_user_news_fav_site_name",
        "user_news_favorites",
        ["site_name"],
    )


def downgrade() -> None:
    """删 user_news_favorites 表（4 索引自动跟随 drop）。"""
    op.drop_index("ix_user_news_fav_site_name", table_name="user_news_favorites")
    op.drop_index(
        "ix_user_news_fav_importance_archived", table_name="user_news_favorites"
    )
    op.drop_index("ix_user_news_fav_archived_at", table_name="user_news_favorites")
    op.drop_table("user_news_favorites")
