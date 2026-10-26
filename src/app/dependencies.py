"""依赖注入容器：集中管理 FastAPI 依赖，方便测试时替换。"""

from collections.abc import AsyncIterator
from functools import lru_cache
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    # 只在类型检查时导入 —— 运行期不引入，避免与 app.services.* 的循环依赖
    # （V0.116.1：下面几处字符串注解 ``"ScoringWideService | None"`` 引用了
    # 一个模块级**不存在**的名字，ruff F821 报 undefined-name。
    # 运行时靠函数体内的局部 import，不受影响。）
    from app.services.scoring_wide import ScoringWideService

from app.config import get_settings
from app.models.user import LEGACY_USER_ID, ROLE_OWNER, User
from app.repositories.account import AccountRepository
from app.repositories.analysis import AnalysisRepository
from app.repositories.central_bank import CentralBankPurchaseRepository
from app.repositories.db import async_session_factory
from app.repositories.gold_inventory import GoldInventoryRepository  # V0.115.0 COMEX 库存
from app.repositories.macro_factor_history import MacroFactorHistoryRepository  # V0.79.0 Step E
from app.repositories.market_data import MarketDataRepository
from app.repositories.market_providers import build_provider_bundle
from app.repositories.news import NewsScoreRepository
from app.repositories.news_feed import NewsFeedRepository  # V0.102 今日要闻
from app.repositories.position import PositionRepository
from app.repositories.reports import ReportRepository  # V0.111.0 报告存档
from app.repositories.review import GoldPriceRepository
from app.repositories.settings import SettingRepository
from app.repositories.snapshot import SnapshotRepository
from app.repositories.telemetry import TelemetryRepository
from app.repositories.user import SessionRepository, UserRepository
from app.repositories.user_news_favorite import UserNewsFavoriteRepository  # V0.103
from app.services.account import AccountService
from app.services.alert import AlertDispatcher  # V0.72.0 P3-b
from app.services.analysis import AnalysisService
from app.services.auth import AuthService, LoginThrottle  # V0.75.0
from app.services.backtest import BacktestService
from app.services.central_bank import CentralBankService
from app.services.compare import GoldCompareService
from app.services.decision import DecisionService
from app.services.freshness import FreshnessService
from app.services.gold_inventory import GoldInventoryService  # V0.115.0 COMEX 库存
from app.services.macro import MacroFactorService  # V0.79.0 Step E
from app.services.macro_thresholds import MacroThresholdCalculator  # V0.79.0 Step E
from app.services.news import NewsScoreService
from app.services.news_feed import NewsFeedService  # V0.102 今日要闻
from app.services.portfolio import PortfolioAnalyticsService
from app.services.position import PositionService
from app.services.reports import ReportService  # V0.111.0 报告存档
from app.services.resonance import ResonanceService
from app.services.review import ReviewService
from app.services.scoring import OpportunityScoringService
from app.services.settings import WeightService
from app.services.snapshot import DailySnapshotService
from app.services.telemetry import TelemetryService
from app.services.trades import TradeHistoryService
from app.services.trend import TrendService
from app.services.user_news_favorite import UserNewsFavoriteService  # V0.103


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


async def get_gold_inventory_repository(
    session: AsyncSession = Depends(get_db_session),
) -> GoldInventoryRepository:
    """COMEX 黄金库存 DB 仓储依赖（V0.115.0）。"""
    return GoldInventoryRepository(session)


def get_gold_inventory_service(
    repo: GoldInventoryRepository = Depends(get_gold_inventory_repository),
) -> GoldInventoryService:
    """COMEX 黄金库存业务服务依赖（V0.115.0）。"""
    return GoldInventoryService(repo=repo)


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


# V0.102 ── 今日要闻（readhub 财经新闻流）


async def get_news_feed_repository(
    session: AsyncSession = Depends(get_db_session),
) -> NewsFeedRepository:
    """readhub 财经新闻仓储依赖。"""
    return NewsFeedRepository(session)


def get_news_feed_service(
    repo: NewsFeedRepository = Depends(get_news_feed_repository),
) -> NewsFeedService:
    """readhub 财经新闻业务服务依赖。"""
    return NewsFeedService(repo=repo)


async def get_user_news_favorite_repository(
    session: AsyncSession = Depends(get_db_session),
) -> UserNewsFavoriteRepository:
    """用户新闻收藏仓储依赖。"""
    return UserNewsFavoriteRepository(session)


