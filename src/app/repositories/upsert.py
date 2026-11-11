"""方言无关的 upsert 语句构造（V0.126.0 生产库迁移到 MySQL）。

## 为什么需要这一层

SQLite 与 MySQL 的 upsert 语法**不兼容**，而且**没有共同的子集**：

| 方言 | 语法 | 冲突目标 |
|---|---|---|
| SQLite | ``INSERT ... ON CONFLICT (cols) DO UPDATE SET ...`` | **必须**逐字列出唯一索引的列 |
| MySQL | ``INSERT ... ON DUPLICATE KEY UPDATE col=VALUES(col)`` | **不需要**指定 ⇒ 命中表上**任意**唯一键 |

⇒ 以前 6 个仓储各自 ``from sqlalchemy.dialects.sqlite import insert as sqlite_insert``
硬编码 SQLite 语法；MySQL 下这一行会直接**语法报错**（不是静默降级）。
本模块把差异**收在一处**，调用方只说「按哪几个列去重、冲突时更新哪几列」。

## ⚠ 三条必须守住的不变量

**① ``index_elements`` 必须与表上的 UNIQUE 约束逐字一致。**
SQLite 找不到目标唯一索引时会**整条 upsert 退化成「每次都插新行」**
（V0.114.0 在 ``news_feed_items`` 上踩过：同一条新闻在库里堆出 N 份）。
MySQL 没有「找不到目标」这回事 —— 它按**任意**命中唯一键去重。
⇒ 两边对「哪些行算重复」的判断必须一致，否则**同一份代码在两个库上行为分叉**。
⇒ 本模块在 MySQL 分支**主动校验**：表上没有覆盖 ``index_elements`` 的唯一约束
就**直接抛错**（宁可启动失败，也不要静默写出重复行）。

**② MySQL 的 rowcount 语义与 SQLite 不同。**
``INSERT ... ON DUPLICATE KEY UPDATE`` 的 rowcount：
插入=**1**、更新且值变了=**2**、更新但值没变=**0**；
SQLite 则是插入=1、更新=1。
⇒ 连接层统一打开 ``CLIENT_FOUND_ROWS``（见 ``repositories/db.py``），
MySQL 的 rowcount 变成「**匹配**行数」⇒ 与 SQLite 逐点对齐
（SQLite 的 ``changes()`` 本来就是「被语句处理过的行数」，不是「值变了的行数」）。

**③ 「引用本次要插入的那一行」在两个方言上覆盖的列不同。**
SQLite 的 ``excluded.<col>`` **包含**被省略列的默认值（SQLite 插入时就把默认值填好了）；
MySQL 的行别名 ``new.<col>`` **只暴露 INSERT 列清单里出现过的列** ⇒ 少一列就是
``error 1054 Unknown column 'new.xxx' in 'field list'``。
⇒ MySQL 分支对「payload 里没有、但要更新」的列改用该列的**隐式默认值**
（见 :func:`_mysql_update_expressions`）。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Table, UniqueConstraint, literal, null
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.logger import get_logger

logger = get_logger(__name__)


def session_dialect_name(session: AsyncSession) -> str:
    """当前 session 绑定的方言名（``sqlite`` / ``mysql``）。

    ⚠ 不能靠「URL 前缀」判断方言：**同一个进程里可能同时存在两个 engine**
    （例如测试里另建一个 SQLite 引擎），方言只能从**绑定**上读。
    """
    bind = session.get_bind()
    return bind.dialect.name


def has_unique_on(table: Table, columns: Sequence[str]) -> bool:
    """表上是否存在**恰好**覆盖 ``columns`` 的唯一约束 / 唯一索引 / 主键。

    ⚠ ``columns`` 是**列名字符串**序列（与 ``build_upsert`` 的入参一致）。
    ⚠ **主键也算**：MySQL 的 ``ON DUPLICATE KEY UPDATE`` 对主键冲突同样生效
    （``news_feed_daily`` 的去重键就是单列主键 ``date``）。
    """
    wanted = set(columns)
    for idx in table.indexes:
        if idx.unique and {c.name for c in idx.columns} == wanted:
            return True
    for con in table.constraints:
        if isinstance(con, UniqueConstraint) and {c.name for c in con.columns} == wanted:
            return True
    # ⚠ 主键也算唯一键（news_feed_daily 的去重键就是单列主键 date）
    return {c.name for c in table.primary_key.columns} == wanted


def build_upsert(
    session: AsyncSession,
    table: Table,
    values: list[dict[str, Any]] | dict[str, Any],
    *,
    index_elements: Sequence[str],
    update_columns: Sequence[str],
) -> Any:
    """构造方言自适应的 upsert 语句。

    Args:
        session: 用来判定方言（**绑定**的方言，不是 URL）。
        table: 目标表。
        values: 待写入的行（dict 或 dict 列表）。
        index_elements: 去重键的列名（必须与表上 UNIQUE 逐字一致）。
        update_columns: 冲突时要覆盖的列名（值取自本次插入的行）。

    Returns:
        可直接 ``await session.execute(stmt)`` 的语句。

    Raises:
        RuntimeError: MySQL 分支下表上没有匹配 ``index_elements`` 的唯一约束。
    """
    dialect = session_dialect_name(session)
    if dialect == "mysql":
        # ⚠ 不变量①：MySQL 按「任意」唯一键去重 ⇒ 唯一键对不上就是静默写重复行
        if not has_unique_on(table, index_elements):
            raise RuntimeError(
                f"upsert 目标唯一键不存在：表 {table.name} 上没有覆盖 "
                f"{list(index_elements)} 的 UNIQUE 约束/唯一索引 ⇒ "
                f"MySQL 会按**另一个**唯一键去重（与 SQLite 行为分叉）。"
            )
        stmt = mysql_insert(table).values(values)
        return stmt.on_duplicate_key_update(
            **_mysql_update_expressions(stmt, table, update_columns, values)
        )

    if dialect != "sqlite":
        raise RuntimeError(f"upsert 不支持的方言：{dialect!r}")

    stmt = sqlite_insert(table).values(values)
    return stmt.on_conflict_do_update(
        index_elements=list(index_elements),
        set_={col: stmt.excluded[col] for col in update_columns},
    )


def _payload_columns(values: list[dict[str, Any]] | dict[str, Any]) -> set[str]:
    """本次 INSERT 实际会写哪些列（= payload 里出现过的键的并集）。

    ⚠ MySQL 编译出来的 ``INSERT INTO t (a, b, c)`` 列清单**只包含**这里返回的列；
    没在 payload 里出现的列走**数据库端的默认值**，且**不在列清单里**。
    """
    if isinstance(values, dict):
        return set(values)
    cols: set[str] = set()
    for row in values:
        cols.update(row)
    return cols


def _column_default_expr(column: Any) -> Any | None:
    """取该列的「隐式默认值」表达式（用于对齐 SQLite ``excluded`` 的语义）。

    - ``server_default=func.now()`` → ``CURRENT_TIMESTAMP``（Function 元素，直接用）
    - ``server_default="readhub"``  → 字面量 ``'readhub'``（要加引号）
    - ``server_default=text("('')")`` → 原样用（它本身就是表达式）
    - 没有 ``server_default`` → ``None``（调用方回退到 NULL）
    """
    sd = getattr(column, "server_default", None)
    if sd is None:
        return None
    arg = getattr(sd, "arg", None)
    if arg is None:
        return None
    if isinstance(arg, str):
        return literal(arg)
    return arg


def _mysql_update_expressions(
    stmt: Any,
    table: Table,
    update_columns: Sequence[str],
    values: list[dict[str, Any]] | dict[str, Any],
) -> dict[str, Any]:
    """构造 MySQL 的 ``ON DUPLICATE KEY UPDATE`` 表达式表。

    ## ⚠ 这是两个方言**语义不同**的地方（V0.126.0 实测踩到）

    | 方言 | 引用「本次要插入的那一行」 | 省略的列 |
    |---|---|---|
    | SQLite | ``excluded.<col>`` | **含**该列的默认值（SQLite 插入时就把默认值填好了）|
    | MySQL | ``new.<col>``（行别名） | **不含** —— 列清单里没出现的列，``new.<col>`` 直接报 error 1054 |

    实测踩坑：``news_feed_items`` 的 payload 不带 ``fetched_at`` / ``source``
    （靠列的 ``server_default`` 补），而 ``update_columns`` 里却有它们 ⇒
    MySQL 报 ``Unknown column 'new.fetched_at' in 'field list'`` ⇒
    **整个新闻流 upsert 失败**（SQLite 上同样的语句完全正常，因为 ``excluded``
    里有这两列的默认值）。

    ⇒ 这里按 MySQL 的规则补齐：对「payload 里没有、但要更新」的列，
    改用该列的**隐式默认值**表达式（``server_default``，没有则 NULL），
    语义与 SQLite 的 ``excluded`` **逐点对齐**。
    """
    payload_cols = _payload_columns(values)
    updates: dict[str, Any] = {}
    for col in update_columns:
        if col in payload_cols:
            updates[col] = stmt.inserted[col]
            continue
        column = table.c.get(col)
        default_expr = _column_default_expr(column) if column is not None else None
        if default_expr is not None:
            updates[col] = default_expr
        else:
            # 无默认值 ⇒ SQLite 的 excluded.<col> 就是 NULL（可空列的隐式默认）
            updates[col] = null()
        logger.warning(
            "upsert 更新列 %s.%s 不在 payload 里 ⇒ 按列默认值对齐 SQLite 的 excluded 语义",
            table.name,
            col,
        )
    return updates


def affected_row_count(result: Any, *, dialect: str, expected_rows: int) -> int:
    """归一化 upsert 的「写入行数」，抹平 SQLite / MySQL 的 rowcount 差异。

    ⚠ **两个方言的 rowcount 不是同一个口径**：

    | 情形 | SQLite | MySQL |
    |---|---|---|
    | 插入新行 | 1 | 1 |
    | 更新已有行（值变了） | 1 | **2** |
    | 更新已有行（值没变） | 1 | 1（有 ``CLIENT_FOUND_ROWS``） |

    ⇒ 一批 100 行里若有 30 行是更新，MySQL 报 **130**、SQLite 报 **100**
    ⇒ 对外那句「upserted=N」在两个库上**含义不同**（MySQL 上虚高 30%）。

    ⇒ MySQL 分支直接用「本次 upsert 覆盖的行数」= ``expected_rows``（payload 行数）：
    每个 payload 行要么插入、要么更新，都恰好让目标表多出/刷新 1 行
    ⇒ 与 SQLite 的 rowcount **逐点相等**（SQLite 的 ``changes()`` 本来就是这个口径）。
    SQLite 分支保留数据库自己报的 rowcount，并在与 ``expected_rows`` 不一致时告警
    （不一致说明有预料外的行被跳过 —— 这种异常不该被悄悄抹平）。
    """
    if dialect == "mysql":
        return expected_rows
    rc = int(result.rowcount or 0)
    if rc != expected_rows:
        logger.warning(
            "upsert rowcount 与写入行数不一致：rowcount=%d，payload 行数=%d（%s）",
            rc,
            expected_rows,
            getattr(result, "context", None),
        )
    return rc


__all__ = ["affected_row_count", "build_upsert", "has_unique_on", "session_dialect_name"]
