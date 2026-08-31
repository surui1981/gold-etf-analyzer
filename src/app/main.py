"""FastAPI 应用入口：装配路由、中间件与生命周期。"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from alembic import command
from alembic.config import Config

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
    """以编程方式执行 Alembic 迁移至最新（head）。"""
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    # 数据库 URL 由 migrations/env.py 从应用配置读取（支持测试库切换）
    command.upgrade(cfg, "head")


async def _migrate_db() -> None:
    """正式 schema 迁移（Alembic）；失败时回退 create_all 兜底，保证可启动。"""
    try:
        await asyncio.to_thread(_run_alembic_upgrade)
        logger.info("alembic upgrade head: ok")
    except Exception as exc:  # noqa: BLE001
        logger.warning("alembic upgrade failed (%s), fallback create_all", exc)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期钩子。

    - 启动：ensure 表存在 → Alembic 正式迁移 → 运行时补列/性能优化
    - 关闭：释放数据库连接池
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _migrate_db()
    # 运行时保障：补齐历史库缺失的新增列 + WAL/索引优化
    await ensure_sqlite_columns(engine)
    await ensure_sqlite_optimizations(engine)
    logger.info("Database ready (env=%s)", settings.app_env)
    yield
    await engine.dispose()


app = FastAPI(
    title="黄金价格投资辅助工具",
    version="0.11.0",
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
