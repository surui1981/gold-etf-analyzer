"""市场行情端点：报价 + 趋势追踪 + 对照。"""

from fastapi import APIRouter, Depends, Query

from app.dependencies import (
    get_compare_service,
    get_freshness_service,
    get_market_data_repository,
    get_trend_service,
)
from app.repositories.market_data import MarketDataRepository
from app.schemas.market import (
    FreshnessOut,
    GoldCompareOut,
    GoldCompareSeries,
    GoldEtfQuoteOut,
    GoldQuoteOut,
    GoldTrendOut,
    SilverCompareOut,
    SilverComparePoint,
    SilverEtfQuoteOut,
    SilverGramQuoteOut,
    SilverQuoteOut,
    SilverTrendMetrics,
    SilverTrendOut,
    SilverTrendPoint,
)
from app.services.compare import GoldCompareService
from app.services.freshness import FreshnessService
from app.services.trend import TrendService, moving_average

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/health", summary="数据源健康度统计")
async def market_health(
    repo: MarketDataRepository = Depends(get_market_data_repository),
) -> dict:
    """各数据源状态：live（真实）/ mock（降级）。

    说明：V0.52 数据源重构（零KEY公开源）后，健康度统计已并入实例级
    ``source_status()``；原 ``health_stats()`` 进程内累计指标已移除。
    """
    return {
        "sources": repo.source_status(),
        "note": "status=live 真实 / mock 降级；进程级状态，重启后清零",
    }


@router.get("/freshness", response_model=FreshnessOut, summary="数据时效与交易时段")
async def market_freshness(
    service: FreshnessService = Depends(get_freshness_service),
) -> FreshnessOut:
    """各市场数据时效分级 + 交易时段 + 采集时间戳（UX 6.1 全站时效条数据源）。

    时效等级：realtime 实时 / delayed 延时（盘后静态）/ t1 T-1（上一交易日）/
    lagged 滞后多日 / cached 缓存（数据源失败，可能过期）/ mock 演示（非真实行情）。
    交易时段：open 交易中 / pre 盘前 / break 盘中休整 / closed 休市（纽约金按美东时间，
    上海金与 ETF 按北京时间；均不含法定节假日）。
    """
    return await service.report()


@router.get("/gold", response_model=GoldQuoteOut, summary="国际金价 XAU/USD 报价")
async def gold_quote(
    repo: MarketDataRepository = Depends(get_market_data_repository),
) -> GoldQuoteOut:
    """获取国际金价 XAU/USD（美元/盎司）实时报价，用于纽约金投资指引与涨跌提醒。

    注意：**这不是 518880 ETF 的人民币价格**。持仓估值 / 开仓预填 / 清仓请使用
    ``GET /market/gold/etf-quote``（元/份）；此前二者混用导致盈亏计算错误，V0.61.0 修正。
    """
    quote = await repo.get_gold_quote()
    return GoldQuoteOut(
        symbol=quote.symbol,
        price_usd=quote.price_usd,
        change_pct=quote.change_pct,
        updated_at=quote.updated_at,
    )


@router.get(
    "/gold/etf-quote",
    response_model=GoldEtfQuoteOut,
    summary="黄金ETF（518880）报价（元/份）",
)
async def gold_etf_quote(
    repo: MarketDataRepository = Depends(get_market_data_repository),
) -> GoldEtfQuoteOut:
    """518880 华安黄金ETF 最新成交价（人民币元/份）——持仓估值与交易价格源。

    与 ``/market/gold``（XAU/USD 国际金价）严格区分：本接口与收益曲线同源，
    用于持仓市值、浮动盈亏、开仓 / 加减仓预填价与清仓价。

    返回字段为 ``price``（元/份）+ ``currency`` / ``unit`` 显式单位，
    不使用易混淆的 ``price_usd`` 命名。
    """
    quote = await repo.get_gold_etf_quote()
    return GoldEtfQuoteOut(
        symbol=quote.symbol,
        price=quote.price_usd,
        currency="CNY",
        unit="元/份",
        change_pct=quote.change_pct,
        updated_at=quote.updated_at,
    )


