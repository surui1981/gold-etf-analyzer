"""FastAPI 应用入口：装配路由、中间件与生命周期。"""

import asyncio
import sqlite3
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.v1.router import api_router
from app.config import get_settings
from app.middleware.auth import AuthMiddleware, CsrfMiddleware  # V0.75.0
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.trace import TraceIdMiddleware
from app.models.base import Base
from app.repositories.db import engine
from app.utils.db_migrate import ensure_sqlite_columns, ensure_sqlite_optimizations
from app.utils.logger import get_logger

settings = get_settings()
logger = get_logger(__name__)  # V0.67.0：使用项目 logger（自动附加 trace_id）
PROJECT_ROOT = Path(__file__).resolve().parents[2]  # src/app/../.. = 项目根
STATIC_DIR = PROJECT_ROOT / "static"

# 后台任务强引用集合（V0.79.0 Step G 提取到独立模块，避免循环导入）。
# asyncio 内部对 task 只保留**弱引用**，若调用方不保存 create_task 的返回值，
# 任务可能在执行途中被垃圾回收（ruff RUF006）。任务结束后由 done_callback
# 自动移出，集合不会无限增长。
from app.services.background import _BACKGROUND_TASKS  # noqa: E402,F401
from app.services.background import spawn as _spawn_background  # noqa: E402


def _run_alembic_upgrade() -> None:
    """以**子进程**方式执行 Alembic 迁移至最新（head）。

    关键：

    - 与当前进程完全隔离，使用独立的 SQLite 连接与锁，避免「在已运行的事件循环内
      调用 Alembic 异步 env」导致的死锁（迁移线程持住写锁并永久等待）。
    - ``timeout`` 由 OS 级 kill 保障：超时即终止子进程，绝不会残留持锁线程，
      从而让下面的回退 ``create_all`` 能正常拿到写锁。
    """
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(PROJECT_ROOT),
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )


async def _checkpoint_wal() -> None:
    """启动期对主库做一次 WAL checkpoint(TRUNCATE)，清理上次异常退出遗留的 -wal/-shm。

    异常强杀（如 -9）会让 SQLite 留下未合并的 WAL，新的连接可能卡在恢复/锁等待上，
    故在迁移前先合并落盘并清空 WAL 文件。
    """
    try:
        url = settings.database_url
        if not url.startswith("sqlite"):
            return
        db_path = url.split("///", 1)[-1]

        def _cp() -> None:
            conn = sqlite3.connect(db_path, timeout=10)
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                conn.close()

        await asyncio.to_thread(_cp)
        logger.info("wal checkpoint done: %s", db_path)
    except Exception as exc:
        logger.warning("wal checkpoint skipped (%s)", exc)


async def _migrate_db() -> None:
    """正式 schema 迁移（Alembic）；失败时回退 create_all 兜底，保证可启动。

    注意：迁移前**不**调用 create_all。应用异步引擎与 Alembic 内部引擎会同时持有
    SQLite 连接，两个写者争同一文件写锁会导致迁移永久等待（启动 hang）。
    Alembic ``upgrade head`` 已负责建全表，仅在其失败时回退 create_all。
    """
    try:
        await asyncio.to_thread(_run_alembic_upgrade)
        logger.info("alembic upgrade head: ok")
    except Exception as exc:
        logger.warning("alembic upgrade failed (%s), fallback create_all", exc)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


async def _ensure_default_account() -> None:
    """保障默认账本存在（V0.62.0 单用户多账本，幂等）。

    老库经运行时补列路径升级时 ``positions.account_id`` 默认为 1，
    但 ``accounts`` 表可能为空；此处显式建出 id=1 的「默认账户」，
    使历史持仓在账本视图中可见，避免出现「无归属」的孤儿数据。
    """
    try:
        from app.models.user import LEGACY_USER_ID
        from app.repositories.account import AccountRepository
        from app.repositories.db import async_session_factory

        async with async_session_factory() as session:
            # 启动引导属**系统级任务**（无请求上下文）→ 必须显式传 LEGACY_USER_ID，
            # 否则多用户模式下 current_user_id() 会抛 MissingUserContextError。
            account = await AccountRepository(session).ensure_default(user_id=LEGACY_USER_ID)
        logger.info("default account ready: id=%s name=%s", account.id, account.name)
    except Exception as exc:
        logger.warning("default account ensure failed (%s)", exc)


