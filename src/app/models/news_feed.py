"""新闻流 ORM 模型：多源财经新闻（V0.102 / V0.105 类目 / V0.107 按日聚合 / V0.114.0 多源）

数据来源（V0.114.0 起 4 源链式 failover，见 ``repositories/news_sources_fetcher.py``）：
- ★ 华尔街见闻 ``api-one.wallstcn.com/apiv1/content/lives``（有 URL，标题常缺）
- 金十数据 ``flash-api.jin10.com/get_flash_list``（无 URL，id 20 位）
- 东方财富 ``np-listapi.eastmoney.com/.../getFastNewsList``（无 URL）
- readhub ``api.readhub.cn/news``（兜底；唯一提供 readhub 独占站点如格隆汇/财联社的源）
- 4h 一次抓取（V0.106 由 6h 调到 4h）

设计要点：
- ``NewsFeedItem``（V0.102，多源化于 V0.114.0）
  - ``(source, external_id)`` **复合** UNIQUE 做 dedup（同一新闻不重复入库；
    二次抓取靠 ``on_conflict_do_update`` 走 upsert 路径）
  - ``external_id`` 是 **String(32)**：金十 id ≈2.02e19，连 SQLite 的 int64
    （上限 9.22e18）都装不下，文本是唯一无损选择
  - ``site_name`` + ``language`` + ``publish_date`` + ``fetched_at`` 单列索引，
    覆盖 UI 的 4 类查询（按来源/语种筛选 + 倒序时间线 + 24h 新增数）
  - 全文字段（``title`` / ``summary`` / ``url`` / ``mobile_url``）一律 Text，
    避免 string length 截断（readhub 标题实测最长 200+ 字符）
  - 所有 nullable 字段遵循 V0.78.0 NULL 纪律：「未知就是未知」，不偷偷回退
    0 / '' / 1970-01-01；``url`` 为 NULL 时 UI 渲染成不可点纯文本（V0.77.1）
  - ``category``（V0.105）：关键词分类器填入；启动 backfill_categories() 一次性
    补齐历史
- ``NewsFeedDaily``（V0.107）：按 BJT 日聚合的物化宽表（仿 ``ScoringDailyWide``
  的 date-as-PK 模式）
  - 1 日 1 行（``date`` 主键），无 ``user_id``（与 ``NewsFeedItem`` 一致：共享
    上下文，V0.80.0 #159 例外）
  - 5 类目计数（财经/科技/创投/商业/其他）+ 独立站点数 + 中英文计数
  - ``first_publish_at`` / ``last_publish_at``：当日首末发布时间（UTC）
  - ``last_refresh_at``：最近一次 refresh 触发本行重建的时间（UTC）
  - 仓储层用 ``upsert_daily(target_date)`` 重建指定 BJT 日行，scheduler 在
    refresh 末尾 + 启动 lifespan backfill 双重触发
"""

from datetime import date as date_t
from datetime import datetime

from sqlalchemy import Date, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SourceId


