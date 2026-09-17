"""依赖注入容器：集中管理 FastAPI 依赖，方便测试时替换。"""

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.repositories.account import AccountRepository
from app.repositories.analysis import AnalysisRepository
from app.repositories.central_bank import CentralBankPurchaseRepository
from app.repositories.db import async_session_factory
from app.repositories.market_data import MarketDataRepository
from app.repositories.market_providers import build_provider_bundle
from app.repositories.news import NewsScoreRepository
from app.repositories.position import PositionRepository
from app.repositories.review import GoldPriceRepository
from app.repositories.settings import SettingRepository
from app.repositories.snapshot import SnapshotRepository
from app.repositories.telemetry import TelemetryRepository
from app.services.account import AccountService
from app.services.analysis import AnalysisService
from app.services.central_bank import CentralBankService
from app.services.compare import GoldCompareService
from app.services.decision import DecisionService
from app.services.freshness import FreshnessService
from app.services.news import NewsScoreService
from app.services.portfolio import PortfolioAnalyticsService
from app.services.position import PositionService
from app.services.review import ReviewService
from app.services.scoring import OpportunityScoringService
from app.services.settings import WeightService
from app.services.snapshot import DailySnapshotService
from app.services.telemetry import TelemetryService
from app.services.trades import TradeHistoryService
from app.services.trend import TrendService


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """每个请求一个数据库会话，请求结束自动关闭。"""
    async with async_session_factory() as session:
        yield session


# 注：央行购金工厂放在靠前位置（get_trend_service 依赖 get_central_bank_service）


async def get_central_bank_repository(
    session: AsyncSession = Depends(get_db_session),
) -> CentralBankPurchaseRepository:
    """央行购金 DB 仓储依赖。"""
    return CentralBankPurchaseRepository(session)


def get_central_bank_service(
    repo: CentralBankPurchaseRepository = Depends(get_central_bank_repository),
) -> CentralBankService:
    """央行购金业务服务依赖。"""
    return CentralBankService(repo=repo)


def get_scoring_service() -> OpportunityScoringService:
    """评分引擎为无状态纯函数，直接返回单例。"""
    return OpportunityScoringService()


def get_market_data_repository(
    settings: Settings = Depends(get_settings),
) -> MarketDataRepository:
    """行情数据源仓储（V0.59.0 配置化）。

    按 ``settings.market_provider`` 自动解析 provider bundle：
    - ``akshare``（默认）：东财 + 新浪 + 英为财情 + gold-api + H.15
    - ``mock``：纯内存确定性序列（离线演示 / 测试）
    - ``eastmoney_only``：仅东财 ETF
    - ``sina_only``：仅新浪 ETF（东财 403 时）
    """
    bundle = build_provider_bundle(settings)
    return MarketDataRepository(bundle=bundle, settings=settings)


async def get_analysis_repository(
    session: AsyncSession = Depends(get_db_session),
) -> AnalysisRepository:
    """分析记录仓储依赖。"""
    return AnalysisRepository(session)


def get_analysis_service(
    repo: AnalysisRepository = Depends(get_analysis_repository),
    scoring: OpportunityScoringService = Depends(get_scoring_service),
) -> AnalysisService:
    """机会分析编排服务依赖（仓储 + 评分引擎）。"""
    return AnalysisService(repo=repo, scoring=scoring)


async def get_setting_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SettingRepository:
    """应用配置仓储依赖。"""
    return SettingRepository(session)


def get_weight_service(
    repo: SettingRepository = Depends(get_setting_repository),
) -> WeightService:
    """权重配置服务依赖。"""
    return WeightService(repo)


async def get_news_repository(
    session: AsyncSession = Depends(get_db_session),
) -> NewsScoreRepository:
    """消息面打分仓储依赖。"""
    return NewsScoreRepository(session)


def get_news_score_service(
    repo: NewsScoreRepository = Depends(get_news_repository),
) -> NewsScoreService:
    """消息面评估服务依赖。"""
    return NewsScoreService(repo)


def get_trend_service(
    repo: MarketDataRepository = Depends(get_market_data_repository),
    settings: WeightService = Depends(get_weight_service),
    news: NewsScoreService = Depends(get_news_score_service),
    central_bank: CentralBankService = Depends(get_central_bank_service),
) -> TrendService:
    """黄金趋势追踪服务依赖（行情仓储 + 权重配置 + 消息面评估 + 央行购金服务）。

    ``central_bank`` 注入后，宏观因子 ``cb_gold`` 会从 ``central_bank_purchases`` 表自动计算
    T12M（不再依赖 STATIC_REF 硬编码）。空表时回退 STATIC_REF，单测时不注入也保持兼容。
    """
    return TrendService(
        repo=repo,
        settings=settings,
        news=news,
        central_bank=central_bank,
    )