async def _backfill_news_categories() -> None:
    """V0.105：启动时一次性把 news_feed_items 历史 NULL 行打上类目标签。

    - 异步、不阻塞 readiness（warm_cache 已经是 spawn_background 模式）
    - 失败仅日志告警：分类失败不影响启动（NULL 仍可工作，仅 UI 筛选项少）
    - 幂等：只处理 ``category IS NULL`` 行
    - 性能：~64378 行 / 500 batch ≈ 130 批 × ~50ms ≈ 6-10s

    启动后 4h scheduler 抓新条目时（V0.106 6h→4h），各源 fetcher 的 normalize
    会即时调 ``classify()`` 填入 category，**新条目不会留 NULL**。
    """
    try:
        from app.repositories.db import async_session_factory
        from app.repositories.news_feed import NewsFeedRepository

        async with async_session_factory() as session:
            n = await NewsFeedRepository(session).backfill_categories(batch_size=500)
        logger.info("news category backfill done: %d rows", n)
    except Exception as exc:
        logger.warning("news category backfill failed (%s)", exc)


async def _backfill_news_feed_daily() -> None:
    """V0.107：启动时一次性回填 news_feed_daily 最近 30 天。

    - 异步、不阻塞 readiness（仿 _backfill_news_categories 模式）
    - 失败仅日志告警：聚合失败不影响启动（daily 行可有可无，UI 走实时 GROUP BY 兜底）
    - 幂等：``upsert_daily`` 用 INSERT ON CONFLICT(date) DO UPDATE
    - 性能：30 天 × 1 行 × 1 SQL 聚合 ≈ 30ms（实测 3-10ms/日）

    启动后 4h scheduler refresh 末尾会自动 rebuild_daily(BJT today + BJT yesterday)，
    日常更新由 scheduler 维护；本函数只负责**历史 30 天**的一次性回填。
    """
    try:
        from datetime import datetime, timedelta, timezone

        from app.repositories.db import async_session_factory
        from app.repositories.news_feed import NewsFeedRepository

        bjt_tz = timezone(timedelta(hours=8))
        bjt_today = datetime.now(bjt_tz).date()
        start_date = bjt_today - timedelta(days=30)

        async with async_session_factory() as session:
            n = await NewsFeedRepository(session).backfill_daily(
                start_date=start_date, end_date=bjt_today
            )
        logger.info(
            "news feed daily backfill done: %d days (%s..%s BJT)",
            n,
            start_date,
            bjt_today,
        )
    except Exception as exc:
        logger.warning("news feed daily backfill failed (%s)", exc)


