"""FastAPI 应用入口：装配路由、中间件与生命周期。"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.config import get_settings
from app.models.base import Base
from app.repositories.db import engine

settings = get_settings()
logger = logging.getLogger(__name__)


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
    title=settings.app_name,
    version="0.10.0",
    description="黄金ETF交易机会分析 API —— 宏观因子加权评分，输出投资机会窗口",
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
