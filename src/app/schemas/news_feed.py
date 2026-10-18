"""今日要闻 Pydantic Out schemas（V0.102）"""

from datetime import datetime

from pydantic import BaseModel, Field


class NewsFeedItemOut(BaseModel):
    """readhub 单条新闻（Out）。"""

    external_id: int = Field(..., description="readhub news id（dedup 主键）")
    title: str = Field(..., description="新闻标题")
    summary: str = Field(
        default="", description="新闻摘要（readhub 自带；空字符串代表无摘要）"
    )
    url: str = Field(..., description="原文链接（浏览器外链 new tab 跳转）")
    mobile_url: str | None = Field(
        default=None, description="移动端链接（readhub 部分条目标注）"
    )
    site_name: str = Field(..., description="来源站：华尔街见闻 / 36Kr / 财联社 / 格隆汇")
    language: str | None = Field(
        default=None, description="语种代码：zh-cn / en（V0.78.0 NULL 纪律：未知则 None）"
    )
    author_name: str | None = Field(
        default=None, description="作者名（部分条目无作者）"
    )
    publish_date: datetime = Field(..., description="新闻发布时间（UTC，readhub 给定）")
    fetched_at: datetime = Field(..., description="本地入库时间（scheduler 6h 一次刷新）")
    source: str = Field(default="readhub", description="数据源标识（预留多源）")
    # V0.105：分类（财经/科技/创投/商业/其他）；None=未分类（启动 backfill 过渡期）
    category: str | None = Field(
        default=None,
        description="V0.105 分类（财经/科技/创投/商业/其他）；启动 backfill_categories() 一次性补齐历史，None = 未分类",
    )


class NewsFeedListOut(BaseModel):
    """新闻列表响应（一次返回全量；UI 限 limit 默认 50 避免渲染压力）。

    V0.104 单日模式扩展：
    - ``current_date`` 回显请求的 date（YYYY-MM-DD）；days 模式时为 None
    - ``has_older`` / ``has_newer`` 用于前端禁用「前一天 / 后一天」按钮
    - ``total`` 语义保持 ``= len(items)``（≤ limit），不破坏现有测试
    """

    items: list[NewsFeedItemOut] = Field(default_factory=list)
    total: int = Field(..., ge=0, description="返回条数（≤ limit）")
    current_date: str | None = Field(
        default=None, description="V0.104：单日模式回显的 date（YYYY-MM-DD）；days 模式为 None"
    )
    has_older: bool = Field(
        default=False, description="V0.104：current_date 之前是否还有更早的新闻（可点「前一天」）"
    )
    has_newer: bool = Field(
        default=False, description="V0.104：current_date 之后是否还有更新的新闻（可点「后一天」）"
    )


class NewsFeedStatusOut(BaseModel):
    """数据时效摘要：UI 顶栏的 4-chip 用。"""

    last_refresh_at: str | None = Field(
        default=None, description="最后入库时间（ISO 8601 UTC）；None=尚无数据"
    )
    total_items: int = Field(..., ge=0, description="DB 总条数")
    last_24h_count: int = Field(..., ge=0, description="过去 24h 新增数")


class NewsFeedRefreshOut(BaseModel):
    """手动刷新响应：保留末次数据语义，失败 ok=False + error 文案。"""

    ok: bool = Field(..., description="True=成功 upsert；False=失败（保留末次）")
    upserted: int = Field(..., ge=0, description="本次 upsert 行数；失败=0")
    error: str | None = Field(
        default=None, description="失败原因（ok=False 时填；ok=True 时 None）"
    )