async def _warm_cache() -> None:
    """非阻塞预热行情缓存 + 首日 served cache：启动后后台拉取三市场数据 + 评估核心。

    - 行情缓存：使首屏直接命中缓存，避免长时间空白等待
    - served cache：预生成"当日已评估"结果，页面秒级返回
    失败仅需日志记录，不影响服务可用（请求时仍会惰性加载 + 降级 Mock）。
    """
    try:
        from app.repositories.market_data import MarketDataRepository

        repo = MarketDataRepository()
        await asyncio.gather(
            repo.get_us_gold_history(days=60),
            repo.get_gold_history(days=60),
            repo.get_gold_gram_history(days=60),
            return_exceptions=True,
        )
        logger.info("cache warmup done (ny/etf/gram)")
    except Exception as exc:
        logger.warning("cache warmup failed (%s)", exc)

    # 预生成今日 served cache（首次请求直接命中，避免首屏空白）
    try:
        from app.repositories.central_bank import CentralBankPurchaseRepository
        from app.repositories.db import async_session_factory

        # 注入央行购金服务 → cb_gold 因子从表自动计算（不再硬编码 STATIC_REF）
        # V0.79.0 Step E：注入 MacroThresholdCalculator → 宏观因子走 252 日滚动百分位
        from app.repositories.macro_factor_history import MacroFactorHistoryRepository
        from app.services.cache import set_served
        from app.services.central_bank import CentralBankService
        from app.services.macro import MacroFactorService
        from app.services.macro_thresholds import MacroThresholdCalculator
        from app.services.trend import GUIDE_TARGET, TrendService

        async with async_session_factory() as session:
            cb_repo = CentralBankPurchaseRepository(session)
            cb_svc = CentralBankService(repo=cb_repo)
            threshold_calc = MacroThresholdCalculator(repo=MacroFactorHistoryRepository(session))
            macro = MacroFactorService(central_bank=cb_svc, threshold_calculator=threshold_calc)
            trend = TrendService(
                repo=MarketDataRepository(),
                macro=macro,
                settings=None,
                news=None,  # 预热时未打分 → 中性 50
            )
            result = await trend.analyze(days=60, target=GUIDE_TARGET)
            # V0.79.0 Step E：warm threshold cache 让首屏不空跑 percentile
            await threshold_calc.warm_cache("default")
        set_served(GUIDE_TARGET, result)
        logger.info(
            "served cache warmup done (index=%.1f, macro_dynamic=%s)",
            result.index.score,
            getattr(result.macro, "macro_dynamic", "n/a"),
        )
    except Exception as exc:
        logger.warning("served cache warmup failed (%s)", exc)


