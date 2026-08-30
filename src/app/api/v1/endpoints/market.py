"""市场行情端点。"""

from fastapi import APIRouter, Depends

from app.dependencies import get_market_data_repository
from app.repositories.market_data import MarketDataRepository
from app.schemas.market import GoldQuoteOut

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/gold", response_model=GoldQuoteOut, summary="黄金现货报价")
async def gold_quote(
    repo: MarketDataRepository = Depends(get_market_data_repository),
) -> GoldQuoteOut:
    """获取黄金现货报价（当前为 Mock 数据，接入真实行情源后不变更接口）。"""
    quote = await repo.get_gold_quote()
    return GoldQuoteOut(
        symbol=quote.symbol,
        price_usd=quote.price_usd,
        change_pct=quote.change_pct,
        updated_at=quote.updated_at,
    )