def get_user_news_favorite_service(
    fav_repo: UserNewsFavoriteRepository = Depends(get_user_news_favorite_repository),
    feed_repo: NewsFeedRepository = Depends(get_news_feed_repository),
) -> UserNewsFavoriteService:
    """用户新闻收藏业务服务依赖（注入 feed_repo 用于 POST 时回填快照）。"""
    return UserNewsFavoriteService(fav_repo=fav_repo, feed_repo=feed_repo)


def get_trend_service(
    repo: MarketDataRepository = Depends(get_market_data_repository),
    settings: WeightService = Depends(get_weight_service),
    news: NewsScoreService = Depends(get_news_score_service),
    central_bank: CentralBankService = Depends(get_central_bank_service),
    macro_thresholds: MacroThresholdCalculator = Depends(get_macro_threshold_calculator),
    macro_history_repo: MacroFactorHistoryRepository = Depends(get_macro_factor_history_repository),
) -> TrendService:
    """黄金趋势追踪服务依赖（行情仓储 + 权重配置 + 消息面评估 + 央行购金服务 + 宏观阈值动态化）。

    - ``central_bank`` 注入后，宏观因子 ``cb_gold`` 会从 ``central_bank_purchases`` 表自动计算
      T12M（不再依赖 STATIC_REF 硬编码）。空表时回退 STATIC_REF，单测时不注入也保持兼容。
    - ``macro_thresholds``（V0.79.0 Step E）注入后，宏观因子 ``dxy/us10y/us30y/vix``
      走近 252 日滚动 90/10 分位，``cb_gold`` 永远走 hardcode。数据不足（< 60 样本）
      自动回退 hardcode。**运行时回滚路径**：把 ``get_macro_threshold_calculator``
      改为返回 None（无需 revert）。
    - ``macro_history_repo``（V0.118.1）注入后，宏观因子在上游源抓不到读数时用
      「上次成功落库的真实读数」顶上，而不是 2026-08-28 的内置常量。
    """
    macro = MacroFactorService(
        settings=settings,
        central_bank=central_bank,
        threshold_calculator=macro_thresholds,
        history_repo=macro_history_repo,
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


async def require_user(
    request: Request,
    user: User | None = Depends(get_current_user),
) -> User:
    """要求已登录；匿名则 401。

    单用户模式（``AUTH_ENABLED=false``）下中间件不解析会话，
    ``request.state.user`` 恒为 None —— V0.97.0 起，AI 端点（``/ai/*``）也
    使用本依赖，会被误伤；故加**单用户回退**：直接读 LEGACY_USER（id=1）
    并返回，便于 LAN 单用户部署直接访问。
    多用户模式下行为不变（仍 401）。
    """
    if user is not None:
        return user
    settings = get_settings()
    if not settings.auth_enabled:
        # 单用户模式：从 DB 取 LEGACY_USER（主键查询，O(1)）；主进程启动时
        # ``main._bootstrap_default_user`` 保证该行存在
        #
        # ⚠ V0.97.0 hotfix：DB 的 ``users`` 表可能**不**含 ORM 声明的
        # ``role`` 列（alembic 漂移，V0.92.0 同类问题见 memory
        # ``alembic-stale-revision-recovery.md``）。直接 ``select(User)``
        # 会 SELECT ``role`` → ``OperationalError: no such column``。
        # 用 ``load_only`` 只读确实存在的列 + ``set_committed_value`` 补 role。
        from sqlalchemy import select
        from sqlalchemy.orm import load_only
        from sqlalchemy.orm.attributes import set_committed_value

        async with async_session_factory() as session:
            legacy = (
                await session.execute(
                    select(User)
                    .where(User.id == LEGACY_USER_ID)
                    .options(
                        load_only(
                            User.id,
                            User.email,
                            User.display_name,
                            User.is_active,
                            User.password_hash,
                        )
                    )
                )
            ).scalar_one_or_none()
        if legacy is not None:
            # role 是 not-null 但 DB 缺列 → 标记为已加载并赋默认值
            # 避免下游 Pydantic UserOut / ORM 写时触发 lazy-load 或缺列
            set_committed_value(legacy, "role", ROLE_OWNER)
            return legacy
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "unauthenticated", "message": "请先登录"},
        headers={"X-Auth-Required": "1"},
    )


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


