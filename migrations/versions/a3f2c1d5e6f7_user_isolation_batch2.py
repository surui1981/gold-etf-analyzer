"""业务表加 user_id（V0.80.0 · 任务 #159 第 2 批 · 数据隔离）

Revision ID: a3f2c1d5e6f7
Revises: g3b4c5d6e7f8
Create Date: 2026-10-07 19:45:00.000000

迁移策略（SQLite 友好、可重复执行）
----------------------------------
给三张**用户数据表**补 ``user_id`` 列 + 索引，并把存量行归入
``LEGACY_USER_ID = 1``（单用户模式的既有语义）：

- ``news_scores``（用户消息面打分）
- ``analysis_records``（机会分析记录）
- ``push_subscriptions``（推送订阅）

为什么这三张表
--------------
本仓 12 张业务表分四类（``docs/roadmap.md`` §5.1，按 ``PRAGMA table_info``
实测分类）：

1. **已有 user_id**：``accounts`` / ``positions`` / ``sessions`` /
   ``telemetry_events`` —— V0.62.0 起就在
2. **本迁移新增**：``trade_records``（已随持仓批交付）/ 本次这三张
3. **混合表需单独设计**：``app_settings``（用户权重与服务级推送密钥混存，
   须改复合主键 + 服务级键约定值，**不在本版**）
4. **全局数据明确不加**：``gold_price_daily`` / ``central_bank_purchases`` /
   ``daily_snapshots``

⚠ **本迁移只加列，不动仓储。** 「有没有列」不是重点，**「有没有人读它」才是**
—— 现有仓储签名写作 ``user_id: int = 1``（字面量默认值）时，过滤条件恒等于
「不过滤」。仓储层的真实用户解析见第 1 批（positions/accounts）
与本批的 ``NewsScoreRepository`` / ``AnalysisRepository`` / ``PushRepository``。

⚠ **两处唯一键变更（都因数据隔离而必须改）**

1. **push_subscriptions**：原 ``endpoint`` 是 ``unique=True``。同一台设备可能登录
   不同用户，端点标识本身不足以定位订阅归属 ⇒ 改为 ``(user_id, endpoint)``。
2. **news_scores**：原 ``(score_date, slot)``。**实测发现**：加 ``user_id`` 列后，
   Bob 在与Alice 同日同槽位提交会 ``IntegrityError: UNIQUE constraint failed``
   ⇒ 两个用户**根本无法共存**，多用户下第二个人用不了打分功能。
   改为 ``(user_id, score_date, slot)``。

⚠ SQLite 无法直接「删列/列组上的 UNIQUE」⇒ 两者都需**重建表**（见下方）。

存量数据
--------
``UPDATE ... SET user_id = 1``（``LEGACY_USER_ID``）：V0.75.2 第1 批已把
``accounts`` / ``positions`` / ``telemetry_events`` 的存量行归入 1，
本批保持一致 ⇒ 单用户模式下行为与迁移前**逐字节一致**。

新库路径
--------
``create_all`` 会按 ORM 直接建出带列的新表 ⇒ 本迁移对新库是 no-op
（``_columns_exist`` 探测后跳过）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f2c1d5e6f7"
down_revision: str | Sequence[str] | None = "g3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 本批要加 user_id 的表
_TABLES = ("news_scores", "analysis_records", "push_subscriptions")

# push_subscriptions 重建时需要复制的列（按 ORM 顺序）
_PUSH_COLS = (
    "id",
    "endpoint",
    "p256dh",
    "auth",
    "user_agent",
    "created_at",
    "archived_at",
)


def _table_exists(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _columns_of(name: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(name)}


def _has_column(table: str, column: str) -> bool:
    """列是否已存在（保证可重复执行 + 新库 no-op）。"""
    return _table_exists(table) and column in _columns_of(table)


_NEWS_COLS = (
    "id",
    "score_date",
    "slot",
    "score",
    "direction",
    "notes",
    "basis",
    "review_note",
    "backfilled",
    "scored_at",
)


def _rebuild_news_scores_unique() -> None:
    """``news_scores`` 唯一键 ``(score_date, slot)`` → ``(user_id, score_date, slot)``。

    ⚠ 实测：加 ``user_id`` 列后两个用户同日同槽位会撞唯一约束
    （``IntegrityError: UNIQUE constraint failed``）⇒ 第二个用户**用不了打分功能**。
    SQLite 不能改列组上的 UNIQUE，只能重建表。
    """
    if not _has_column("news_scores", "user_id"):
        return
    existing = {
        tuple(u["column_names"])
        for u in sa.inspect(op.get_bind()).get_unique_constraints("news_scores")
    }
    if ("user_id", "score_date", "slot") in existing:
        return  # 已是目标键
    cols = ", ".join(_NEWS_COLS)
    op.execute(
        "CREATE TABLE news_scores_new ("
        "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
        "score_date DATE NOT NULL, slot INTEGER NOT NULL DEFAULT 1, "
        "score FLOAT NOT NULL, direction VARCHAR(16) NOT NULL, "
        "notes VARCHAR(500), basis TEXT DEFAULT '', review_note TEXT DEFAULT '', "
        "backfilled INTEGER DEFAULT 0, scored_at DATETIME, updated_at DATETIME, "
        "user_id INTEGER NOT NULL DEFAULT 1)"
    )
    op.execute(f"INSERT INTO news_scores_new ({cols}) SELECT {cols} FROM news_scores")
    op.execute("DROP TABLE news_scores")
    op.execute("ALTER TABLE news_scores_new RENAME TO news_scores")
    op.create_index(op.f("ix_news_scores_score_date"), "news_scores", ["score_date"], unique=False)
    op.create_index(op.f("ix_news_scores_user_id"), "news_scores", ["user_id"], unique=False)
    # ⚠ SQLite 的 alembic dialect **不支持 ALTER 约束**
    # （NotImplementedError: No support for ALTER of constraints in SQLite dialect）
    # ⇒ 用 `CREATE UNIQUE INDEX` 表达同一语义（SQLite 支持，且约束效果等价：
    # 唯一性由唯一索引强制）。索引名与 ORM 的 UniqueConstraint(name=...) 对齐，
    # 保证「库结构」与「ORM 声明」名字一致，便于排查。
    op.create_index(
        "uq_news_scores_user_date_slot",
        "news_scores",
        ["user_id", "score_date", "slot"],
        unique=True,
    )


def _rebuild_push_unique() -> None:
    """``push_subscriptions`` 的 ``endpoint`` 单列 UNIQUE → ``(user_id, endpoint)``。"""
    if not _has_column("push_subscriptions", "user_id"):
        return
    existing = {
        tuple(u["column_names"])
        for u in sa.inspect(op.get_bind()).get_unique_constraints("push_subscriptions")
    }
    if ("endpoint",) not in existing:
        return  # 无单列 UNIQUE（新建库由 create_all 负责）
    cols = ", ".join(_PUSH_COLS)
    op.execute("PRAGMA foreign_keys=OFF")
    op.execute(
        "CREATE TABLE push_subscriptions_new ("
        "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
        "endpoint VARCHAR(512) NOT NULL, "
        "p256dh TEXT NOT NULL, auth TEXT NOT NULL, "
        "user_agent VARCHAR(256), created_at DATETIME NOT NULL, "
        "archived_at DATETIME, user_id INTEGER NOT NULL DEFAULT 1)"
    )
    op.execute(f"INSERT INTO push_subscriptions_new ({cols}) SELECT {cols} FROM push_subscriptions")
    op.execute("DROP TABLE push_subscriptions")
    op.execute("ALTER TABLE push_subscriptions_new RENAME TO push_subscriptions")
    op.create_index(
        "ix_push_subscriptions_user_endpoint",
        "push_subscriptions",
        ["user_id", "endpoint"],
        unique=True,
    )
    # ⚠ 重建表只复制数据，**索引不会跟着走** ⇒ 必须补回 user_id 单列索引
    op.create_index(
        op.f("ix_push_subscriptions_user_id"), "push_subscriptions", ["user_id"], unique=False
    )
    op.execute("PRAGMA foreign_keys=ON")


def upgrade() -> None:
    """Upgrade schema."""
    for table in _TABLES:
        if _has_column(table, "user_id"):
            continue
        op.add_column(
            table,
            sa.Column(
                "user_id",
                sa.Integer(),
                nullable=False,
                server_default="1",
                comment="归属用户 users.id（V0.75.2 加列）",
            ),
        )
        op.create_index(op.f(f"ix_{table}_user_id"), table, ["user_id"], unique=False)
        # 存量行归入 LEGACY_USER_ID（server_default 已覆盖，此 UPDATE 兜底
        # 「表已存在但列刚补上」的老库场景）
        op.execute(f"UPDATE {table} SET user_id = 1 WHERE user_id IS NULL")

    _rebuild_news_scores_unique()
    _rebuild_push_unique()


def downgrade() -> None:
    """Downgrade schema.

    ⚠ **只删列，不回滚 endpoint 的唯一键变更** —— SQLite 不支持把复合唯一降回
    单列唯一（同样需要重建表）。保留复合唯一是**更严格**的状态
    （不会放进原本会被拒绝的重复行），故可接受。

    ⚠ 不回填数据：``user_id`` 是新增列，删列即丢弃归属信息。
    单用户模式下该列恒为 1（信息量为零）；多用户模式下意味着不可逆丢失
    —— 这是降级的固有代价，故写明而非静默执行。

    ⚠ 2026-10-07 实测修正：**不假设索引名**。`op.f()` 生成 ``ix_*``，
    而 SQLite 自动命名用 ``idx_*``，且 ``push_subscriptions`` 重建表后
    索引集与另两张表不同。初版按名字 drop 报「no such index」，
    并留下**半降级状态**（两张表列已删、第三张还在）——
    这是比「降级直接失败」更坏的结果。改为**按索引的列**探测实际存在者。
    """
    if not _has_column("push_subscriptions", "user_id"):
        return
    for table in _TABLES:
        if not _has_column(table, "user_id"):
            continue
        inspector = sa.inspect(op.get_bind())
        for idx in inspector.get_indexes(table):
            if "user_id" in idx["column_names"]:
                op.drop_index(idx["name"], table_name=table)
        # 删索引后表结构已变，重新取 inspector 再删列
        op.drop_column(table, "user_id")