async def get_snapshot_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SnapshotRepository:
    """每日快照仓储依赖。"""
    return SnapshotRepository(session)


def get_snapshot_service(
    repo: SnapshotRepository = Depends(get_snapshot_repository),
    trend: TrendService = Depends(get_trend_service),
) -> DailySnapshotService:
    """每日快照服务依赖（快照仓储 + 趋势评估）。"""
    return DailySnapshotService(repo=repo, trend=trend)


async def get_gold_price_repository(
    session: AsyncSession = Depends(get_db_session),
) -> GoldPriceRepository:
    """黄金价格日历仓储依赖（研判复盘的对比基准）。"""
    return GoldPriceRepository(session)


def get_review_service(
    gold: GoldPriceRepository = Depends(get_gold_price_repository),
    news: NewsScoreRepository = Depends(get_news_repository),
    trend: TrendService = Depends(get_trend_service),
) -> ReviewService:
    """研判复盘服务依赖（价格日历 + 打分明细 + 趋势服务用于回填）。"""
    return ReviewService(gold=gold, news=news, trend=trend)


async def get_position_repository(
    session: AsyncSession = Depends(get_db_session),
) -> PositionRepository:
    """持仓仓储依赖。"""
    return PositionRepository(session)


async def get_account_repository(
    session: AsyncSession = Depends(get_db_session),
) -> AccountRepository:
    """账本仓储依赖。"""
    return AccountRepository(session)


def get_account_service(
    repo: AccountRepository = Depends(get_account_repository),
    positions: PositionRepository = Depends(get_position_repository),
) -> AccountService:
    """账本服务依赖（账本仓储 + 持仓仓储，用于归档前的未平仓校验与统计）。"""
    return AccountService(repo=repo, positions=positions)


def get_position_service(
    repo: PositionRepository = Depends(get_position_repository),
    market: MarketDataRepository = Depends(get_market_data_repository),
    accounts: AccountService = Depends(get_account_service),
) -> PositionService:
    """交易面服务依赖（持仓仓储 + 行情 + 账本解析）。"""
    return PositionService(repo=repo, market=market, accounts=accounts)


def get_trade_history_service(
    repo: PositionRepository = Depends(get_position_repository),
) -> TradeHistoryService:
    """交易历史服务依赖（持仓仓储：流水 + 持仓联表查询）。"""
    return TradeHistoryService(repo=repo)


def get_portfolio_analytics_service(
    repo: PositionRepository = Depends(get_position_repository),
    market: MarketDataRepository = Depends(get_market_data_repository),
) -> PortfolioAnalyticsService:
    """交易业绩分析服务依赖（持仓仓储 + 行情仓储）。

    为持仓页提供收益曲线与获利分析：无新增数据表，曲线由交易流水回放重建。
    """
    return PortfolioAnalyticsService(repo=repo, market=market)


def get_decision_service(
    trend: TrendService = Depends(get_trend_service),
    position: PositionService = Depends(get_position_service),
) -> DecisionService:
    """购买决策引擎依赖（趋势指数 + 持仓状态）。"""
    return DecisionService(trend=trend, position=position)


def get_compare_service(
    repo: MarketDataRepository = Depends(get_market_data_repository),
) -> GoldCompareService:
    """ETF vs 克价对照服务依赖（行情仓储）。"""
    return GoldCompareService(repo=repo)


def get_freshness_service(
    repo: MarketDataRepository = Depends(get_market_data_repository),
) -> FreshnessService:
    """数据时效服务依赖（行情仓储的采集元信息 + 交易时段）。"""
    return FreshnessService(repo=repo)


# V0.68.0 —— 前端埋点（白名单校验 + append-only 入库）


async def get_telemetry_repository(
    session: AsyncSession = Depends(get_db_session),
) -> TelemetryRepository:
    """埋点事件仓储依赖。"""
    return TelemetryRepository(session)


def get_telemetry_service(
    repo: TelemetryRepository = Depends(get_telemetry_repository),
) -> TelemetryService:
    """埋点业务编排服务依赖。"""
    return TelemetryService(repo=repo)