async def _start_daily_scheduler() -> None:
    """启动每日 07:00 BJT 调度协程（捕获快照 + 预热 served cache）。

    V0.60.0：内部串联日内 4 个时点（09:30/11:30/14:00/15:30 BJT）的 served cache
    预热，由 ``daily_capture_loop`` 内部 ``min(next_daily, next_intraday)`` 决定触发时机。

    异常仅日志告警；调度循环自身 try/except 隔离失败。
    """
    try:
        from app.repositories.central_bank import CentralBankPurchaseRepository
        from app.repositories.db import async_session_factory
        from app.repositories.market_data import MarketDataRepository
        from app.repositories.snapshot import SnapshotRepository
        from app.services.central_bank import CentralBankService
        from app.services.macro import MacroFactorService
        from app.services.scheduler import (
            daily_capture_loop,
            is_intraday_refresh_enabled,
        )
        from app.services.snapshot import DailySnapshotService
        from app.services.trend import TrendService

        async with async_session_factory() as session:
            from app.repositories.macro_factor_history import MacroFactorHistoryRepository
            from app.services.macro_thresholds import MacroThresholdCalculator

            cb_svc = CentralBankService(repo=CentralBankPurchaseRepository(session))
            # V0.79.0 Step E：注入 MacroThresholdCalculator → 宏观因子走 252 日滚动百分位
            threshold_calc = MacroThresholdCalculator(repo=MacroFactorHistoryRepository(session))
            macro = MacroFactorService(central_bank=cb_svc, threshold_calculator=threshold_calc)
            trend_svc = TrendService(
                repo=MarketDataRepository(),
                macro=macro,
                settings=None,
                news=None,
            )

        async def _capture_with_session():
            """按需创建 session 调一次 capture_today（避免 lifespan 长持 session）。"""
            async with async_session_factory() as session:
                repo = SnapshotRepository(session)
                snap_svc = DailySnapshotService(repo=repo, trend=trend_svc)
                return await snap_svc.capture_today()

        class _SnapshotAdapter:
            """适配器：把带 session 的 capture 包装成 scheduler 期望的接口。"""

            async def capture_today(self):
                return await _capture_with_session()

        _spawn_background(daily_capture_loop(_SnapshotAdapter(), trend_svc))
        intra_state = "enabled" if is_intraday_refresh_enabled() else "disabled"
        logger.info(
            "daily scheduler started (07:00 BJT + intraday 09:30/11:30/14:00/15:30 BJT, %s)",
            intra_state,
        )
    except Exception as exc:
        logger.error("daily scheduler failed to start: %s", exc)

    # 央行购金月度刷新协程：每月 1/15/末日 07:30 BJT（与每日 07:00 错开 30min）
    try:
        from app.services.scheduler import monthly_central_bank_loop

        _spawn_background(monthly_central_bank_loop())
        logger.info("central bank monthly scheduler started (1/15/last-day 07:30 BJT)")
    except Exception as exc:
        logger.error("central bank scheduler failed to start: %s", exc)

    # V0.102 ── 今日要闻刷新协程；V0.106 由 6h 加密到 4h
    try:
        from app.services.scheduler import (
            NEWS_FEED_INTERVAL_HOURS,
            news_feed_loop,
        )

        _spawn_background(news_feed_loop())
        # ⚠ 触发时刻从 NEWS_FEED_INTERVAL_HOURS **推导**而不是写死。
        # 原来这里写的是「every 6h: 00/06/12/18 UTC」，而实际调度是 4h ——
        # 一条与真实行为相反的日志：排障时照着它去等 06:00，永远等不到。
        # 与 scheduler.news_feed_loop 的 hours_label 同一算法。
        _hours = "/".join(f"{h:02d}" for h in range(0, 24, NEWS_FEED_INTERVAL_HOURS))
        logger.info(
            "news feed scheduler started (every %dh: %s UTC, 4 sources with failover)",
            NEWS_FEED_INTERVAL_HOURS,
            _hours,
        )
    except Exception as exc:
        logger.error("news feed scheduler failed to start: %s", exc)

    # V0.115.0 ── COMEX 黄金库存刷新协程；每日 08:10 BJT
    # 排在 07:00 快照 / 07:30 央行购金 / 08:00 新闻之后，错开源与时间点。
    try:
        from app.services.scheduler import (
            GOLD_INV_TRIGGER_HOUR_BJT,
            GOLD_INV_TRIGGER_MINUTE_BJT,
            gold_inventory_loop,
        )

        _spawn_background(gold_inventory_loop())
        logger.info(
            "gold inventory scheduler started (%02d:%02d BJT daily)",
            GOLD_INV_TRIGGER_HOUR_BJT,
            GOLD_INV_TRIGGER_MINUTE_BJT,
        )
    except Exception as exc:
        logger.error("gold inventory scheduler failed to start: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期钩子。

    - 启动：WAL 合并 → Alembic 正式迁移（建表/升级）→ 运行时补列/性能优化
      → 后台预热行情缓存 + served cache → 启动每日 07:00 BJT 调度协程
    - 关闭：释放数据库连接池（调度协程随事件循环终止）
    """
    await _checkpoint_wal()
    await _migrate_db()
    # 运行时保障：补齐历史库缺失的新增列 + WAL/索引优化
    await ensure_sqlite_columns(engine)
    await ensure_sqlite_optimizations(engine)
    # 单用户多账本：保障默认账本存在（承接历史数据，幂等）
    await _ensure_default_account()
    # V0.105：news 类目历史数据回填（spawn_background 异步执行，不阻塞启动）
    _spawn_background(_backfill_news_categories())
    # V0.107：news_feed_daily 最近 30 天历史聚合回填（spawn_background）
    _spawn_background(_backfill_news_feed_daily())
    logger.info("Database ready (env=%s)", settings.app_env)
    # 非阻塞预热：首屏直接命中缓存，避免长时间空白等待
    _spawn_background(_warm_cache())
    # 每日 07:00 BJT 调度：自动捕获快照 + 预热 served cache
    await _start_daily_scheduler()
    # V0.92.0：注册打分数据宽表服务单例，供 snapshot / news 服务写时 hook 调用
    # （避免 DI 前向引用：get_scoring_wide_service 间接依赖 snapshot_repo /
    #  news_repo / gold_repo，而 snapshot_service / news_service 又依赖 wide_svc，
    #  定义时即触发 NameError ⇒ 改用 lifespan 阶段挂载的进程级单例）
    from app.dependencies import set_scoring_wide_singleton
    from app.repositories.db import async_session_factory
    from app.repositories.news import NewsScoreRepository
    from app.repositories.review import GoldPriceRepository
    from app.repositories.scoring_wide import ScoringWideRepository
    from app.repositories.snapshot import SnapshotRepository
    from app.services.scoring_wide import ScoringWideService

    async with async_session_factory() as boot_session:
        wide_svc = ScoringWideService(
            repo=ScoringWideRepository(boot_session),
            snapshot_repo=SnapshotRepository(boot_session),
            news_repo=NewsScoreRepository(boot_session),
            gold_repo=GoldPriceRepository(boot_session),
        )
        set_scoring_wide_singleton(wide_svc)

    # V0.97.0：初始化 AI 智能分析（Claude LLM + ToolDispatcher）。
    # API key 未配时 llm_client=None，前端 /api/v1/ai/health 报 enabled=false，
    # /ask 页 feature flag 关，避免启动崩溃。
    from app.services.llm.claude import ClaudeClient
    from app.services.llm.tools import ToolDispatcher

    if settings.llm_api_key:
        llm_client = ClaudeClient(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout_seconds,
            max_tokens=settings.llm_max_tokens,
        )
        # ToolDispatcher 复用 5 个 services（DI 之外的 service 实例）。
        # dependencies 里的 get_trend_service / get_position_service /
        # get_freshness_service 是普通函数，调用会在 lifespan 内起异步 session，
        # 所以这里用 lifespan 自己这个 session 手工构造 —— ToolDispatcher
        # 接受 duck-typed 的 5 个 service，不需要走 DI。
        from app.repositories.db import async_session_factory as _asf
        from app.repositories.market_data import MarketDataRepository
        from app.services.trend import TrendService

        # 用一个独立 session 拼 tool 依赖（lifespan 阶段 session 直接 await 即可）
        async with _asf() as tool_sess:
            trend_svc = TrendService(
                MarketDataRepository(tool_sess), MarketDataRepository(tool_sess)
            )
            # 其余 4 个 service 注入宽表 + market_data
            from app.repositories.news import NewsScoreRepository as _NSR
            from app.repositories.position import PositionRepository as _PR
            from app.repositories.review import GoldPriceRepository as _GPR
            from app.repositories.scoring_wide import ScoringWideRepository as _SWR
            from app.repositories.snapshot import SnapshotRepository as _SSR
            from app.services.freshness import FreshnessService
            from app.services.position import PositionService
            from app.services.scoring_wide import ScoringWideService as _SWS

            market_repo = MarketDataRepository(tool_sess)
            scoring_svc = _SWS(
                repo=_SWR(tool_sess),
                snapshot_repo=_SSR(tool_sess),
                news_repo=_NSR(tool_sess),
                gold_repo=_GPR(tool_sess),
            )
            position_svc = PositionService(_PR(tool_sess), market_repo)
            freshness_svc = FreshnessService(market_repo)
            tool_dispatcher = ToolDispatcher(
                trend_service=trend_svc,
                scoring_service=scoring_svc,
                position_service=position_svc,
                freshness_service=freshness_svc,
                market_data_repository=market_repo,
            )
        app.state.llm_client = llm_client
        app.state.tool_dispatcher = tool_dispatcher
        logger.info(
            "AI 智能分析已启用（model=%s，base_url=%s）",
            settings.llm_model,
            settings.llm_base_url,
        )
    else:
        app.state.llm_client = None
        app.state.tool_dispatcher = None
        logger.info("AI 智能分析未启用（LLM_API_KEY 未配置）")
    app.state.settings = settings
    yield
    # V0.92.0：卸载宽表单例
    set_scoring_wide_singleton(None)
    await engine.dispose()


app = FastAPI(
    title="黄金价格投资辅助工具",
    version=__version__,
    description="黄金价格投资辅助工具 API —— 三市场对照（纽约金/上海金/黄金ETF）、趋势评估指数、个人持仓跟踪与ETF购买决策",
    lifespan=lifespan,
    debug=settings.debug,
    # V0.75.0：启用登录且为生产环境时关闭交互式文档 —— /docs 与 /openapi.json
    # 会完整暴露 API 面（对公网暴露的实例等于给攻击者一份接口清单）。
    # dev 下保持开启，方便本地调试与 Swagger 联调。
    docs_url=None if (settings.auth_enabled and settings.app_env == "prod") else "/docs",
    redoc_url=None if (settings.auth_enabled and settings.app_env == "prod") else "/redoc",
    openapi_url=None if (settings.auth_enabled and settings.app_env == "prod") else "/openapi.json",
)

# V0.75.0：认证 + CSRF 中间件必须在 TraceIdMiddleware **之前**注册。
# add_middleware 是 LIFO（后加的更靠外），故先注册者成为**内层**，
# 最终执行顺序为 CORS → RateLimit → TraceId → Auth → Csrf → 路由：
#   ① Auth 外层 → **未登录先于 CSRF 判定**，匿名写方法稳定得到 401（而非 csrf_failed 403），
#      前端据此把用户送去登录页；已登录但缺/错 token 才是 403；
#   ② 401/403 响应仍带 CORS 头（CORS 在最外层）→ 前端能读到错误体（否则只显示 "Failed to fetch"）；
#   ③ 审计日志带 trace_id（TraceId 在两者之外）；
#   ④ 登录爆破先被 per-IP 限速拦一道，成本更高。
# AUTH_ENABLED=false 时两者都是纯透传（零 DB 访问），行为与 V0.74.3 一致。
app.add_middleware(CsrfMiddleware)
app.add_middleware(AuthMiddleware)

# V0.67.0：trace_id 注入中间件必须在 CORS 之前注册（LIFO：最后加入的最近路径）。
# 即使 CORS 预检失败 / OPTIONS 拦截，响应头里也带 X-Request-ID，便于客户端定位。
app.add_middleware(TraceIdMiddleware)

# V0.72.0 P3-b：per-IP 限速（默认 120 req/min；env RATE_LIMIT_PER_MIN=0 禁用）。
# 位置在 CORS 之后：LIFO 顺序下，限速包在内层先执行；OPTIONS 预检在中间件内部已豁免。
# 测试环境（app_env='test'）自动禁用：测试套件大量连发请求，限速会误伤 201/200 测试。
if settings.rate_limit_per_min > 0 and settings.app_env != "test":
    app.add_middleware(
        RateLimitMiddleware,
        per_min=settings.rate_limit_per_min,
        skip_static=settings.rate_limit_skip_static,
    )

# V0.97.0：per-user 限速（仅作用于 /api/v1/ai/* 路径），与 per-IP 叠加。
# 测试环境自动禁用（与 per-IP 限速同策略）。
if settings.app_env != "test":
    from app.middleware.per_user_rate_limit import PerUserRateLimitMiddleware

    app.add_middleware(
        PerUserRateLimitMiddleware,
        per_min=settings.llm_per_user_per_minute,
        daily_quota=settings.llm_daily_token_quota,
    )

# CORS：开发期前端（如本地静态页）可直接跨域调用
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 统一挂载 v1 路由
app.include_router(api_router, prefix="/api/v1")


@app.get("/", include_in_schema=False)
async def index() -> RedirectResponse:
    """根路径直接进入趋势追踪页。"""
    return RedirectResponse("/static/trend.html")


@app.get("/home", include_in_schema=False)
async def home_page() -> RedirectResponse:
    """场景化首页（V0.98 C4）—— 5 大场景卡。"""
    return RedirectResponse("/static/home.html")


@app.get("/portfolio", include_in_schema=False)
async def portfolio_page() -> RedirectResponse:
    """个人交易跟踪与购买决策页。"""
    return RedirectResponse("/static/portfolio.html")


@app.get("/weights", include_in_schema=False)
async def weights_page() -> RedirectResponse:
    """评估权重配置页。"""
    return RedirectResponse("/static/weights.html")


@app.get("/news", include_in_schema=False)
async def news_page() -> RedirectResponse:
    """消息面评估页（客户打分）。"""
    return RedirectResponse("/static/news.html")


@app.get("/review", include_in_schema=False)
async def review_page() -> RedirectResponse:
    """研判复盘页（按日期归档研判 + 次日金价对比 + 准确率统计）。"""
    return RedirectResponse("/static/review.html")


@app.get("/central-bank", include_in_schema=False)
async def central_bank_page() -> RedirectResponse:
    """世界央行黄金购买统计页（按国家 / 季度）。"""
    return RedirectResponse("/static/central_bank.html")


@app.get("/headlines", include_in_schema=False)
async def headlines_page() -> RedirectResponse:
    """今日要闻页（V0.102）—— 多源财经快讯，每 4h 刷新（V0.106 起）。"""
    return RedirectResponse("/static/headlines.html")


@app.get("/favorites", include_in_schema=False)
async def favorites_page() -> RedirectResponse:
    """我的收藏页（V0.103）—— 今日要闻「收藏 / 永久存储 / 档案管理」。"""
    return RedirectResponse("/static/favorites.html")


@app.get("/report-archive", include_in_schema=False)
async def report_archive_page() -> RedirectResponse:
    """报告存档页（V0.111.0）—— 上传 HTML 报告 + 元数据登记表检索。"""
    return RedirectResponse("/static/report-archive.html")


@app.get("/data-health", include_in_schema=False)
async def data_health_page() -> RedirectResponse:
    """数据健康摘要页（V0.85.0）—— 6 数据源实时状态完整披露。

    9 页 statusPanel summary 都用 ``<a href="/data-health">`` chip 跳本页
    （与项目 kebab-url 约定一致：``/portfolio``、``/central-bank`` 等都无
    ``.html`` 后缀）。客户端脚本见 ``static/health-summary.js``。
    """
    return RedirectResponse("/static/data-health.html")


@app.get("/data-health.html", include_in_schema=False)
async def data_health_page_dothtml() -> RedirectResponse:
    """``/data-health.html`` 别名（向后兼容 V0.85.0 chip 直链 + 外部书签）。

    V0.85.0 早期发布的 chip ``href="/data-health.html"`` 在 V0.86.x 升级到
    kebab-url 后仍保留此别名，避免升级过程中老浏览器或书签拿到 404。
    """
    return RedirectResponse("/static/data-health.html")


@app.get("/report", include_in_schema=False)
async def report_page() -> RedirectResponse:
    """复盘报告 PDF 导出页（V0.91.0）。

    顶栏 📄 按钮 / 各页跳转链接都走这个 RESTful 别名。Query 串承载
    ``from`` / ``to`` / ``days`` / ``account_id`` 等筛选状态（与
    ``nav-context.js`` 协同：URL 优先、localStorage 兜底）。

    设计取舍：与 9 个既有 RESTful 别名同模式（kebab-url，无 .html 后缀）。
    **未**登记 ``/report.html`` 别名 —— ``sw.js`` 的 ``SHELL_ASSETS`` 不进
    报告页（V0.91.0 D1 决策：PDF 导出是显式在线行为，离线落 ``offline.html``
    合理；降低 ``cache.addAll`` 原子失败概率，保护 9 页离线可用性）。
    """
    return RedirectResponse("/static/report.html")


@app.get("/scoring", include_in_schema=False)
async def scoring_page() -> RedirectResponse:
    """历史打分数据汇总页（V0.92.0）。

    顶栏 📊 按钮走此 RESTful 别名（kebab-url，无 .html 后缀；与 12 个
    既有别名同模式）。背后是 ``scoring_daily_wide`` 物化宽表（24 列 ×
    N 日），由 ``DailySnapshotService.capture_today`` 与
    ``NewsScoreService.save_today`` 写时 hook 同步 ETL。
    """
    return RedirectResponse("/static/scoring.html")


@app.get("/ask", include_in_schema=False)
async def ask_page() -> RedirectResponse:
    """AI 智能分析页（V0.97.0）。

    顶栏 🤖 按钮走此 RESTful 别名。背后是 Claude API + 5 个只读 tool。
    需要 LLM_API_KEY 环境变量配置；未配置时 /ask 页仍可访问但
    ``/api/v1/ai/health`` 报 ``enabled=false``，前端友好降级。
    """
    return RedirectResponse("/static/ask.html")


@app.get("/trades", include_in_schema=False)
async def trades_page() -> RedirectResponse:
    """交易历史查询页（P1 #6：多条件筛选 + 汇总 + CSV 导出）。"""
    return RedirectResponse("/static/trades.html")


@app.get("/login", include_in_schema=False)
async def login_page() -> RedirectResponse:
    """登录 / 注册页（V0.75.0）。

    未启用认证时也保留该路由：页面自身会读取 ``/auth/status`` 并提示
    「本站未启用登录」—— 比 404 更能解释现状（用户可能是按内网地址猜的路径）。
    """
    return RedirectResponse("/static/login.html")


@app.get("/reset-password", include_in_schema=False)
async def reset_password_page() -> RedirectResponse:
    """找回密码落地页（V0.75.3）。

    ⚠ **这个 RESTful 别名不是可选的** —— ``sw.js`` 的 ``SHELL_ASSETS`` 里
    登记的是 ``/static/reset-password.html``，而离线兜底走
    ``caches.match(request)``，缓存 key 必须与地址栏里的 URL 一致。
    若只有 ``/static/*.html`` 一条路（无别名），用户从邮件点进
    ``/reset-password`` 会得到 **404** ⇒ 离线场景下「找回密码」不可用。

    同理，``SHELL_ASSETS`` 里**不能**把它写成
    ``/static/reset-password.html`` 直链形式来「省掉」这个别名 ——
    那会让离线访问落到 ``offline.html``（LESSONS §1.9 的既有结论）。
    """
    return RedirectResponse("/static/reset-password.html")


# 静态资源（趋势追踪页面等）
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# V0.72.0 P3-b：Service Worker 必须在 / 根 scope（StaticFiles mount 默认是 /static/），
# 通过 /sw.js 路由 + Service-Worker-Allowed: / 头实现。nginx 也需配同 location。
@app.get("/sw.js", include_in_schema=False)
async def service_worker() -> FileResponse:
    """PWA Service Worker（root scope）。"""
    sw_path = STATIC_DIR / "sw.js"
    if not sw_path.exists():
        return FileResponse(content=b"", media_type="application/javascript")
    return FileResponse(
        sw_path,
        media_type="application/javascript",
        headers={
            "Service-Worker-Allowed": "/",
            "Cache-Control": "no-cache",
        },
    )


# V0.114.1：/favicon.ico 走根作用域路由，理由同 /sw.js —— 浏览器约定在**站点根**
# 找 favicon，而 StaticFiles mount 只覆盖 /static/。
#
# 21 个页面现已各自带 <link rel="icon" href="/static/icon-192.png">，正常导航不会再
# 打这个路径；这个路由兜的是仍然会打的情况：旧书签、收藏夹、PWA 安装前的首屏，
# 以及某些不解析 link 标签的客户端（curl / 抓取器 / 早期浏览器）。
#
# ⚠️ 返回的是 192px PNG，不是真 .ico —— 实测 21 个页面全部 404 才是真问题，
# 补一个多尺寸真 ico 纯属锦上添花，收益/维护成本不成比例。content_type 如实写
# image/png，媒体类型与字节一致，别撒谎（撒谎会让某些浏览器拒绝解析）。
@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    """站点根 favicon（复用 PWA 图标，避免 /favicon.ico 404）。"""
    icon = STATIC_DIR / "icon-192.png"
    if not icon.exists():
        return Response(status_code=404)
    return FileResponse(
        icon,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )
