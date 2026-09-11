"""pytest 全局配置：隔离测试数据库 + 内存级异步客户端。"""

import os
from pathlib import Path

# 必须在导入 app 之前设置环境变量，
# 保证 config / repositories 使用独立的测试库，不污染正式 data/。
TEST_DB = Path(__file__).resolve().parent / "test_gold_etf.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB}"
os.environ["APP_ENV"] = "test"
os.environ["DEBUG"] = "false"

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.repositories.db import async_session_factory, engine  # noqa: E402


@pytest.fixture(autouse=True)
async def _reset_db() -> None:
    """每个用例前重建数据表，保证用例之间完全隔离。"""
    from app.repositories import market_data
    from app.services import cache as served_cache
    from app.services.settings import clear_weights_cache

    clear_weights_cache()  # 配置内存缓存随库重建失效
    served_cache.invalidate()  # 当日 served 缓存：跨测试隔离（避免模块级缓存污染）
    # V0.60.0：行情缓存（_cache_get/_cache_set）也是进程级 dict，跨测试必须清空
    with market_data._CACHE_LOCK:
        market_data._CACHE.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture
async def db_session():
    """服务层测试用的独立数据库会话。"""
    async with async_session_factory() as session:
        yield session


@pytest.fixture
async def client() -> AsyncClient:
    """内存级异步测试客户端：直接走 ASGI 通道，不监听端口。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
