"""依赖注入容器：集中管理 FastAPI 依赖，方便测试时替换。"""

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.analysis import AnalysisRepository
from app.repositories.db import async_session_factory
from app.repositories.market_data import MarketDataRepository
from app.repositories.position import PositionRepository
from app.services.analysis import AnalysisService
from app.services.compare import GoldCompareService
from app.services.decision import DecisionService
from app.services.position import PositionService
from app.services.scoring import OpportunityScoringService
from app.services.trend import TrendService


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """每个请求一个数据库会话，请求结束自动关闭。"""
    async with async_session_factory() as session:
        yield session


def get_scoring_service() -> OpportunityScoringService:
    """评分引擎为无状态纯函数，直接返回单例。"""
    return OpportunityScoringService()


def get_market_data_repository() -> MarketDataRepository:
    """行情数据源抽象；当前为 Mock 实现，后续可替换真实源。"""
    return MarketDataRepository()


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


def get_trend_service(
    repo: MarketDataRepository = Depends(get_market_data_repository),
) -> TrendService:
    """黄金趋势追踪服务依赖（行情仓储）。"""
    return TrendService(repo=repo)


async def get_position_repository(
    session: AsyncSession = Depends(get_db_session),
) -> PositionRepository:
    """持仓仓储依赖。"""
    return PositionRepository(session)


def get_position_service(
    repo: PositionRepository = Depends(get_position_repository),
    market: MarketDataRepository = Depends(get_market_data_repository),
) -> PositionService:
    """交易面服务依赖（持仓仓储 + 行情）。"""
    return PositionService(repo=repo, market=market)


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
