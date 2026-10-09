"""依赖注入容器：集中管理 FastAPI 依赖，方便测试时替换。"""

from collections.abc import AsyncIterator
from functools import lru_cache

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.user import ROLE_OWNER, User
from app.repositories.account import AccountRepository
from app.repositories.analysis import AnalysisRepository
from app.repositories.central_bank import CentralBankPurchaseRepository
from app.repositories.db import async_session_factory
from app.repositories.macro_factor_history import MacroFactorHistoryRepository  # V0.79.0 Step E
from app.repositories.market_data import MarketDataRepository
from app.repositories.market_providers import build_provider_bundle
from app.repositories.news import NewsScoreRepository
from app.repositories.position import PositionRepository
from app.repositories.review import GoldPriceRepository
from app.repositories.settings import SettingRepository
from app.repositories.snapshot import SnapshotRepository
from app.repositories.telemetry import TelemetryRepository
from app.repositories.user import SessionRepository, UserRepository
from app.services.account import AccountService
from app.services.alert import AlertDispatcher  # V0.72.0 P3-b
from app.services.analysis import AnalysisService
from app.services.auth import AuthService, LoginThrottle  # V0.75.0
from app.services.backtest import BacktestService
from app.services.central_bank import CentralBankService
from app.services.compare import GoldCompareService
from app.services.decision import DecisionService
from app.services.freshness import FreshnessService
from app.services.macro import MacroFactorService  # V0.79.0 Step E
from app.services.macro_thresholds import MacroThresholdCalculator  # V0.79.0 Step E
from app.services.news import NewsScoreService
from app.services.portfolio import PortfolioAnalyticsService
from app.services.position import PositionService
from app.services.resonance import ResonanceService
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


async def get_macro_factor_history_repository(
    session: AsyncSession = Depends(get_db_session),
) -> MacroFactorHistoryRepository:
    """每日宏观因子历史仓储依赖（V0.79.0 Step E）。"""
    return MacroFactorHistoryRepository(session)


def get_macro_threshold_calculator(
    repo: MacroFactorHistoryRepository = Depends(get_macro_factor_history_repository),
) -> MacroThresholdCalculator:
    """宏观阈值动态计算器依赖（V0.79.0 Step E）。

    V0.79.0 Step E commit 1 仅注册 provider；commit 2 才会把此 provider 接入
    ``get_trend_service`` 让 ``MacroFactorService`` 走动态阈值。
    """
    return MacroThresholdCalculator(repo=repo)


def get_scoring_service() -> OpportunityScoringService:
    """评分引擎为无状态纯函数，直接返回单例。"""
    return OpportunityScoringService()


def get_market_data_repository() -> MarketDataRepository:
    """行情数据源仓储（V0.59.0 配置化，V0.73.x+ 进程级单例）。

    按 ``settings.market_provider`` 自动解析 provider bundle：
    - ``akshare``（默认）：东财 + 新浪 + 英为财情 + gold-api + H.15
    - ``mock``：纯内存确定性序列（离线演示 / 测试）
    - ``eastmoney_only``：仅东财 ETF
    - ``sina_only``：仅新浪 ETF（东财 403 时）
    - ``silver_yahoo``（V0.73.0+）：白银走 Yahoo Finance（金仍走默认 akshare）

    V0.73.x+ 修复：原先每次请求都新建 ``MarketDataRepository``，
    导致进程级状态 ``_sources / _fetched_at / _last_date`` 被立刻丢弃，
    ``/api/v1/market/health`` 永远返回 ``{"sources":{}}`` 空字典（连带
    FreshnessService 看到所有市场都是"未采集"）。改用进程级 ``lru_cache``
    单例，所有请求复用同一份状态。

    测试时仍可通过 ``app.dependency_overrides[get_market_data_repository]``
    整体替换。
    """
    return _get_market_data_repository_singleton()


@lru_cache(maxsize=1)
def _get_market_data_repository_singleton() -> MarketDataRepository:
    """仓储进程级单例（延迟到首次调用时构造）。"""
    settings = get_settings()
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


