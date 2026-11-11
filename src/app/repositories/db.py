"""异步数据库引擎与会话工厂（SQLAlchemy 2.0）。

V0.126.0：**双方言支持**（SQLite 用于开发/测试，MySQL 用于生产）。
本模块是全项目**唯一**的引擎定义处，方言判断都从这里走，
不要在别处重复写 ``url.startswith("sqlite")``（复制粘贴必然漂移）。

## ⚠ MySQL 的两个必设项（漏一个就有静默数据损坏）

**① 会话时区必须置 UTC。**
SQLite 的 ``CURRENT_TIMESTAMP`` 是 **UTC**；MySQL 的 ``CURRENT_TIMESTAMP``
用的是**会话时区**（本机 ``time_zone=SYSTEM`` ⇒ **CST / UTC+8**）
⇒ 不置会话时区的话，所有 ``created_at`` / ``updated_at`` 会整体**偏移 8 小时**，
而且**不会报任何错**。
⇒ 通过 ``init_command="SET time_zone='+00:00'"`` 在**每条连接**建立时置成 UTC
（改 server 级 ``default-time-zone`` 不可行：这台机器上还跑着别的库）。
本项目的时间存储口径是**朴素 UTC**（见 ``models/user.py`` 的注释），
所以会话时区 = UTC 就与 SQLite 完全一致。

**② 连接池要预检。**
MySQL 的 ``wait_timeout`` 默认 8 小时，长空闲连接会被服务端单方面掐断；
应用侧不知情 ⇒ 下一个请求撞上死连接。
⇒ ``pool_pre_ping=True``（取连接前先探活）+ ``pool_recycle=3600``（1 小时回收）。

**③ rowcount 语义必须与 SQLite 对齐。**
MySQL 的 ``INSERT ... ON DUPLICATE KEY UPDATE`` 返回「**改动**行数」
（插入=1 / 更新且值变了=2 / 更新但值没变=0），SQLite 返回「**处理过**的行数」
（插入=1 / 更新=1）。
⇒ 打开 ``CLIENT_FOUND_ROWS``，MySQL 改为返回「**匹配**行数」⇒ 与 SQLite 逐点一致。
（⚠ SQLAlchemy 的 asyncmy/aiomysql 方言**没有**自动设置这个 flag ——
它们实现了 ``_found_rows_client_flag()`` 但基类**从不调用它**，只有 mysqldb 调用
⇒ 必须自己设。）
"""

from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()


def is_sqlite_url(url: str) -> bool:
    """URL 是否指向 SQLite。"""
    return url.startswith("sqlite")


def is_mysql_url(url: str) -> bool:
    """URL 是否指向 MySQL（MariaDB 的 ``mariadb+`` 前缀也一并识别）。"""
    return url.startswith("mysql") or url.startswith("mariadb")


# SQLite 文件所在目录不存在时自动创建，避免启动即报错
if is_sqlite_url(settings.database_url):
    db_path = settings.database_url.split("///", 1)[-1]
    if db_path and db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

_IS_SQLITE = is_sqlite_url(settings.database_url)
_IS_MYSQL = is_mysql_url(settings.database_url)

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
#
# ⚠ V0.126.0：MySQL 分支**不能**带这个参数（`timeout` 不是 asyncmy 的参数）
#   ⇒ 两个方言必须分开构造，不能靠三元表达式糊在一起。
if _IS_SQLITE:
    _CONNECT_ARGS: dict = {"timeout": 30.0}
    _POOL_KWARGS: dict = {}
elif _IS_MYSQL:
    # ⚠ 会话时区置 UTC（见模块 docstring「①」）—— 漏了会静默偏移 8 小时
    _CONNECT_ARGS = {"init_command": "SET time_zone='+00:00'"}
    # ⚠ CLIENT_FOUND_ROWS：让 MySQL 的 rowcount 语义与 SQLite 对齐（见模块 docstring「③」）
    from asyncmy.constants import CLIENT as _MYSQL_CLIENT

    _CONNECT_ARGS["client_flag"] = _MYSQL_CLIENT.FOUND_ROWS
    # ⚠ 预检 + 定期回收（见模块 docstring「②」）
    _POOL_KWARGS = {
        "pool_pre_ping": True,
        "pool_recycle": 3600,
        "pool_size": 5,
        "max_overflow": 10,
    }
else:  # pragma: no cover - 未支持的方言
    raise RuntimeError(
        f"不支持的数据库 URL 前缀: {settings.database_url[:40]!r}（支持 sqlite / mysql）"
    )

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,  # 开发期打印 SQL，便于排查
    connect_args=_CONNECT_ARGS,
    **_POOL_KWARGS,
)

# ⚠ WAL 只能对**文件库**设置；`:memory:` 库开 WAL 会报错。
# 用 SQLAlchemy 事件在**每条新连接建立时**执行一次，而不是像启动流程那样
# 只对当前连接执行一次 —— 连接池会重建连接，只设一次是不够的。
if _IS_SQLITE and ":memory:" not in settings.database_url:

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
