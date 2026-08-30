"""FastAPI 应用入口：装配路由、中间件与生命周期。"""

import logging
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

settings = get_settings()
logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parents[2] / "static"  # src/app/../.. = 项目根/static


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期钩子。

    - 启动：确保数据表存在（骨架期用 create_all，迁移工具后续可切换 Alembic）
    - 关闭：释放数据库连接池
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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


# 静态资源（趋势追踪页面等）
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
