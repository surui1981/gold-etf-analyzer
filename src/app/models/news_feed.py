"""新闻流 ORM 模型：readhub 财经新闻（V0.102）

数据来源：
- readhub 内部 API ``https://api.readhub.cn/news``（前端 hydrate 用，非官方但
  匿名稳定，6h 一次抓取）。

设计要点：
- ``external_id`` 是 readhub 的自增主键，整型，作为唯一约束做 dedup（同一新闻
  不重复入库；二次抓取靠 ``on_conflict_do_update`` 走 upsert 路径）
- ``site_name`` + ``language`` + ``publish_date`` + ``fetched_at`` 单列索引，
  覆盖 UI 的 4 类查询（按来源/语种筛选 + 倒序时间线 + 24h 新增数）
- 全文字段（``title`` / ``summary`` / ``url`` / ``mobile_url``）一律 Text，
  避免 string length 截断（readhub 标题实测最长 200+ 字符）
- 所有 nullable 字段遵循 V0.78.0 NULL 纪律：「未知就是未知」，不偷偷回退
  0 / '' / 1970-01-01
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class NewsFeedItem(Base):
    """readhub 财经新闻条目。

    唯一约束：``external_id``（readhub 的 news id），作为 dedup 主键。
    二次抓取时相同 ``external_id`` 的行：``title`` / ``summary`` / ``url`` /
    ``site_name`` / ``language`` / ``author_name`` / ``publish_date`` 全量更新
    （readhub 偶有标题微调或作者补录），``fetched_at`` 自然变最新。
    """

    __tablename__ = "news_feed_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[int] = mapped_column(
        Integer,
        comment="readhub 的 news id（dedup 主键，整型）",
    )
    title: Mapped[str] = mapped_column(Text, comment="新闻标题")
    summary: Mapped[str] = mapped_column(
        Text, default="", server_default="", comment="新闻摘要（readhub 自带）"
    )
    url: Mapped[str] = mapped_column(Text, comment="原文链接（浏览器外链跳转）")
    mobile_url: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="移动端链接（部分来源提供）"
    )
    site_name: Mapped[str] = mapped_column(
        String(64),
        index=True,
        comment="来源站：华尔街见闻 / 36Kr / 财联社 / 格隆汇",
    )
    language: Mapped[str | None] = mapped_column(
        String(8), nullable=True, index=True, comment="语种代码：zh-cn / en"
    )
    author_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="作者名（可选，readhub 部分条目标注）"
    )
    publish_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, comment="新闻发布时间（readhub 给定）"
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        server_default=func.now(),
        comment="本地入库时间（scheduler 6h 一次刷新）",
    )
    source: Mapped[str] = mapped_column(
        String(32),
        default="readhub",
        server_default="readhub",
        comment="数据源标识：readhub（未来可扩 多家）",
    )

    __table_args__ = (UniqueConstraint("external_id", name="uq_news_feed_external_id"),)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<NewsFeedItem #{self.external_id} {self.site_name} '{self.title[:24]}...'>"
