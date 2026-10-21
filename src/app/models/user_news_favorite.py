"""用户新闻收藏 ORM 模型：今日要闻「收藏 / 永久存储」（V0.103）

数据来源：
- 用户从 ``news_feed_items``（V0.102 readhub 财经新闻流）或外部链接手动收藏
- 收藏时**全量快照** title / summary / url / site_name / publish_date / source，
  与源表完全松耦合（防 readhub 端撤稿 / URL 失效时收藏断链）

设计要点：
- ``news_external_id + news_source`` 复合 UNIQUE → 同一新闻只能收藏一次
  （POST dedup 走 INSERT OR FAIL；重复时 409 Conflict）
- ``user_tags`` TEXT 存 JSON 数组（去重 + 字母序），与 ``scoring_daily_wide.news_basis_tags``
  完全同模式（``String(512)`` 足够；tag 数 0-12 个，平均 50 字符）
- ``importance`` INTEGER 1-3 星（1 默认 / 2 关注 / 3 必看）
- ``user_note`` TEXT 自由笔记，默认空字符串（V0.78.0 NULL 纪律例外：
  笔记是用户内容，占位用 '' 而非 NULL，UI 更好处理）
- ``archived_at`` / ``updated_at`` 自动维护
- 索引：
  - ``(news_external_id, news_source)`` UNIQUE — dedup 主键
  - ``(archived_at)`` — 倒序时间线
  - ``(importance, archived_at)`` 复合 — 「3 星 + 最近」高优列表
  - ``(site_name)`` — 来源站统计
- 所有 nullable 字段遵循 V0.78.0 NULL 纪律：「未知就是未知」
  （mobile_url / language / author_name 可空；其它必填）

⚠ V0.80.0 #159 教训：本表**不挂 user_id** —— 与 ``news_feed_items`` 一致走
   「共享上下文」语义边界（用户已通过 AskUserQuestion 锁定单用户模式）。
   多用户模式启用后：POST/PATCH/DELETE 仍走 ``Depends(require_user)`` 校验登录态，
   但所有人看到同一份收藏。未来如需 per-user 隔离，加迁移
   ``ALTER TABLE user_news_favorites ADD COLUMN user_id INTEGER``。
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SourceId


class UserNewsFavorite(Base):
    """用户对今日要闻的收藏记录（V0.103 引入）。

    唯一约束：``(news_external_id, news_source)``，作为收藏 dedup 主键。
    重复收藏（POST）由仓储层检测并抛 409 Conflict。
    """

    __tablename__ = "user_news_favorites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    news_external_id: Mapped[str] = mapped_column(
        SourceId,
        nullable=False,
        comment="源站 news id（仅做溯源，无 FK）。文本型：金十 id 超出 SQLite int64 上限",
    )
    news_source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="readhub",
        server_default="readhub",
        comment="数据源标识：wallstcn / jin10 / eastmoney / readhub（V0.114.0 多源）",
    )
    title: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="收藏时的标题快照（防 readhub 端撤稿 / 修改）",
    )
    summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
        comment="收藏时的摘要快照",
    )
    url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="收藏时的原文链接快照（直接打开此 URL，不回查源表）。NULL = 源条目本就无链接（金十/东财）",
    )
    mobile_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="移动端 URL 快照（可空）",
    )
    site_name: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="来源站快照（例：格隆汇 / 财联社 / techradar.com）",
    )
    language: Mapped[str | None] = mapped_column(
        String(8),
        nullable=True,
        comment="语种快照（NULL = 未知）",
    )
    author_name: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="作者快照（NULL = 未知）",
    )
    publish_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="新闻发布时间快照（区分「新闻何时发生」与「我何时收藏」）",
    )
    user_tags: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
        server_default="[]",
        comment="用户自定义 tag JSON 数组（去重 + 字母序，LIKE 模式搜索）",
    )
    user_note: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
        comment="用户自由笔记（默认空字符串，占位）",
    )
    importance: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
        comment="重要度 1-3 星（1 默认 / 2 关注 / 3 必看）",
    )
    archived_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="收藏时间（手动 archive_at 字段）",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="笔记 / tag / importance 改动时刷新",
    )

    __table_args__ = (
        UniqueConstraint(
            "news_external_id",
            "news_source",
            name="uq_user_news_fav_external_source",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<UserNewsFavorite #{self.id} ext={self.news_external_id} "
            f"★{self.importance} '{self.title[:24]}...'>"
        )
