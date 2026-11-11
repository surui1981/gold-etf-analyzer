"""方言无关的 SQL 表达式构造（V0.126.0 生产库迁移到 MySQL）。

## 为什么需要这一层

SQLite 与 MySQL 有几组**没有共同子集**的函数/语法，凡是「拼 SQL 片段」的地方
都要按方言分叉。与 :mod:`app.repositories.upsert` 同理：**差异收在一处**，
调用方只描述「我要什么」，不描述「怎么写」。

### 已知需要分叉的函数

| 用途 | SQLite | MySQL | 备注 |
|---|---|---|---|
| 日期 → ``YYYY-MM`` | ``strftime('%Y-%m', col)`` | ``DATE_FORMAT(col, '%Y-%m')`` | MySQL 8.0 无 ``strftime`` |
| 日期 → ``YYYY-MM-DD`` | ``strftime('%Y-%m-%d', col)`` | ``DATE_FORMAT(col, '%Y-%m-%d')`` | 同上 |
| 当前时间 | ``CURRENT_TIMESTAMP`` | ``NOW()`` | SQLAlchemy 的 ``func.now()`` 两边都对，**别用** ``func.current_timestamp()`` 拼字符串 |
| 自动增量 | ``INTEGER PRIMARY KEY`` 是 rowid 别名 | 需 ``AUTO_INCREMENT`` | 见 ``scripts/migrate_sqlite_to_mysql.py`` |

⚠ ``func.strftime(...)`` 在 MySQL 上**不会报错** —— 它被编译成普通函数调用，
MySQL 在执行时才报 ``FUNCTION gold_etf.xxx.strftime does not exist``。
⇒ 这类坑**只在跑到那行 SQL 时才炸**，所以函数必须集中在这里，一次写对。

## ⚠ 分组标签的坑

用函数表达式分组时，SQL 标准要求 ``GROUP BY`` 与 ``SELECT`` 的表达式**逐字一致**
（MySQL 的 ``ONLY_FULL_GROUP_BY`` 会直接判红）。
⇒ 本模块返回的表达式**必须原样**同时放进 ``select()`` 和 ``group_by()``，
不要在 ``group_by()`` 里写字符串别名 —— 别名在 MySQL 上能过，
但 SQLite 上 ``group_by("ym")`` 会被当成**列名**而不是别名
（SQLite 只在少数情况下认别名）⇒ 两个库的结果对不上。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ColumnElement, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.upsert import session_dialect_name

__all__ = ["year_month_expr", "date_expr", "supports_mysql"]


def supports_mysql(session: AsyncSession) -> bool:
    """当前 session 是否绑定在 MySQL 系方言上。"""
    return session_dialect_name(session) in ("mysql", "mariadb")


def year_month_expr(session: AsyncSession, column: ColumnElement[Any]) -> ColumnElement[Any]:
    """把日期列格式化成 ``YYYY-MM`` 字符串（可用于 ``SELECT`` / ``GROUP BY``）。

    Examples:
        >>> # SQLite: strftime('%Y-%m', archived_at)
        >>> # MySQL : DATE_FORMAT(archived_at, '%Y-%m')
    """
    if supports_mysql(session):
        return func.date_format(column, "%Y-%m")
    return func.strftime("%Y-%m", column)


def date_expr(session: AsyncSession, column: ColumnElement[Any]) -> ColumnElement[Any]:
    """把日期列格式化成 ``YYYY-MM-DD`` 字符串。"""
    if supports_mysql(session):
        return func.date_format(column, "%Y-%m-%d")
    return func.strftime("%Y-%m-%d", column)
