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
        # V0.79.0 任务 #162：技术面 5 维度明细 JSON（trend_5 网格回测的前置）。
        # ⚠ 历史 24 行**保持 NULL 不回填** —— 上游 K 线只覆盖其中 16-17 天，
        # 回填不可能完整；缺失日期绝不用邻近日期顶替（那是伪造历史）。
        ("tech_detail", "TEXT", "NULL"),
        # V0.79.0 任务 #163：行情来源标记（历史行 NULL = 未标记，不可当作 live）
        ("data_source", "VARCHAR(16)", "NULL"),
    ],
    # V0.80.0 任务 #159 第 2 批：另两张用户数据表加 user_id
    "analysis_records": [
        ("user_id", "INTEGER", "1"),
    ],
    "push_subscriptions": [
        ("user_id", "INTEGER", "1"),
    ],
    "positions": [
        ("deleted_at", "DATETIME", "NULL"),
        # V0.62.0 单用户多账本：老库经此路径升级时补列并归入默认账本（id=1）
        ("account_id", "INTEGER", "1"),
    ],
    "news_scores": [
        # V0.65.0 每日 3 次打分机会：老库补槽位序号与打分时刻
        ("slot", "INTEGER", "1"),
        ("scored_at", "DATETIME", "NULL"),
        # V0.80.0 任务 #159 第 2 批：数据隔离（归属用户，存量归 LEGACY_USER_ID=1）
        ("user_id", "INTEGER", "1"),
        # V0.66.0 研判复盘：结构化研判依据 + 事后批注 + 补录标记
        ("basis", "TEXT", "''"),
        ("review_note", "TEXT", "''"),
        ("backfilled", "INTEGER", "0"),
    ],
}

# 高频查询字段索引：表名 -> 列名列表
INDEX_MIGRATIONS: dict[str, list[str]] = {
    "daily_snapshots": ["snapshot_date"],
    "news_scores": ["score_date"],
    "positions": ["account_id"],
}

# 复合唯一索引：表名 -> [(索引名, [列...])]
UNIQUE_INDEX_MIGRATIONS: dict[str, list[tuple[str, list[str]]]] = {
    # ⚠ V0.80.0 数据隔离：键从 ``(score_date, slot)`` 扩为
    # ``(user_id, score_date, slot)`` —— 改前两个用户同日同槽位无法共存。
    "news_scores": [("uq_news_scores_user_date_slot", ["user_id", "score_date", "slot"])],
}

# ⚠ V0.80.0：随唯一键变更作废的历史唯一索引（旧名，迁移时需删除）。
LEGACY_UNIQUE_INDEX_DROPS: list[tuple[str, str]] = [
    # V0.65.0 建的旧键（score_date, slot）
    ("news_scores", "uq_news_scores_date_slot"),
]

# 历史遗留索引：V0.65.0 起同一 score_date 允许多条记录，
# 旧的 score_date 唯一索引必须移除，否则第 2/3 次打分写入会被拒。
LEGACY_INDEX_DROPS: list[str] = ["ix_news_scores_score_date"]


async def ensure_sqlite_columns(engine: AsyncEngine) -> None:
    """检查并补齐各表新增列（幂等，缺失才执行 ALTER TABLE）。

    表不存在时跳过（部分老库 / 测试场景）：调用方应保证上游 Alembic / create_all
    已建表；此处仅做列级补齐。
    """
    async with engine.connect() as conn:
        for table, columns in COLUMN_MIGRATIONS.items():
            # 表不存在则跳过（PRAGMA table_info 返回空，但 ALTER 会失败）
            tbl_exists = (
                await conn.execute(
                    text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"),
                    {"n": table},
                )
            ).first()
            if not tbl_exists:
                logger.debug("db migrate: table %s not present, skip", table)
                continue

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


async def ensure_sqlite_optimizations(engine: AsyncEngine) -> None:
    """SQLite 性能优化：WAL 模式（高并发读写）+ 常用查询索引（幂等）。"""
    async with engine.connect() as conn:
        mode = (await conn.execute(text("PRAGMA journal_mode=WAL"))).scalar()
        if mode:
            logger.info("sqlite journal_mode=%s", mode)

        for table, columns in INDEX_MIGRATIONS.items():
            for col in columns:
                idx = f"idx_{table}_{col}"
                await conn.execute(text(f"CREATE INDEX IF NOT EXISTS {idx} ON {table} ({col})"))
                logger.info("sqlite index ready: %s on %s(%s)", idx, table, col)

        # 移除历史遗留索引（V0.65.0：news_scores 的 score_date 唯一索引须放开）
        for legacy in LEGACY_INDEX_DROPS:
            await conn.execute(text(f"DROP INDEX IF EXISTS {legacy}"))

        # ⚠ V0.80.0：先删「因唯一键变更而作废」的历史唯一索引。
        # ⚠ **顺序很关键**：news_scores 的旧键是 (score_date, slot)，若不先删掉，
        # 它会**继续阻止**两个用户同日同槽位共存（新建的新键虽已是三元组，
        # 但旧键仍在生效）⇒ 数据隔离形同虚设。
        for table, name in LEGACY_UNIQUE_INDEX_DROPS:
            try:
                await conn.execute(text(f"DROP INDEX IF EXISTS {name}"))
                logger.info("sqlite legacy unique index dropped: %s (on %s)", name, table)
            except Exception as exc:
                logger.warning("sqlite legacy unique index drop failed: %s (%s)", name, exc)

        # 复合唯一索引（幂等；存量数据冲突时降级为告警，不阻断启动）
        for table, entries in UNIQUE_INDEX_MIGRATIONS.items():
            for name, cols in entries:
                try:
                    await conn.execute(
                        text(
                            f"CREATE UNIQUE INDEX IF NOT EXISTS {name} "
                            f"ON {table} ({', '.join(cols)})"
                        )
                    )
                    logger.info(
                        "sqlite unique index ready: %s on %s(%s)", name, table, ", ".join(cols)
                    )
                except Exception as exc:  # 存量脏数据不应阻断启动
                    logger.warning("sqlite unique index skipped: %s (%s)", name, exc)

        await conn.commit()
