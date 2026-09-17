"""交易业绩 Schema：收益曲线点位 / 汇总 + 获利分析统计（V0.61.0）。"""

from pydantic import BaseModel, Field


class EquityPoint(BaseModel):
    """收益曲线单日点位。"""

    date: str = Field(..., description="交易日 YYYY-MM-DD")
    price: float = Field(0, description="当日 ETF 收盘价（元/份）")
    quantity: float = Field(0, description="当日收盘持有份数")
    cost: float = Field(0, description="当日持仓成本合计（元）")
    market_value: float = Field(0, description="当日持仓市值（元）")
    realized_pnl: float = Field(0, description="截至当日累计已实现盈亏（元）")
    unrealized_pnl: float = Field(0, description="当日浮动盈亏（元）")
    total_pnl: float = Field(0, description="当日累计总盈亏 = 已实现 + 浮动（元）")
    return_pct: float = Field(0, description="当日累计收益率 %（相对累计买入本金）")


class EquitySummary(BaseModel):
    """收益曲线区间汇总。"""

    latest_market_value: float = Field(0, description="最新持仓市值（元）")
    latest_return_pct: float = Field(0, description="最新累计收益率 %")
    max_return_pct: float = Field(0, description="区间最高累计收益率 %")
    min_return_pct: float = Field(0, description="区间最低累计收益率 %")
    max_drawdown_pct: float = Field(0, description="区间最大回撤 %（正数表示回撤幅度）")
    total_invested: float = Field(0, description="累计买入本金（含手续费，元）")
    total_pnl: float = Field(0, description="累计总盈亏（元）")


class EquityCurveOut(BaseModel):
    """收益曲线输出（由交易流水 + ETF 历史价回放重建）。"""

    days: int = Field(..., description="请求区间（自然日）")
    points: list[EquityPoint] = Field(default_factory=list, description="按日期升序的每日点位")
    summary: EquitySummary = Field(default_factory=EquitySummary, description="区间汇总")


class PerformanceOut(BaseModel):
    """获利分析总结评估（已实现 + 浮动 + 交易统计）。"""

    total_pnl: float = Field(0, description="总盈亏 = 已实现 + 浮动（元）")
    realized_pnl: float = Field(0, description="已实现盈亏（元）")
    unrealized_pnl: float = Field(0, description="浮动盈亏（元）")
    total_cost: float = Field(0, description="当前持仓成本合计（元）")
    total_invested: float = Field(0, description="累计买入本金（元）")
    total_return_pct: float = Field(0, description="总收益率 %（相对累计买入本金）")
    open_positions: int = Field(0, description="当前持仓笔数")
    closed_positions: int = Field(0, description="已平仓笔数")
    closed_trades: int = Field(0, description="平仓成交笔数（卖出笔数）")
    win_trades: int = Field(0, description="盈利平仓笔数")
    loss_trades: int = Field(0, description="亏损平仓笔数")
    win_rate: float = Field(0, description="胜率 %（盈利平仓 / 总平仓）")
    buy_count: int = Field(0, description="买入笔数")
    sell_count: int = Field(0, description="卖出笔数")
    best_trade_pnl: float = Field(0, description="最佳平仓盈亏（元）")
    worst_trade_pnl: float = Field(0, description="最差平仓盈亏（元）")
    avg_trade_pnl: float = Field(0, description="平均每笔平仓盈亏（元）")
    gross_profit: float = Field(0, description="盈利平仓合计（元）")
    gross_loss: float = Field(0, description="亏损平仓合计（元，负值）")
    profit_factor: float | None = Field(
        None,
        description="盈亏比 = 总盈利 / |总亏损|；无亏损记录时为 null",
    )
    avg_holding_days: float = Field(0, description="平均持仓天数")
    summary: str = Field("", description="面向客户的中文总结")
