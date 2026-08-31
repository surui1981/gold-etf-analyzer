"""SQLite 轻量列迁移测试：缺失列自动补齐且幂等。"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.utils.db_migrate import ensure_sqlite_columns


async def _make_engine(tmp_path) -> AsyncEngine:
    db_file = tmp_path / "migrate_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        # 模拟历史库：缺 news_index 列
        await conn.execute(
            text(
                "CREATE TABLE daily_snapshots ("
                "id INTEGER PRIMARY KEY, snapshot_date TEXT, trend_index FLOAT)"
            )
        )
        await conn.execute(
            text("INSERT INTO daily_snapshots (snapshot_date, trend_index) VALUES ('2026-01-01', 60.0)")
        )
    return engine


async def _columns(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as conn:
        rows = await conn.execute(text("PRAGMA table_info(daily_snapshots)"))
        return {row[1] for row in rows}


async def test_add_missing_column(tmp_path) -> None:
    """历史库缺列时自动 ALTER TABLE 补齐，且原有数据不丢失。"""
    engine = await _make_engine(tmp_path)
    assert "news_index" not in await _columns(engine)

    await ensure_sqlite_columns(engine)

    assert "news_index" in await _columns(engine)
    async with engine.connect() as conn:
        val = await conn.execute(text("SELECT trend_index FROM daily_snapshots"))
        assert val.scalar() == 60.0
    await engine.dispose()


async def test_migration_is_idempotent(tmp_path) -> None:
    """重复执行迁移不报错、不重复加列。"""
    engine = await _make_engine(tmp_path)
    await ensure_sqlite_columns(engine)
    await ensure_sqlite_columns(engine)
    await ensure_sqlite_columns(engine)

    cols = await _columns(engine)
    assert list(cols).count("news_index") == 1
    await engine.dispose()
