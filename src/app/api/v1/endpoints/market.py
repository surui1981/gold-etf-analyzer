"""市场行情端点：报价 + 趋势追踪 + 对照。"""

from fastapi import APIRouter, Depends, Query

from app.dependencies import (
    get_compare_service,
    get_market_data_repository,
    get_trend_service,
)
from app.repositories.market_data import MarketDataRepository
from app.schemas.market import GoldCompareOut, GoldQuoteOut, GoldTrendOut
from app.services.compare import GoldCompareService
from app.services.trend import TrendService

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/gold", response_model=GoldQuoteOut, summary="黄金ETF最新报价")
async def gold_quote(
    repo: MarketDataRepository = Depends(get_market_data_repository),
) -> GoldQuoteOut:
    """获取黄金ETF最新报价（AKShare 实时数据，失败自动降级 Mock）。"""
    quote = await repo.get_gold_quote()
    return GoldQuoteOut(
        symbol=quote.symbol,
        price_usd=quote.price_usd,
        change_pct=quote.change_pct,
        updated_at=quote.updated_at,
    )


@router.get("/gold/trend", response_model=GoldTrendOut, summary="黄金2个月趋势追踪")
async def gold_trend(
    days: int = Query(60, ge=20, le=250, description="追踪的交易日数量（默认约2个月）"),
    service: TrendService = Depends(get_trend_service),
) -> GoldTrendOut:
    """返回黄金ETF近 N 个交易日趋势：价格序列 + MA5/MA20/MA40 + 方向判定。

    数据源为 AKShare（东方财富ETF历史行情），采集失败时回退 Mock。
    """
    return await service.analyze(days=days)


@router.get("/gold/ny-trend", response_model=GoldTrendOut, summary="纽约金60天趋势曲线")
async def ny_gold_trend(
    days: int = Query(60, ge=20, le=250, description="追踪的交易日数量（默认60天）"),
    service: TrendService = Depends(get_trend_service),
) -> GoldTrendOut:
    """纽约金（COMEX 黄金期货 GC，美元/盎司）连续 N 天价格曲线与趋势。

    与国内黄金（ETF/上海金）对照，观察国际金价走势。
    """
    return await service.analyze(days=days, target="ny")


@router.get("/gold/compare", response_model=GoldCompareOut, summary="黄金ETF vs 克价对照")
async def gold_compare(
    days: int = Query(60, ge=20, le=250, description="对照的交易日数量"),
    service: GoldCompareService = Depends(get_compare_service),
) -> GoldCompareOut:
    """黄金ETF（518880）与黄金克价（上海金 Au99.99，元/克）区间表现对照。

    按公共交易日对齐，各自归一化（起点=100），输出涨跌幅与领先判定。
    """
    return await service.compare(days=days)
