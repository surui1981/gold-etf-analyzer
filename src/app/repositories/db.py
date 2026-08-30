"""异步数据库引擎与会话工厂（SQLAlchemy 2.0 + aiosqlite）。"""

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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
)

# expire_on_commit=False：commit 后对象仍可访问属性，避免 async 环境下的 lazy-load 陷阱
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)
