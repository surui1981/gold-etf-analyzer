"""报告存档 Pydantic schemas（V0.111.0）

5 个 schema：
- ``ReportOut``：单条报告 Out（**不含** 磁盘路径，只出 id + 元数据）
- ``ReportUpdateIn``：PATCH 请求体（title / report_date / category / tags / summary 任选）
- ``ReportListOut``：列表响应（items + total + limit + offset）
- ``ReportCategoriesOut``：分类去重列表（喂前端筛选下拉）
- ``ReportStatsOut``：侧栏统计（total / last_30d_count / by_category）

⚠ **``stored_name`` 刻意不出现在任何 Out schema 里**：它是磁盘真名，
   一旦下发给前端就等于把「上传目录 + 文件名规律」暴露给浏览器，
   而前端并不需要它（查看走 ``/content`` 端点按 id 取）。这是刻意的
   「最小暴露」——同 ``models/reports.py`` 里原始文件名不入库是同一条纪律。
"""

from datetime import date, datetime

from pydantic import BaseModel, Field


class ReportOut(BaseModel):
    """单条报告 Out（V0.111.0）。"""

    id: int = Field(..., description="报告主键")
    title: str = Field(..., description="报告标题")
    original_name: str = Field(..., description="上传时的原始文件名（仅展示，前端须转义）")
    size_bytes: int = Field(..., description="文件字节数")
    report_date: date | None = Field(default=None, description="报告自身日期（NULL = 未填）")
    category: str = Field(default="其他", description="分类")
    tags: list[str] = Field(default_factory=list, description="标签数组（去重 + 字母序）")
    summary: str = Field(default="", description="一句话摘要")
    created_at: datetime = Field(..., description="上传时间")
    updated_at: datetime = Field(..., description="元数据最后修改时间")
    view_url: str = Field(
        default="", description="查看地址（/api/v1/reports/{id}/content），由端点填充"
    )


class ReportUpdateIn(BaseModel):
    """PATCH 请求体：登记表字段局部更新（任选，None = 不改）。

    ⚠ ``tags`` 与 ``report_date`` 用显式 ``None`` 表达「清空」是**做不到**的
    （本 schema 的 None 语义是「不更新」）。清空标签请传 ``tags=[]``；
    清空报告日期请用 ``report_date: null`` 之外的 ``ReportUpdateIn`` 约定 ——
    当前实现里报告日期不可清空，属已知取舍（补录日期比清空常见得多）。
    """

    title: str | None = Field(default=None, max_length=200, description="报告标题")
    report_date: date | None = Field(default=None, description="报告自身日期")
    category: str | None = Field(default=None, max_length=32, description="分类")
    tags: list[str] | None = Field(default=None, description="标签数组")
    summary: str | None = Field(default=None, max_length=2000, description="一句话摘要")


class ReportListOut(BaseModel):
    """列表响应（V0.111.0）。"""

    items: list[ReportOut] = Field(default_factory=list, description="报告列表")
    total: int = Field(default=0, description="符合筛选条件的总数（用于分页）")
    limit: int = Field(default=50, description="本次返回上限")
    offset: int = Field(default=0, description="本次跳过的条数")


class ReportCategoriesOut(BaseModel):
    """分类去重列表（喂前端筛选下拉）。"""

    categories: list[str] = Field(default_factory=list, description="出现过的分类（按频次倒序）")


class ReportStatsOut(BaseModel):
    """侧栏统计。"""

    total: int = Field(default=0, description="报告总数")
    last_30d_count: int = Field(default=0, description="近 30 天上传数")
    total_bytes: int = Field(default=0, description="全部报告占用字节数")
    by_category: list[dict] = Field(
        default_factory=list, description="分类分布 [{category, count}]"
    )