def get_admin_token() -> str | None:
    """V0.72.0 P3-b / V0.82 单用户模式豁免。

    返回 ``settings.admin_token``；**单用户模式**（``AUTH_ENABLED=false``）或
    **dev 模式**（``ADMIN_TOKEN`` 未设）时返回 ``None`` ⇒ admin 鉴权跳过。

    由 :func:`app.middleware.admin_auth.require_admin` / :func:`require_admin_session`
    Depends 间接消费。

    ⚠ **单用户模式豁免**（V0.82）：LAN 部署默认 ``AUTH_ENABLED=false``，
    admin 鉴权不再需要配置（多用户场景才需要）。
    """
    settings = get_settings()
    if not settings.auth_enabled:
        # V0.82：单用户模式 → admin 鉴权整体豁免（防 LAN 多终端踩坑）
        return None
    return settings.admin_token


def get_weight_service(
    repo: SettingRepository = Depends(get_setting_repository),
) -> WeightService:
    """权重配置服务依赖。"""
    return WeightService(repo)


def get_alert_dispatcher() -> AlertDispatcher:
    """V0.72.0：告警分发器依赖（单例 in-process，去重状态跨请求保留）。

    设计要点：dispatcher 内部维护 ``_sent_today`` 去重表与 ``_quiet_queue`` 静默队列，
    因此不能在每个请求创建新实例（否则日内 4 次 warm 都会重复触发）。
    """
    if not hasattr(get_alert_dispatcher, "_instance"):
        get_alert_dispatcher._instance = AlertDispatcher()  # type: ignore[attr-defined]
    return get_alert_dispatcher._instance  # type: ignore[attr-defined]


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
    macro_thresholds: MacroThresholdCalculator = Depends(get_macro_threshold_calculator),
) -> TrendService:
    """黄金趋势追踪服务依赖（行情仓储 + 权重配置 + 消息面评估 + 央行购金服务 + 宏观阈值动态化）。

    - ``central_bank`` 注入后，宏观因子 ``cb_gold`` 会从 ``central_bank_purchases`` 表自动计算
      T12M（不再依赖 STATIC_REF 硬编码）。空表时回退 STATIC_REF，单测时不注入也保持兼容。
    - ``macro_thresholds``（V0.79.0 Step E）注入后，宏观因子 ``dxy/us10y/us30y/vix``
      走近 252 日滚动 90/10 分位，``cb_gold`` 永远走 hardcode。数据不足（< 60 样本）
      自动回退 hardcode。**运行时回滚路径**：把 ``get_macro_threshold_calculator``
      改为返回 None（无需 revert）。
    """
    macro = MacroFactorService(
        settings=settings,
        central_bank=central_bank,
        threshold_calculator=macro_thresholds,
    )
    return TrendService(
        repo=repo,
        macro=macro,
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


# V0.70.0 P2 #7 —— 共振信号服务


def get_resonance_service(
    trend: TrendService = Depends(get_trend_service),
    news: NewsScoreRepository = Depends(get_news_repository),
) -> ResonanceService:
    """共振信号服务依赖（趋势服务 + 消息面仓储，用于历史回放与命中统计）。"""
    return ResonanceService(trend=trend, news=news)


# V0.71.0 —— 回测服务


def get_backtest_service(
    session: AsyncSession = Depends(get_db_session),
    gold: GoldPriceRepository = Depends(get_gold_price_repository),
    weights: WeightService = Depends(get_weight_service),
    trend: TrendService = Depends(get_trend_service),
) -> BacktestService:
    """回测编排服务依赖（DB 会话 + 价格仓储 + 权重配置 + 趋势服务）。

    复用 daily_snapshots（参数面 + 评估值的历史「金标准」）做参数扫描；
    节流由 :mod:`app.services.backtest_throttle` 模块级维护。

    V0.79.0：注入 ``trend`` 以支持价格日历**按需自动回填** —— 此前价格日历
    只有「用户在 /review 页手工点复盘」一条写入路径，而回测依赖它，
    导致未回填时回测静默返回假结果（Sharpe 恒 0、命中率虚高）。
    """
    return BacktestService(session=session, gold=gold, weights=weights, trend=trend)


# V0.79.0 Step G —— 异步任务注册表（回测 run-async / 进度查询）


def get_task_registry():
    """异步任务注册表依赖（单例；模块级 dict + lock，详见 ``services/task_registry``）。

    命名上保留函数形式以遵循 ``dependencies.py`` 的「函数即 provider」惯例，
    但实际返回的是模块单例 —— 与 ``get_alert_dispatcher`` / ``_login_throttle_singleton``
    等「无 FastAPI 注入但需复用」单例同等依赖模式。
    """
    # 本地 import 避免模块初始化时的循环依赖
    from app.services import task_registry

    return task_registry


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


# ══════════════════ V0.75.0 认证骨架 ══════════════════


async def get_user_repository(
    session: AsyncSession = Depends(get_db_session),
) -> UserRepository:
    """用户仓储依赖。"""
    return UserRepository(session)


async def get_session_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SessionRepository:
    """会话仓储依赖。"""
    return SessionRepository(session)


@lru_cache(maxsize=1)
def _login_throttle_singleton() -> LoginThrottle:
    """登录节流器**进程级单例**。

    关键：失败计数必须跨请求累积。若每次请求新建 ``LoginThrottle``，
    计数器会随请求结束一起丢弃 → 锁定永不生效（等价于没做防爆破）。
    测试可用 ``app.dependency_overrides[get_login_throttle]`` 替换为可控实例。
    """
    settings = get_settings()
    return LoginThrottle(
        max_attempts=settings.login_max_attempts,
        window_seconds=settings.login_attempt_window_minutes * 60,
        lockout_seconds=settings.login_lockout_minutes * 60,
    )


def get_login_throttle() -> LoginThrottle:
    """登录节流器依赖（进程级单例）。"""
    return _login_throttle_singleton()


def get_auth_service(
    users: UserRepository = Depends(get_user_repository),
    sessions: SessionRepository = Depends(get_session_repository),
    throttle: LoginThrottle = Depends(get_login_throttle),
) -> AuthService:
    """认证服务依赖（用户仓储 + 会话仓储 + 进程级节流器）。"""
    return AuthService(users, sessions, throttle=throttle)


def get_current_user(request: Request) -> User | None:
    """当前登录用户；匿名返回 ``None``（不抛错）。

    由 :class:`app.middleware.auth.AuthMiddleware` 在 ``request.state`` 上预置。
    需要「必须登录」语义时改用 :func:`require_user`。
    """
    return getattr(request.state, "user", None)


def get_current_session_id(request: Request) -> str | None:
    """当前请求所用会话 ID（改密时用于保留当前设备登录）。"""
    return getattr(request.state, "session_id", None)


def require_user(
    request: Request,
    user: User | None = Depends(get_current_user),
) -> User:
    """要求已登录；匿名则 401。

    单用户模式（``AUTH_ENABLED=false``）下中间件不解析会话，
    ``request.state.user`` 恒为 None —— 但 ``require_user`` 只被「认证专属端点」
    （``/auth/me``、``/auth/logout``、``/auth/change-password``）使用，
    这些端点本身在单用户模式下无意义，故不会误伤既有流程。
    """
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthenticated", "message": "请先登录"},
            headers={"X-Auth-Required": "1"},
        )
    return user


