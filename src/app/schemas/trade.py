"""交易历史 Schema：多条件查询结果 / 汇总 / 分页（P1 #6 交易历史查询页）。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TradeHistoryItem(BaseModel):
    """一笔成交（含所属持仓与账本信息）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    position_id: int = Field(..., description="所属持仓 ID")
    account_id: int = Field(..., description="所属账本 ID")
    account_name: str = Field("", description="账本名称")
    symbol: str = Field("", description="品种代码")
    name: str = Field("", description="品种名称")
    side: str = Field(..., description="buy 买入 / sell 卖出")
    quantity: float = Field(..., description="成交数量（份）")
    price: float = Field(..., description="成交价（元/份）")
    fee: float = Field(0, description="手续费（元）")
    amount: float = Field(0, description="成交金额 = 数量 × 价格（元，不含手续费）")
    realized_pnl: float | None = Field(
        None, description="该笔卖出的已实现盈亏（元，均价法）；买入为 null"
    )
    post_quantity: float | None = Field(
        None, description="该笔成交后该持仓剩余份数（均价法回放）"
    )
    traded_at: datetime


class TradeHistorySummary(BaseModel):
    """筛选结果的汇总（覆盖全部匹配行，非当前页）。"""

    count: int = Field(0, description="成交笔数")
    buy_count: int = Field(0, description="买入笔数")
    sell_count: int = Field(0, description="卖出笔数")
    buy_amount: float = Field(0, description="买入金额合计（元，不含手续费）")
    sell_amount: float = Field(0, description="卖出金额合计（元，不含手续费）")
    net_amount: float = Field(0, description="净流出 = 买入 − 卖出（元）")
    total_fee: float = Field(0, description="手续费合计（元）")
    realized_pnl: float = Field(0, description="已实现盈亏合计（元，均价法，已扣卖出手续费）")


class TradeHistoryOut(BaseModel):
    """交易历史查询输出（分页）。"""

    items: list[TradeHistoryItem] = Field(default_factory=list, description="当前页明细")
    total: int = Field(0, description="匹配总笔数")
    page: int = Field(1, description="当前页码（从 1 起）")
    page_size: int = Field(50, description="每页条数")
    page_count: int = Field(1, description="总页数")
    summary: TradeHistorySummary = Field(default_factory=TradeHistorySummary)