class NewsFeedItem(Base):
    """多源财经新闻条目（V0.114.0：readhub → 4 源链式 failover）。

    唯一约束：``(source, external_id)``，作为 dedup 主键。
    V0.114.0 之前是单列 ``external_id`` UNIQUE —— 那在单源时代成立，四源并存
    时必然撞车（四个源的 id 空间互不相干，同号不同源是常态而非异常）。

    二次抓取时相同 ``(source, external_id)`` 的行：``title`` / ``summary`` /
    ``url`` / ``site_name`` / ``language`` / ``author_name`` / ``publish_date``
    全量更新（源端偶有标题微调或作者补录），``fetched_at`` 自然变最新。

    ``url`` **可空**（V0.114.0）：金十 / 东方财富的快讯接口根本不返回链接。
    NULL = 「来源没有给链接」，UI 据此渲染**不可点的纯文本**（V0.77.1 不给假
    affordance），不合成 ``#`` 假链接。
    """

    __tablename__ = "news_feed_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # ⚠ V0.114.0 用 **String 而非 BigInteger**：金十 id ≈2.02e19，而 SQLite
    # INTEGER 是 int64（上限 9.22e18），超了 2.2 倍 —— 绑值直接 OverflowError。
    # BigInteger 只能解决 int32 溢出，解决不了 int64。文本是唯一无损选择。
    external_id: Mapped[str] = mapped_column(
        SourceId,
        comment="源站 news id（dedup 主键的一半）。文本型：金十 id 20 位，超出 SQLite int64 上限",
    )
    title: Mapped[str] = mapped_column(Text, comment="新闻标题")
    summary: Mapped[str] = mapped_column(
        Text, default="", server_default="", comment="新闻摘要（部分源只给正文，标题回退自正文）"
    )
    url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="原文链接。NULL = 来源未提供（金十/东财快讯），UI 渲染成不可点纯文本",
    )
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
        comment="数据源标识：wallstcn / jin10 / eastmoney / readhub（V0.114.0 多源 failover）",
    )
    # V0.105：关键词分类器结果（财经/科技/创投/商业/其他）
    # - 入库时由 ``readhub_fetcher._normalize`` 调 ``classify()`` 填入
    # - backfill：``NewsFeedRepository.backfill_categories()`` 启动时一次
    # - 索引：UI 顶部类目筛选 + 「/categories」端点 distinct 查询
    category: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        index=True,
        comment="V0.105 分类（财经/科技/创投/商业/其他），_normalize() 关键词分类器填入；启动 backfill_categories() 一次性补齐历史",
    )

    __table_args__ = (
        # V0.114.0：单列 external_id UNIQUE → 复合（单源时代成立，四源并存必撞车）
        UniqueConstraint("source", "external_id", name="uq_news_feed_source_external"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<NewsFeedItem #{self.external_id} {self.site_name} '{self.title[:24]}...'>"


class NewsFeedDaily(Base):
    """V0.107 按 BJT 日聚合的物化宽表（仿 ScoringDailyWide · date-as-PK）。

    ``NewsFeedItem`` 的按日聚合；refresh 后重建 / 启动 backfill。
    news 是 shared context（V0.80.0 #159 例外），与 ``NewsFeedItem`` 一致**不**挂
    ``user_id``。

    字段约定
    --------
    - ``date``：BJT 日期（YYYY-MM-DD），用 ``datetime.date`` 类型作主键（1 日 1 行）
    - 5 类目计数（财经/科技/创投/商业/其他）：``category IS NULL`` 的行**不**计入
      任何类目，但 ``total_count`` 仍计入（NULL 视为「未分类」）
    - ``unique_sites_count``：当日独立 ``site_name`` 数
    - ``en_count`` / ``zh_count``：按 ``language`` 区分（NULL 不计）
    - ``first_publish_at`` / ``last_publish_at``：当日首末发布时间（UTC，可能为
      NULL 当日为空）
    - ``last_refresh_at``：最近一次 refresh 触发本行重建的时间（UTC）

    设计权衡
    --------
    - 与 ``ScoringDailyWide`` 相比：没有 ``user_id``（V0.80.0 例外）；没有
      ``outcomes`` 列（新闻聚合无 T+N 概念）
    - 重建策略：全量重算（不增量），30 天 × 1 行 ≈ 10ms，简单胜过复杂
    - ``category`` 5 个类目列写死，**不**用 JSON 字段 —— 固定列便于 GROUP BY +
      加列对应 SQL 子句直白，索引也可针对每列
    """

    __tablename__ = "news_feed_daily"

    date: Mapped[date_t] = mapped_column(
        Date, primary_key=True, comment="BJT 日期（YYYY-MM-DD，1 日 1 行）"
    )
    total_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="当日新闻总条数（含未分类）"
    )
    finance_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="财经类目条数"
    )
    tech_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="科技类目条数"
    )
    vc_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="创投类目条数"
    )
    biz_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="商业类目条数"
    )
    other_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="其他类目条数"
    )
    unique_sites_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="当日独立来源站数"
    )
    en_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="英文条数（language='en'）"
    )
    zh_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
        comment="中文条数（language='zh-cn' / 'zh' / 'zh-tw' / 'zh-CN' 任意 zh- 前缀）",
    )
    first_publish_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="当日首篇发布时间（UTC）"
    )
    last_publish_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="当日末篇发布时间（UTC）"
    )
    last_refresh_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="最近一次 refresh 触发本行重建的时间（UTC）",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # 索引：date 已是主键（隐含 B-Tree 索引），无需额外单列索引

    def __repr__(self) -> str:  # pragma: no cover
        return f"<NewsFeedDaily {self.date} total={self.total_count} finance={self.finance_count} ...>"
