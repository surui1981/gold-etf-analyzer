"""异步数据库引擎与会话工厂（SQLAlchemy 2.0 + aiosqlite）。"""

from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()

# SQLite 文件所在目录不存在时自动创建，避免启动即报错
if settings.database_url.startswith("sqlite"):
    db_path = settings.database_url.split("///", 1)[-1]
    if db_path and db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,  # 开发期打印 SQL，便于排查
    # ⚠⚠ V0.80.0 SQLite 并发参数：**此前完全没有配置**，导致
    #   「database is locked」在测试里高频出现（本地 1 passed / 10 errors，
    #   而 CI 因时序不同而绿 ⇒ 问题被长期掩盖）。
    #
    # 根因不是「dispose 不够」而是**配置缺失**（走完三轮才定位到这里）：
    #   · WAL 模式只在 `main.py` 的启动路径设置（`ensure_sqlite_optimizations`），
    #     而**测试完全不经过 main.py** ⇒ 测试库从未开 WAL
    #     ⇒ 读写互相阻塞；
    #   · `busy_timeout` 未设 ⇒ SQLite 默认**立即抛锁错误**而不是等待重试。
    #
    # 两个参数都是 SQLite 并发的标准做法，写在这里而不是启动流程里，
    # 是为了让**测试与生产共用同一套语义**（测试通过 ⇒ 生产也通过）。
    connect_args={"timeout": 30.0} if settings.database_url.startswith("sqlite") else {},
)

# ⚠ WAL 只能对**文件库**设置；`:memory:` 库开 WAL 会报错。
# 用 SQLAlchemy 事件在**每条新连接建立时**执行一次，而不是像启动流程那样
# 只对当前连接执行一次 —— 连接池会重建连接，只设一次是不够的。
if settings.database_url.startswith("sqlite") and ":memory:" not in settings.database_url:

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
        """每条新连接上启用 WAL + busy_timeout（幂等）。

        ⚠ 必须在 connect 事件里做：连接池会新建连接，
        在启动时对单条连接执行一次 PRAGMA 不足以覆盖后续连接。
        """
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
        finally:
            cursor.close()


# expire_on_commit=False：commit 后对象仍可访问属性，避免 async 环境下的 lazy-load 陷阱
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)
