"""今日要闻 Pydantic Out schemas（V0.102 / V0.107 按日聚合）"""

from datetime import date as date_t
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


class NewsFeedDailyOut(BaseModel):
    """V0.107 按 BJT 日聚合的物化快照。

    1 日 1 行（``date`` 主键），由 ``NewsFeedRepository.upsert_daily`` 重建。
    UI /home 顶 chip 与 /headlines 顶部 daily 摘要直接读此表（O(1) 行），
    替代实时 ``GROUP BY`` 计算。

    所有 nullable 字段遵循 V0.78.0 NULL 纪律：「未知就是未知」，
    **不**用 0 兜底。
    """

    date: date_t = Field(..., description="BJT 日期（YYYY-MM-DD，1 日 1 行）")
    total_count: int = Field(..., ge=0, description="当日总条数（含未分类）")
    finance_count: int = Field(..., ge=0, description="财经类目条数")
    tech_count: int = Field(..., ge=0, description="科技类目条数")
    vc_count: int = Field(..., ge=0, description="创投类目条数")
    biz_count: int = Field(..., ge=0, description="商业类目条数")
    other_count: int = Field(..., ge=0, description="其他类目条数")
    unique_sites_count: int = Field(..., ge=0, description="当日独立来源站数")
    en_count: int = Field(..., ge=0, description="英文条数（language='en'）")
    zh_count: int = Field(..., ge=0, description="中文条数（language 任意 zh- 前缀）")
    first_publish_at: datetime | None = Field(
        default=None, description="当日首篇发布时间（UTC）"
    )
    last_publish_at: datetime | None = Field(
        default=None, description="当日末篇发布时间（UTC）"
    )
    last_refresh_at: datetime = Field(
        ..., description="最近一次 refresh 触发本行重建的时间（UTC）"
    )


class NewsFeedDailyListOut(BaseModel):
    """V0.107 区间聚合响应：``[start, end]`` 闭区间（倒序，最近 → 远期）。"""

    items: list[NewsFeedDailyOut] = Field(
        default_factory=list,
        description="区间内日聚合行（按 date 倒序；空日不创建行，可能跳过）",
    )
    start: date_t = Field(..., description="区间起始 BJT 日（闭）")
    end: date_t = Field(..., description="区间结束 BJT 日（闭）")
    total: int = Field(..., ge=0, description="返回条数（实际有数据的日数）")
