"""FastAPI 应用入口：装配路由、中间件与生命周期。"""

import asyncio
import logging
import sqlite3
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.config import get_settings
from app.models.base import Base
from app.repositories.db import engine
from app.utils.db_migrate import ensure_sqlite_columns, ensure_sqlite_optimizations

settings = get_settings()
logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]  # src/app/../.. = 项目根
STATIC_DIR = PROJECT_ROOT / "static"


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
    except Exception as exc:  # noqa: BLE001 —— 清理失败不影响后续迁移
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
    except Exception as exc:  # noqa: BLE001
        logger.warning("alembic upgrade failed (%s), fallback create_all", exc)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


async def _warm_cache() -> None:
    """非阻塞预热行情缓存：启动后后台拉取三市场数据，使首屏直接命中缓存。

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
    except Exception as exc:  # noqa: BLE001
        logger.warning("cache warmup failed (%s)", exc)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期钩子。

    - 启动：WAL 合并 → Alembic 正式迁移（建表/升级）→ 运行时补列/性能优化 → 后台预热缓存
    - 关闭：释放数据库连接池
    """
    await _checkpoint_wal()
    await _migrate_db()
    # 运行时保障：补齐历史库缺失的新增列 + WAL/索引优化
    await ensure_sqlite_columns(engine)
    await ensure_sqlite_optimizations(engine)
    logger.info("Database ready (env=%s)", settings.app_env)
    # 非阻塞预热：首屏直接命中缓存，避免长时间空白等待
    asyncio.create_task(_warm_cache())
    yield
    await engine.dispose()


app = FastAPI(
    title="黄金价格投资辅助工具",
    version="0.54.0",
    description="黄金价格投资辅助工具 API —— 三市场对照（纽约金/上海金/黄金ETF）、趋势评估指数、个人持仓跟踪与ETF购买决策",
    lifespan=lifespan,
    debug=settings.debug,
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


# 静态资源（趋势追踪页面等）
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