@router.get(
    "/gold/gram-quote",
    response_model=GoldQuoteOut,
    summary="上海金 Au99.99 克价（元/克，V0.70.0 P2 #8）",
)
async def gold_gram_quote(
    repo: MarketDataRepository = Depends(get_market_data_repository),
) -> GoldQuoteOut:
    """上海黄金交易所 Au99.99 实时克价（人民币元/克）——「按克」开/加/减仓的折算基准。

    V0.70.0（P2 #8）新增：与 ``get_gold_gram_quote`` 同源，供前端 ``sharesFromGrams``
    实时折算使用；后端 ``PositionService.open`` 也调用相同仓储确保一致性。
    """
    quote = await repo.get_gold_gram_quote()
    return GoldQuoteOut(
        symbol=quote.symbol,
        price_usd=quote.price_usd,
        change_pct=quote.change_pct,
        updated_at=quote.updated_at,
    )


@router.get(
    "/gold/trend",
    response_model=GoldTrendOut,
    summary="黄金趋势追踪（投资指引基准，支持多时间框架）",
)
async def gold_trend(
    days: int = Query(
        60,
        ge=20,
        le=750,
        description="追踪的交易日数量（默认 60；上限 750 ≈ 3 个交易年，支持 24M 月 K 聚合）",
    ),
    target: str = Query(
        "ny",
        pattern="^(ny|etf|gram)$",
        description="指引标的：ny=纽约金COMEX（默认投资指引基准）/ etf=黄金ETF 518880 / gram=上海金Au99.99",
    ),
    interval: str = Query(
        "D",
        pattern="^[DWM]$",
        description="V0.64.0 多时间框架：K 线聚合粒度 D=日 K / W=周 K（ISO 周界）/ M=月 K。"
        "W/M 模式下 days 需 ≥ 365 / 730 才有完整序列；MA 在聚合后序列上重算。",
    ),
    service: TrendService = Depends(get_trend_service),
) -> GoldTrendOut:
    """返回近 N 个交易日趋势：价格序列 + MA5/MA20/MA40 + 方向判定 + 综合趋势评估指数。

    投资指引基准默认为纽约金（COMEX GC，美元/盎司）——连续交易、夜盘覆盖国内休市，
    对国内金价具备领先指示意义；持仓与交易仍以人民币 ETF/上海金计。

    **V0.64.0**：新增 ``interval`` 参数，支持日/周/月三档时间框架切换。
    """
    return await service.analyze(days=days, target=target, interval=interval)


@router.get("/gold/ny-trend", response_model=GoldTrendOut, summary="纽约金60天趋势曲线")
async def ny_gold_trend(
    days: int = Query(
        60,
        ge=20,
        le=750,
        description="追踪的交易日数量（默认60天；上限 750 支持多时间框架）",
    ),
    interval: str = Query(
        "D",
        pattern="^[DWM]$",
        description="V0.64.0：K 线聚合粒度 D / W / M",
    ),
    service: TrendService = Depends(get_trend_service),
) -> GoldTrendOut:
    """纽约金（COMEX 黄金期货 GC，美元/盎司）连续 N 天价格曲线与趋势。

    与国内黄金（ETF/上海金）对照，观察国际金价走势。
    """
    return await service.analyze(days=days, target="ny", interval=interval)


@router.get("/gold/compare", response_model=GoldCompareOut, summary="黄金ETF vs 克价对照")
async def gold_compare(
    days: int = Query(60, ge=20, le=750, description="对照的交易日数量"),
    service: GoldCompareService = Depends(get_compare_service),
) -> GoldCompareOut:
    """黄金ETF（518880）与黄金克价（上海金 Au99.99，元/克）区间表现对照。

    按公共交易日对齐，各自归一化（起点=100），输出涨跌幅与领先判定。
    """
    return await service.compare(days=days)


# ───────────────────── V0.71.0：白银 5 端点 ─────────────────────


@router.get("/silver/quote", response_model=SilverQuoteOut, summary="纽约白银 SI 报价")
async def silver_quote(
    repo: MarketDataRepository = Depends(get_market_data_repository),
) -> SilverQuoteOut:
    """纽约白银（COMEX SI 期货主力，美元/盎司）最新报价。

    与 ``/market/silver/etf-quote``（562800 元/份）口径严格区分。
    """
    quote = await repo.get_silver_ny_quote()
    return SilverQuoteOut(
        symbol=quote.symbol,
        price_usd=quote.price_usd,
        change_pct=quote.change_pct,
        updated_at=quote.updated_at,
    )


@router.get(
    "/silver/etf-quote",
    response_model=SilverEtfQuoteOut,
    summary="白银ETF（562800）报价（元/份）",
)
async def silver_etf_quote(
    repo: MarketDataRepository = Depends(get_market_data_repository),
) -> SilverEtfQuoteOut:
    """562800 易方达白银 ETF 最新成交价（人民币元/份）。"""
    quote = await repo.get_silver_etf_quote()
    return SilverEtfQuoteOut(
        symbol=quote.symbol,
        price=quote.price_usd,
        currency="CNY",
        unit="元/份",
        change_pct=quote.change_pct,
        updated_at=quote.updated_at,
    )


@router.get(
    "/silver/gram-quote",
    response_model=SilverGramQuoteOut,
    summary="白银克价报价（V0.73.0 N+16，元/克）",
)
async def silver_gram_quote(
    repo: MarketDataRepository = Depends(get_market_data_repository),
) -> SilverGramQuoteOut:
    """白银克价（人民币 元/克）最新报价。

    **口径**：``gram_price = silver_etf_price × 1000``
    （562800 易方达白银 ETF 单位 ≈ 1000 克白银现货，公开换算）。

    与 ``/market/silver/etf-quote``（562800 元/份）口径严格区分。
    与 ``/market/silver/quote``（NY SI 美元/盎司）口径严格区分。
    """
    quote = await repo.get_silver_gram_quote()
    return SilverGramQuoteOut(
        symbol=quote.symbol,
        price=quote.price_usd,
        currency="CNY",
        unit="元/克",
        source="silver_etf×1000",
        change_pct=quote.change_pct,
        updated_at=quote.updated_at,
    )


@router.get(
    "/silver/trend",
    response_model=SilverTrendOut,
    summary="白银 ETF 趋势追踪（V0.71.0）",
)
async def silver_trend(
    days: int = Query(
        60,
        ge=20,
        le=750,
        description="追踪的交易日数量（默认 60；上限 750 支持多时间框架）",
    ),
    interval: str = Query(
        "D",
        pattern="^[DWM]$",
        description="V0.64.0：K 线聚合粒度 D / W / M",
    ),
    service: TrendService = Depends(get_trend_service),
) -> SilverTrendOut:
    """白银 ETF（562800）连续 N 天价格曲线 + 趋势评估指数（复用 TrendService.analyze）。

    与黄金趋势同一指标算法，仅数据源切换为白银 ETF。
    """
    result = await service.analyze(days=days, target="silver_etf", interval=interval)
    return _gold_to_silver(result)


@router.get(
    "/silver/ny-trend",
    response_model=SilverTrendOut,
    summary="纽约白银 SI 趋势追踪（V0.71.0）",
)
async def silver_ny_trend(
    days: int = Query(
        60,
        ge=20,
        le=750,
        description="追踪的交易日数量（默认60天；上限 750 支持多时间框架）",
    ),
    interval: str = Query(
        "D",
        pattern="^[DWM]$",
        description="V0.64.0：K 线聚合粒度 D / W / M",
    ),
    service: TrendService = Depends(get_trend_service),
) -> SilverTrendOut:
    """纽约白银（COMEX SI，美元/盎司）连续 N 天价格曲线与趋势。"""
    result = await service.analyze(days=days, target="silver_ny", interval=interval)
    return _gold_to_silver(result)


@router.get(
    "/silver/compare",
    response_model=SilverCompareOut,
    summary="白银 ETF vs 纽约白银 对照（V0.71.0）",
)
async def silver_compare(
    days: int = Query(60, ge=20, le=750, description="对照的交易日数量"),
    repo: MarketDataRepository = Depends(get_market_data_repository),
) -> SilverCompareOut:
    """白银 ETF（562800，元/份）与纽约白银（COMEX SI，美元/盎司）区间表现对照。

    由于计价单位不同（CNY 元/份 vs USD 美元/盎司），归一化仅展示**相对涨跌走势**，
    不直接做绝对价位对照；领先判定基于各自归一化序列的相对涨幅。
    """
    etf_klines = await repo.get_silver_etf_history(days=days)
    ny_klines = await repo.get_silver_ny_history(days=days)
    etf_map = {k.date: k for k in etf_klines}
    ny_map = {k.date: k for k in ny_klines}
    common_dates = sorted(etf_map.keys() & ny_map.keys())
    if len(common_dates) < 2:
        raise ValueError("白银 ETF 与 NY 公共交易日不足，无法对照")

    etf_closes = [etf_map[d].close for d in common_dates]
    ny_closes = [ny_map[d].close for d in common_dates]
    e0, n0 = etf_closes[0], ny_closes[0]
    points = [
        SilverComparePoint(
            date=d,
            silver_etf=round(e / e0 * 100, 2),
            silver_ny=round(n / n0 * 100, 2),
        )
        for d, e, n in zip(common_dates, etf_closes, ny_closes, strict=True)
    ]

    etf_series = _silver_series_metrics(
        "562800",
        "白银ETF易方达",
        etf_closes,
        [etf_map[d].high for d in common_dates],
        [etf_map[d].low for d in common_dates],
    )
    ny_series = _silver_series_metrics(
        "SI",
        "纽约白银COMEX",
        ny_closes,
        [ny_map[d].high for d in common_dates],
        [ny_map[d].low for d in common_dates],
    )

    lead_gap = round(abs(etf_series.change_pct - ny_series.change_pct), 2)
    if etf_series.change_pct > ny_series.change_pct:
        leader = "silver_etf"
    elif ny_series.change_pct > etf_series.change_pct:
        leader = "silver_ny"
    else:
        leader = "tie"

    return SilverCompareOut(
        days=len(common_dates),
        silver_etf=etf_series,
        silver_ny=ny_series,
        points=points,
        leader=leader,
        lead_gap=lead_gap,
        summary=(
            f"近2个月白银对照：ETF {etf_series.change_pct:+.2f}% vs 纽约白银 {ny_series.change_pct:+.2f}%，"
            f"涨跌幅差 {lead_gap:.2f} 个百分点；"
            f"{'白银ETF 领先' if leader == 'silver_etf' else '纽约白银领先' if leader == 'silver_ny' else '两者持平'}。"
            "（注：ETF 与 NY 计价单位不同，归一化仅展示相对涨跌走势，不直接做绝对价位对照。）"
        ),
    )


def _gold_to_silver(gold: GoldTrendOut) -> SilverTrendOut:
    """将 GoldTrendOut 转换为 SilverTrendOut（结构对称字段映射，V0.71.0）。"""
    return SilverTrendOut(
        symbol=gold.symbol,
        name=gold.name,
        days=gold.days,
        points=[
            SilverTrendPoint(date=p.date, close=p.close, ma5=p.ma5, ma20=p.ma20, ma40=p.ma40)
            for p in gold.points
        ],
        metrics=SilverTrendMetrics(
            start_date=gold.metrics.start_date,
            end_date=gold.metrics.end_date,
            trading_days=gold.metrics.trading_days,
            start_price=gold.metrics.start_price,
            end_price=gold.metrics.end_price,
            change_pct=gold.metrics.change_pct,
            high=gold.metrics.high,
            low=gold.metrics.low,
            ma20=gold.metrics.ma20,
            ma40=gold.metrics.ma40,
            change_pct_1d=gold.metrics.change_pct_1d,
            change_pct_5d=gold.metrics.change_pct_5d,
            direction=gold.metrics.direction,
            unit=gold.metrics.unit,
            summary=gold.metrics.summary,
        ),
        indicators=gold.indicators,
        index=gold.index,
        macro=gold.macro,
        news=gold.news,
        data_sources=gold.data_sources,
        degraded=gold.degraded,
        freshness=gold.freshness,
        interval=gold.interval,
        served_at=gold.served_at,
    )


def _silver_series_metrics(
    symbol: str,
    name: str,
    closes: list[float],
    highs: list[float],
    lows: list[float],
) -> GoldCompareSeries:
    """由价格序列计算白银对照序列指标（复用 GoldCompareSeries 结构）。"""
    from app.schemas.market import TrendDirection

    start_price, end_price = closes[0], closes[-1]
    change_pct = (end_price - start_price) / start_price * 100 if start_price else 0.0
    ma20 = moving_average(closes, 20)[-1]
    ma40 = moving_average(closes, 40)[-1]
    if change_pct >= 0 and ma20 is not None and end_price > ma20:
        direction = TrendDirection.UP
    elif change_pct < 0 and ma20 is not None and end_price < ma20:
        direction = TrendDirection.DOWN
    else:
        direction = TrendDirection.SIDEWAYS
    return GoldCompareSeries(
        symbol=symbol,
        name=name,
        start_price=round(start_price, 3),
        end_price=round(end_price, 3),
        change_pct=round(change_pct, 2),
        high=round(max(highs), 3),
        low=round(min(lows), 3),
        ma20=ma20,
        ma40=ma40,
        direction=direction,
    )
