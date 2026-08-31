"""SQLite 轻量迁移：为已存在的表补充新增列。

背景：SQLAlchemy 的 ``create_all`` 只会创建新表，不会给已存在的表添加新列。
历史版本升级后（如 V0.20 新增 daily_snapshots.news_index）会导致查询报错
"no such column"，因此启动时按声明补齐缺失列，用户数据不丢失。
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.utils.logger import get_logger

logger = get_logger(__name__)

# 表名 -> [(列名, SQLite 类型, 默认值)]
COLUMN_MIGRATIONS: dict[str, list[tuple[str, str, str]]] = {
    "daily_snapshots": [
        ("news_index", "FLOAT", "50"),
    ],
}


async def ensure_sqlite_columns(engine: AsyncEngine) -> None:
    """检查并补齐各表新增列（幂等，缺失才执行 ALTER TABLE）。"""
    async with engine.connect() as conn:
        for table, columns in COLUMN_MIGRATIONS.items():
            rows = await conn.execute(text(f"PRAGMA table_info({table})"))
            existing = {row[1] for row in rows}

            for col, col_type, default in columns:
                if col in existing:
                    continue
                await conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type} DEFAULT {default}")
                )
                logger.warning("db migrate: added column %s.%s (%s)", table, col, col_type)

        await conn.commit()
