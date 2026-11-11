import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# 允许直接运行 alembic CLI（项目根为 cwd）
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings  # noqa: E402
from app.models.base import Base  # noqa: E402
import app.models  # noqa: E402,F401  注册全部 ORM 模型

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# 数据库 URL 从应用配置读取（支持 DATABASE_URL 环境变量切换测试库）
config.set_main_option("sqlalchemy.url", get_settings().database_url)

# ⚠⚠ V0.126.0：**禁止**对 MySQL 库跑 Alembic。
# 那 32 个迁移是按「从零建库」写的，在已有表的库上会「table already exists」报错；
# 更糟的是**中途失败会留下半迁移的 schema**（前几条 apply、后几条没 apply），
# 而版本号已推进 ⇒ 再也跑不回来。
# MySQL 的 schema 由 scripts/migrate_sqlite_to_mysql.py 负责（镜像生产 SQLite 的
# sqlite_master，并写入同样的 alembic_version）。
if get_settings().database_url.startswith(("mysql", "mariadb")):
    raise RuntimeError(
        "Alembic 不支持 MySQL 生产库：MySQL 的 schema 由 "
        "scripts/migrate_sqlite_to_mysql.py 建立并维护，不走 Alembic。"
        "（本项目里 SQLite 才是被 Alembic 管理的那个库。）"
    )

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 供 autogenerate 对比的元数据
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