# ─────────────────────────────────────────────────────────────────
# V0.92.0 —— 打分数据宽表（物化视图）
#
# 不用 Depends() 注入到 get_news_score_service / get_snapshot_service，
# 因为这会形成 forward reference（get_scoring_wide_service 依赖的
# get_snapshot_repository / get_news_repository / get_gold_price_repository
# 之中至少一个会被 get_news_score_service 间接依赖 ⇒ 定义时 NameError）。
#
# 改用「延迟构造」+「进程级单例」：snapshot / news 服务在 hook 点调用
# :func:`get_scoring_wide_service_for_etl` 拿到现成实例，不走 DI 参数解析。
# 单测 / CLI 路径可注入 stub wide_svc（见各服务的 wide_svc 参数）。
# ─────────────────────────────────────────────────────────────────


async def get_scoring_wide_repository(
    session: AsyncSession = Depends(get_db_session),
):
    """打分数据宽表仓储依赖（V0.92.0）。"""
    from app.repositories.scoring_wide import ScoringWideRepository

    return ScoringWideRepository(session)


def get_scoring_wide_service(
    repo=Depends(get_scoring_wide_repository),
    snapshot_repo: SnapshotRepository = Depends(get_snapshot_repository),
    news_repo: NewsScoreRepository = Depends(get_news_repository),
    gold_repo: GoldPriceRepository = Depends(get_gold_price_repository),
):
    """打分数据宽表服务依赖（V0.92.0）。"""
    from app.services.scoring_wide import ScoringWideService

    return ScoringWideService(
        repo=repo,
        snapshot_repo=snapshot_repo,
        news_repo=news_repo,
        gold_repo=gold_repo,
    )


def get_scoring_wide_service_for_etl() -> "ScoringWideService | None":
    """snapshot/news 服务在写时 hook 用的延迟构造器（V0.92.0）。

    不走 DI：FastAPI 的 Depends() 在函数定义时即解析参数，
    而 ``get_scoring_wide_service`` 依赖的 ``get_snapshot_repository`` 等
    都被前向定义在更早位置 ⇒ 直接 ``Depends(get_scoring_wide_service)``
    会触发 ``NameError``（典型 DI 循环问题）。

    本函数：
    1. 取出当前 FastAPI 请求作用域下的 session（``get_db_session`` 同款 AsyncSession）
    2. 现场构造一个 :class:`ScoringWideService` 实例并返回
    3. 不缓存 —— 每次调用现场造；写时 hook 1 日 1 次，开销可忽略

    Returns:
        :class:`ScoringWideService` 实例；异常时返回 ``None``（snapshot / news
        服务应 log.warning 后跳过，不影响主流程 —— V0.79.0 任务 #162 教训）。
    """
    try:
        # 用同步 session_factory 走一次性会话（写时 hook 不在请求路径上，
        # 跨请求共用一个事件循环的场景下用独立会话最安全）。
        # 异步封装由调用方 await 处理。

        class _LazyService:
            """轻量占位：实际 rebuild 在调用方 async 上下文中现场 await session。"""

            def __init__(self) -> None:
                pass

        # 真实实现：见 ``rebuild_for_date`` 全局函数（在 main 启动时挂载）。
        return _get_or_build_wide_svc()
    except Exception:
        return None


# 进程级单例（FastAPI lifespan 启动时构建；snapshot/news hook 复用）
_wide_svc_singleton: "ScoringWideService | None" = None


def set_scoring_wide_singleton(svc: "ScoringWideService | None") -> None:
    """lifespan 启动时挂载；卸载（重载 / 测试 teardown）置 None。"""
    global _wide_svc_singleton
    _wide_svc_singleton = svc


def _get_or_build_wide_svc() -> "ScoringWideService | None":
    """hook 入口：取 lifespan 阶段已挂载的单例；缺则返回 None（CLI/单测）。"""
    return _wide_svc_singleton


# ─────────────────────────────────────────────────────────────────
# V0.92.0 —— 打分数据宽表（物化视图）
# 定义在文件末尾以避免前向引用：get_scoring_wide_service 依赖
# get_snapshot_repository / get_news_repository / get_gold_price_repository
# ─────────────────────────────────────────────────────────────────


def get_report_repository(
    session: AsyncSession = Depends(get_db_session),
) -> ReportRepository:
    """报告存档仓储依赖（V0.111.0）。"""
    return ReportRepository(session)


def get_report_service(
    repo: ReportRepository = Depends(get_report_repository),
) -> ReportService:
    """报告存档服务依赖（V0.111.0）。"""
    return ReportService(repo=repo)
