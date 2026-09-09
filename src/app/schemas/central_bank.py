"""世界央行黄金购买（Pydantic Out schemas）。"""

from datetime import date, datetime

from pydantic import BaseModel, Field


class CentralBankPurchaseOut(BaseModel):
    """单条央行季度购金记录。"""

    country_iso: str = Field(..., description="ISO 3 字母代码")
    country_name: str = Field(..., description="国家中文名")
    quarter: str = Field(..., description="季度，如 2026Q2")
    tonnes_net: float = Field(..., description="季度净购金（吨），正=买入/负=卖出")
    source: str = Field(..., description="数据源：IMF IRFCL / WGC 手工")
    data_date: date = Field(..., description="数据截止日（季度最后一日）")


class CentralBankTopBuyer(BaseModel):
    """某年度 Top N 买家。"""

    rank: int = Field(..., ge=1, description="排名，从 1 开始")
    country_iso: str
    country_name: str
    tonnes_net: float = Field(..., description="当年累计净购金（吨）")


class CentralBankSummaryOut(BaseModel):
    """首页摘要：T12M 总量 + 当前季度 + 参与国家数 + 数据截止季。"""

    t12m_total: float = Field(..., description="滚动 12 月（最近 4 季度）合计净购金（吨）")
    t12m_window: str = Field(..., description="T12M 窗口，如 2025Q3–2026Q2")
    current_quarter: str = Field(..., description="最新数据季度")
    current_quarter_total: float = Field(..., description="最新季度全球合计（吨）")
    country_count: int = Field(..., ge=0, description="覆盖国家数")
    latest_data_quarter: str = Field(..., description="数据库最新季度")
    last_refresh: datetime | None = Field(None, description="最后刷新时间（UTC）")


class CentralBankListOut(BaseModel):
    """央行购金明细查询响应（purchases endpoint 一次返回全量）。"""

    items: list[CentralBankPurchaseOut]
    summary: CentralBankSummaryOut
    top_buyers: list[CentralBankTopBuyer] = Field(
        default_factory=list,
        description="按 T12M 降序的 Top 10 买家",
    )
