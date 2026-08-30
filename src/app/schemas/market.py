"""行情相关 Schema。"""

from datetime import datetime

from pydantic import BaseModel, Field


class GoldQuoteOut(BaseModel):
    """黄金现货报价输出。"""

    symbol: str
    price_usd: float = Field(..., gt=0)
    change_pct: float = Field(..., description="涨跌幅 %")
    updated_at: datetime
