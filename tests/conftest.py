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
    # V0.79.0 Step G：清空后台任务追踪集合。
    #
    # ⚠ V0.80.0 更正：原注释写「不能 await 它们，否则 Event loop is closed」
    # （悬挂 task 可能绑定在已关闭的 loop 上，gather 会 RuntimeError）——
    # **那个理由成立，但据此得出的「只 clear() 就够了」是错的**。
    # clear() 只丢掉强引用，task 仍在运行；而锁的**真正持有者是连接池**
    # （见下方 `engine.dispose()` 的说明），清 task 只是辅助。
    # 这里保持 clear() 不 await：它能回收引用，且不引入跨 loop 的 await 风险。
    from app.services.background import _BACKGROUND_TASKS

    _BACKGROUND_TASKS.clear()

    from app.repositories import market_data
    from app.services import backtest_throttle as throttle
    from app.services import cache as served_cache
    from app.services import macro as macro_mod  # V0.79.0 Step E：模块级 _CACHE
    from app.services import task_registry  # V0.79.0 Step G
    from app.services.settings import clear_weights_cache

    clear_weights_cache()  # 配置内存缓存随库重建失效
    served_cache.invalidate()  # 当日 served 缓存：跨测试隔离（避免模块级缓存污染）
    throttle.clear()  # 回测 5 分钟节流缓存（V0.71.0）
    task_registry.clear()  # 异步任务注册表（V0.79.0 Step G）
    # V0.79.0 Step E：MacroFactorService._CACHE 是模块级 dict，跨测试必须清空
    macro_mod._CACHE = {"ts": 0.0, "result": None}
    # V0.60.0：行情缓存（_cache_get/_cache_set）也是进程级 dict，跨测试必须清空
    with market_data._CACHE_LOCK:
        market_data._CACHE.clear()

    # ⚠⚠ V0.80.0 修 database is locked：drop_all / create_all 之前先 dispose 连接池。
    #
    # 根因由 SQLAlchemy 自己打印在告警里：
    #   "The garbage collector is trying to clean up non-checked-in connection
    #    <AdaptedConnection ...> ... Please ensure that SQLAlchemy pooled connections
    #    are returned to the pool explicitly"
    #
    # 成因链条（三环缺一不可）：
    #   ① `repositories/db.py` 的 `engine` 是**模块级单例**，导入时创建 ⇒
    #      连接池被**第一个** event loop 的线程绑定；
    #   ② pytest-asyncio 默认**每个测试函数新建 event_loop**（asyncio_mode=auto）；
    #   ③ 上一个用例遗留的 pooled 连接**没有 check-in** ⇒ 本用例的 drop_all
    #      在旧连接上执行 ⇒ sqlite 报 database is locked。
    #
    # ⚠ 不是「掩盖问题」：dispose 正是上面那句 SQLAlchemy 告警要求的
    # 「return connections to the pool explicitly」。dispose 后 pool 会重建，
    # 下一个用例的 engine.begin() 自然拿到新连接 —— 语义正确。
    #
    # **负向验证（2026-10-07）**：移除此行 ⇒ `test_async_backtest.py`
    # 精确复现「1 passed / 10 errors」；加回 ⇒「11 passed」。
    # 因果关系已确认，不是碰巧通过。
    await engine.dispose()

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
