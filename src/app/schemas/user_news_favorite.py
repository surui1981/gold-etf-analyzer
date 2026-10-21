"""用户新闻收藏 Pydantic schemas（V0.103）

5 个 schema：
- ``UserNewsFavoriteItemOut``：单条收藏 Out（11 字段快照 + 3 user_meta + 2 timestamp）
- ``UserNewsFavoriteCreateIn``：POST 请求体（news_external_id + 可选 user_meta）
- ``UserNewsFavoriteUpdateIn``：PATCH 请求体（user_tags / user_note / importance 任选）
- ``UserNewsFavoriteListOut``：列表响应（items + total + limit + offset）
- ``UserNewsFavoriteStatusOut``：统计响应（6 维聚合）
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_serializer

from app.schemas.news_feed import js_safe_id


class UserNewsFavoriteItemOut(BaseModel):
    """单条收藏 Out（V0.103）。"""

    id: int = Field(..., description="收藏主键")
    news_external_id: int = Field(
        ..., description="源站 news id（仅溯源）。JSON 里可能是数字也可能是字符串，见 js_safe_id"
    )
    news_source: str = Field(
        default="readhub", description="数据源标识：wallstcn / jin10 / eastmoney / readhub"
    )
    title: str = Field(..., description="标题快照")
    summary: str = Field(default="", description="摘要快照")
    url: str | None = Field(
        default=None,
        description=(
            "原文链接快照（外链跳转）。V0.114.0 起可空："
            "源条目本就无链接时（金十/东财快讯）收藏存 NULL"
        ),
    )
    mobile_url: str | None = Field(default=None, description="移动端 URL 快照")
    site_name: str = Field(..., description="来源站快照")
    language: str | None = Field(default=None, description="语种快照")
    author_name: str | None = Field(default=None, description="作者快照")
    publish_date: datetime = Field(..., description="新闻发布时间快照（UTC）")
    user_tags: list[str] = Field(
        default_factory=list, description="用户自定义 tag 数组（去重 + 字母序）"
    )
    user_note: str = Field(default="", description="用户自由笔记")
    importance: int = Field(
        default=1, ge=1, le=3, description="重要度 1-3 星"
    )
    archived_at: datetime = Field(..., description="收藏时间（UTC）")
    updated_at: datetime = Field(..., description="最后修改时间（笔记/tag/importance 改动）")

    @field_serializer("news_external_id", when_used="json")
    def _ser_news_external_id(self, value: int) -> int | str:
        """超 JS 安全范围的 id（金十 20 位）序列化成字符串，见 ``js_safe_id``。"""
        return js_safe_id(value)


class UserNewsFavoriteCreateIn(BaseModel):
    """POST 请求体：从 news_feed_items 收藏时直接传 external_id；也支持外部 URL 直传。"""

    # 必填：定位源
    news_external_id: int = Field(..., description="readhub news id（与 source 组成 dedup 主键）")
    news_source: str = Field(
        default="readhub", description="数据源标识（默认 readhub）"
    )
    # 可选：直接外部 URL 收藏时手动传；news_feed_items 命中时由后端自动补全
    title: str | None = Field(default=None, description="标题快照（外部直传时必填）")
    summary: str | None = Field(default=None, description="摘要快照")
    url: str | None = Field(default=None, description="原文链接快照（外部直传时必填）")
    mobile_url: str | None = Field(default=None, description="移动端 URL 快照")
    site_name: str | None = Field(default=None, description="来源站快照（外部直传时必填）")
    language: str | None = Field(default=None, description="语种快照")
    author_name: str | None = Field(default=None, description="作者快照")
    publish_date: datetime | None = Field(default=None, description="新闻发布时间快照")
    # 可选：用户元数据
    user_tags: list[str] = Field(
        default_factory=list, description="用户自定义 tag 数组"
    )
    user_note: str = Field(default="", description="用户自由笔记")
    importance: int = Field(default=1, ge=1, le=3, description="重要度 1-3 星")


class UserNewsFavoriteUpdateIn(BaseModel):
    """PATCH 请求体：user_tags / user_note / importance 任选。"""

    user_tags: list[str] | None = Field(
        default=None, description="新的 tag 数组（None=不改）"
    )
    user_note: str | None = Field(
        default=None, description="新笔记（None=不改）"
    )
    importance: int | None = Field(
        default=None, ge=1, le=3, description="新重要度（None=不改）"
    )


class UserNewsFavoriteListOut(BaseModel):
    """列表响应。"""

    items: list[UserNewsFavoriteItemOut] = Field(default_factory=list)
    total: int = Field(..., ge=0, description="当前筛选条件下的总条数")
    limit: int = Field(..., ge=1, description="本次返回的 limit")
    offset: int = Field(..., ge=0, description="本次 offset")


class UserNewsFavoriteStatusOut(BaseModel):
    """统计响应（6 维聚合，UI 侧栏用）。"""

    total: int = Field(..., ge=0, description="收藏总数")
    by_importance: dict[int, int] = Field(
        default_factory=dict, description="按重要度分布 {1: n, 2: n, 3: n}"
    )
    by_site: list[dict] = Field(
        default_factory=list,
        description="按来源站 top 10 [{site_name, count}]",
    )
    by_tag: list[dict] = Field(
        default_factory=list,
        description="按 tag top 10 [{tag, count}]",
    )
    by_month: list[dict] = Field(
        default_factory=list,
        description="按月归档 top 6 [{month: YYYY-MM, count}]",
    )
    last_7d_count: int = Field(..., ge=0, description="过去 7 天新增")
    last_30d_count: int = Field(..., ge=0, description="过去 30 天新增")