def require_owner(user: User = Depends(require_user)) -> User:
    """要求当前登录用户是**所有者**（``role == ROLE_OWNER``），否则 403。

    ⚠⚠ **与 ``middleware.admin_auth.require_admin`` 是两个不同维度，切勿混淆**：

    - ``require_admin``校验的是**服务级凭据**（``X-Admin-Token`` 头 vs
      ``ADMIN_TOKEN`` env）—— 它回答「这个调用方是否被允许写」，
      与**谁登录了**无关，是防未授权写入的服务级闸门；
    - ``require_owner`` 校验的是**登录用户的角色** —— 它回答
      「当前这个人在本系统里能不能管别人」。

    用户管理走**后者**：因为操作对象就是「用户」，需要知道**操作者是谁**，
    否则无法实现「禁止停用/删除自己」这类防自锁规则
    （服务级 token 回答不了「你是哪个用户」）。

    两者**都保留**：用户管理端点同时受会话鉴权与角色鉴权约束，
    且仍可叠加 ``require_admin`` 作为服务级闸门。

    ⚠ 匿名/未登录由 :func:`require_user` 先抛 401，本依赖只负责 403。

    Args:
        user: 由 :func:`require_user` 解析出的登录用户

    Returns:
        角色为 owner 的 :class:`~app.models.user.User` 对象

    Raises:
        HTTPException 403: 已登录但不是所有者
    """
    if user.role != ROLE_OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "owner_required",
                "message": "仅所有者可管理用户",
            },
        )
    return user
