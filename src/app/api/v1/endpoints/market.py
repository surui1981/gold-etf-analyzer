"""市场行情端点：报价 + 趋势追踪 + 对照。"""

from fastapi import APIRouter, Depends, Query

from app.dependencies import (
    get_compare_service,
    get_market_data_repository,
    get_trend_service,
)
from app.repositories.market_data import MarketDataRepository, health_stats
from app.schemas.market import GoldCompareOut, GoldQuoteOut, GoldTrendOut
from app.services.compare import GoldCompareService
from app.services.trend import TrendService

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/health", summary="数据源健康度统计")
async def market_health() -> dict:
    """各数据源采集健康度：成功率 / 平均耗时 / 采集次数 / 最近状态（进程内近态统计）。"""
    return {
        "sources": health_stats(),
        "note": "进程内近态统计，重启后清零；status=live 真实 / mock 降级",
    }


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


@router.get("/gold/trend", response_model=GoldTrendOut, summary="黄金2个月趋势追踪（投资指引基准）")
async def gold_trend(
    days: int = Query(60, ge=20, le=250, description="追踪的交易日数量（默认约2个月）"),
    target: str = Query(
        "ny",
        pattern="^(ny|etf|gram)$",
        description="指引标的：ny=纽约金COMEX（默认投资指引基准）/ etf=黄金ETF 518880 / gram=上海金Au99.99",
    ),
    service: TrendService = Depends(get_trend_service),
) -> GoldTrendOut:
    """返回近 N 个交易日趋势：价格序列 + MA5/MA20/MA40 + 方向判定 + 综合趋势评估指数。

    投资指引基准默认为纽约金（COMEX GC，美元/盎司）——连续交易、夜盘覆盖国内休市，
    对国内金价具备领先指示意义；持仓与交易仍以人民币 ETF/上海金计。
    """
    return await service.analyze(days=days, target=target)


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
