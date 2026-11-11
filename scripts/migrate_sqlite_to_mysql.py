#!/usr/bin/env python3
"""SQLite → MySQL 生产库迁移（V0.126.0）。

## 为什么目标 schema 从**生产 SQLite**导出，而不是从 ORM 生成

生产库的权威结构是「ORM + 32 个 alembic 迁移 + 若干手工 ALTER」的**叠加结果**，
与 ORM 已有 **42 处差异**（比如 ``user_news_favorites.news_source`` 在 ORM 里是
``String(32)``、在生产库里还是更早的 ``TEXT``）。
⇒ 用 ORM ``create_all`` 生成 MySQL 结构，等于**顺手改掉 42 处**没人审过的差异。
⇒ 本脚本**只认生产 SQLite 的实际结构**（``sqlite_master`` + ``PRAGMA table_info``），
逐列翻译成 MySQL DDL。

## 三条必须守住的不变量

**① 目标列类型按「精度等价」翻译，不是按名字翻译。**

| SQLite | MySQL | 为什么 |
|---|---|---|
| ``INTEGER`` | ``BIGINT`` | SQLite INTEGER = int64；MySQL ``INT`` = int32（**溢出**） |
| ``FLOAT`` / ``REAL`` | ``DOUBLE`` | SQLite FLOAT = float64；MySQL ``FLOAT`` = float32（**静默截断**） |
| ``TEXT`` | ``LONGTEXT`` | MySQL ``TEXT`` 只有 64KB；``macro_detail`` 这类 JSON 会超 |
| ``DATETIME`` | ``DATETIME(6)`` | MySQL ``DATETIME`` 是秒级 ⇒ 微秒被**四舍五入**（整秒都可能差 1） |
| ``NUMERIC(p,s)`` | ``DECIMAL(p,s)`` | 同义 |

**② 主键必须是 ``AUTO_INCREMENT``。**
SQLite 里 ``id INTEGER NOT NULL, PRIMARY KEY (id)``（表级单列 PK）**是 rowid 别名**
⇒ 插入时 SQLite 自己发 id。而 MySQL 的 ``BIGINT PRIMARY KEY`` **不发** id
⇒ 应用（ORM 省略 id 插入）会直接撞主键。
⇒ 单列 INTEGER 主键一律翻译成 ``BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY``，
并在灌完数据后把 ``AUTO_INCREMENT`` 拨到 ``max(id)+1``。

**③ 不建外键约束。**
生产 SQLite 的 ``PRAGMA foreign_keys`` 默认关 ⇒ 外键**从来没被真正执行过**
（``ON DELETE CASCADE`` 也是空话）。
在 MySQL 里真建外键 = **顺手改语义**：删用户时 MySQL 会因 ``RESTRICT`` 报 1451，
删会话时会真的级联删消息 —— 这些行为线上从没发生过。
⇒ 迁移只搬数据与结构，**不改行为**；要不要在 MySQL 上真正启用外键，是另一件事。

## 用法

    # 1) 看计划（不连 MySQL 也行）
    python scripts/migrate_sqlite_to_mysql.py --dry-run

    # 2) 真迁（建表 + 灌数据 + 逐表校验 + 回填 alembic_version）
    python scripts/migrate_sqlite_to_mysql.py --apply

    # 3) 只校验（行数 + 内容校验和）
    python scripts/migrate_sqlite_to_mysql.py --verify

    # 4) 回滚：删掉本脚本在 MySQL 侧建的表
    python scripts/migrate_sqlite_to_mysql.py --drop-target

⚠ **停机窗口内跑**（切库时服务要停）：源库文件应来自刚做的备份，
否则迁移过程中线上写入会漏在快照之外。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SOURCE = os.path.join(PROJECT_DIR, "data", "gold_etf.db")
DEFAULT_ENV_FILE = os.path.join(PROJECT_DIR, ".env.mysql")

CHARSET = "utf8mb4"
COLLATION = "utf8mb4_0900_ai_ci"

BATCH_SIZE = 2000

# ---------------------------------------------------------------------------
# 类型翻译
# ---------------------------------------------------------------------------

#: SQLite 声明类型 → MySQL 列类型（按「精度等价」而非同名）
TYPE_MAP: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^INTEGER$"), "BIGINT"),
    (re.compile(r"^INT$"), "BIGINT"),
    (re.compile(r"^BIGINT$"), "BIGINT"),
    (re.compile(r"^SMALLINT$"), "BIGINT"),
    (re.compile(r"^FLOAT$"), "DOUBLE"),
    (re.compile(r"^REAL$"), "DOUBLE"),
    (re.compile(r"^DOUBLE$"), "DOUBLE"),
    (re.compile(r"^DOUBLE PRECISION$"), "DOUBLE"),
    (re.compile(r"^BOOLEAN$"), "BOOLEAN"),
    (re.compile(r"^VARCHAR\((\d+)\)$"), r"VARCHAR(\1)"),
    (re.compile(r"^CHAR\((\d+)\)$"), r"CHAR(\1)"),
    (re.compile(r"^TEXT$"), "LONGTEXT"),
    (re.compile(r"^CLOB$"), "LONGTEXT"),
    (re.compile(r"^DATETIME$"), "DATETIME(6)"),
    (re.compile(r"^TIMESTAMP$"), "DATETIME(6)"),
    (re.compile(r"^DATE$"), "DATE"),
    (re.compile(r"^NUMERIC\((\d+),\s*(\d+)\)$"), r"DECIMAL(\1,\2)"),
    (re.compile(r"^NUMERIC$"), "DECIMAL(20,6)"),
    (re.compile(r"^DECIMAL\((\d+),\s*(\d+)\)$"), r"DECIMAL(\1,\2)"),
]

#: 逐列类型覆盖（生产 DDL 与 ORM 有出入时，按 **ORM** 口径 —— ORM 才是应用真正的契约）
COLUMN_TYPE_OVERRIDES: dict[tuple[str, str], str] = {
    # 生产库还停在更早的 TEXT；ORM 已改成 String(32)。
    # ⚠ 必须改：MySQL 的 UNIQUE **不能**直接建在 TEXT/BLOB 上（error 1170）。
    ("user_news_favorites", "news_source"): "VARCHAR(32)",
    # ⚠ 生产库的 site_name 还停在更早的 ``TEXT``，ORM 已改成 String(64)。
    # ⚠ 必须改：MySQL 的 INDEX 不能直接建在 TEXT/BLOB 上（error 1170）。
    ("user_news_favorites", "site_name"): "VARCHAR(64)",
    # ⚠ **长度不足**：生产 DDL 写的是 VARCHAR(3)（ISO 3 字母代码），
    #   但库里存着 WGC 全球合计行的伪 ISO —— ``WGC_AGGR``（8 字符）。
    #   SQLite **不校验** VARCHAR 长度 ⇒ 一路存得好好的；
    #   MySQL 严格模式直接报 error 1406「Data too long」。
    #   ⇒ 这里放宽到 VARCHAR(16)（ORM 同步改成 String(16)）。
    ("central_bank_purchases", "country_iso"): "VARCHAR(16)",
}


def translate_type(sqlite_type: str) -> str:
    """SQLite 声明类型 → MySQL 列类型。未知类型一律报错（不猜）。"""
    t = (sqlite_type or "").strip().upper()
    for pattern, mysql_type in TYPE_MAP:
        if pattern.match(t):
            # ⚠ 必须用 sub 而不是直接返回模板 —— 模板里有 ``\1``（捕获组）
            # （V0.126.0 实测：直接返回会产出 ``VARCHAR(\\1)`` 这种废 DDL）
            return pattern.sub(mysql_type, t)
    raise ValueError(f"未知的 SQLite 列类型：{sqlite_type!r}（不猜 ⇒ 直接报错）")


# ---------------------------------------------------------------------------
# 源库 schema 读取
# ---------------------------------------------------------------------------


@dataclass
class Column:
    name: str
    sqlite_type: str
    mysql_type: str
    notnull: bool
    default: str | None
    pk: bool


@dataclass
class Unique:
    name: str
    columns: list[str]


@dataclass
class Index:
    name: str
    sql: str


@dataclass
class Table:
    name: str
    columns: list[Column] = field(default_factory=list)
    uniques: list[Unique] = field(default_factory=list)
    indexes: list[Index] = field(default_factory=list)
    pk_columns: list[str] = field(default_factory=list)
    autoincrement: bool = False

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]


_CONSTRAINT_UNIQUE_RE = re.compile(r"CONSTRAINT\s+(\w+)\s+UNIQUE\s*\(([^)]*)\)", re.IGNORECASE)
_COLUMN_UNIQUE_RE = re.compile(r"^\s*\w+\s+[^,]*\bUNIQUE\b", re.IGNORECASE)


def read_sqlite_schema(conn: sqlite3.Connection) -> list[Table]:
    """从生产 SQLite 读出结构（表 / 列 / 唯一约束 / 显式索引）。"""
    tables: list[Table] = []
    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    index_rows = conn.execute(
        "SELECT name, tbl_name, sql FROM sqlite_master "
        "WHERE type='index' AND sql IS NOT NULL ORDER BY name"
    ).fetchall()

    for name, ddl in rows:
        tbl = Table(name=name)
        ddl = ddl or ""

        # 列
        pk_cols: list[tuple[int, str]] = []
        for _cid, cname, ctype, notnull, dflt, pk in conn.execute(f'PRAGMA table_info("{name}")'):
            mysql_type = COLUMN_TYPE_OVERRIDES.get((name, cname), translate_type(ctype or ""))
            tbl.columns.append(
                Column(
                    name=cname,
                    sqlite_type=(ctype or "").upper(),
                    mysql_type=mysql_type,
                    notnull=bool(notnull),
                    default=dflt,
                    pk=bool(pk),
                )
            )
            if pk:
                pk_cols.append((pk, cname))
        tbl.pk_columns = [c for _, c in sorted(pk_cols)]

        # 表级命名 UNIQUE 约束
        for uname, cols in _CONSTRAINT_UNIQUE_RE.findall(ddl):
            col_list = [c.strip().strip('"`[]') for c in cols.split(",")]
            tbl.uniques.append(Unique(name=uname, columns=col_list))

        # 列级 UNIQUE（ORM 的 unique=True 可能渲染成表级，SQLite 多半也是表级；
        # 这里兜底扫描单列定义）
        for col in tbl.columns:
            if col.name in {c for u in tbl.uniques for c in u.columns}:
                continue
            m = re.search(rf"`?\"?{re.escape(col.name)}\"?\s+[^,]*?\bUNIQUE\b", ddl, re.IGNORECASE)
            if m:
                tbl.uniques.append(Unique(name=f"uq_{name}_{col.name}", columns=[col.name]))

        # 单列 INTEGER 主键 ⇒ rowid 别名 ⇒ 需要 AUTO_INCREMENT
        tbl.autoincrement = (
            len(tbl.pk_columns) == 1
            and next((c for c in tbl.columns if c.name == tbl.pk_columns[0]), None) is not None
            and next(c for c in tbl.columns if c.name == tbl.pk_columns[0]).sqlite_type == "INTEGER"
        )

        tables.append(tbl)

    # 显式索引（CREATE INDEX / CREATE UNIQUE INDEX）
    by_name = {t.name: t for t in tables}
    for iname, tname, isql in index_rows:
        tbl = by_name.get(tname)
        if tbl is None:
            continue
        tbl.indexes.append(Index(name=iname, sql=isql))

    return tables


# ---------------------------------------------------------------------------
# DDL 生成
# ---------------------------------------------------------------------------


def _quote(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def _render_default(col: Column) -> str:
    """把 SQLite 的默认值字面量翻成 MySQL 可用的 DEFAULT 子句。

    ⚠ **TEXT 列的默认值必须写成表达式**（``DEFAULT ('')``）：
    MySQL 报 error 1101「BLOB/TEXT/JSON 列不能有默认值」——
    除非是 8.0.13+ 的**带括号表达式**默认值。
    ⚠ ``CURRENT_TIMESTAMP`` 在 MySQL 上是**会话时区** ⇒ 连接层已钉死 UTC
    （见 ``repositories/db.py`` 的 ``init_command``），与 SQLite 的 UTC 一致。
    """
    if col.default is None:
        return ""
    raw = col.default.strip()
    upper = raw.upper()
    is_text = col.mysql_type.upper().startswith(("LONGTEXT", "TEXT", "BLOB"))

    if upper == "NULL":
        return " DEFAULT NULL" if col.notnull else ""
    if upper in ("CURRENT_TIMESTAMP", "(CURRENT_TIMESTAMP)"):
        return " DEFAULT (CURRENT_TIMESTAMP)"
    if raw.startswith("(") and raw.endswith(")"):
        inner = raw[1:-1].strip()
        if inner.upper() == "CURRENT_TIMESTAMP":
            return " DEFAULT (CURRENT_TIMESTAMP)"
        return f" DEFAULT ({inner})"
    # 字面量（SQLite 的 dflt_value 一定带引号，除非是数字/关键字）
    if is_text:
        literal = raw if raw.startswith(("'", '"')) else f"'{raw}'"
        return f" DEFAULT ({literal})"
    return f" DEFAULT {raw}"


def build_mysql_ddl(table: Table) -> str:
    """一张表的 MySQL 建表语句。"""
    cols: list[str] = []
    for col in table.columns:
        piece = f"  {_quote(col.name)} {col.mysql_type}"
        if col.name in table.pk_columns:
            if table.autoincrement and len(table.pk_columns) == 1:
                piece += " NOT NULL AUTO_INCREMENT"
            else:
                piece += " NOT NULL"
        elif col.notnull:
            piece += " NOT NULL"
        piece += _render_default(col)
        cols.append(piece)

    if table.pk_columns:
        cols.append(f"  PRIMARY KEY ({', '.join(_quote(c) for c in table.pk_columns)})")
    for uq in table.uniques:
        cols.append(
            f"  CONSTRAINT {_quote(uq.name)} UNIQUE ({', '.join(_quote(c) for c in uq.columns)})"
        )

    body = ",\n".join(cols)
    return (
        f"CREATE TABLE {_quote(table.name)} (\n{body}\n) "
        f"ENGINE=InnoDB DEFAULT CHARSET={CHARSET} COLLATE={COLLATION}"
    )


def build_mysql_indexes(table: Table) -> list[str]:
    """把 SQLite 的显式索引翻成 MySQL 的 CREATE INDEX。

    ⚠ **去重**：生产 SQLite 里同一组列上挂了两个索引
    （``idx_positions_account_id`` 与 ``ix_positions_account_id`` ——
    一个来自 ORM 的 ``index=True``，一个来自 ``db_migrate`` 的补列脚本）。
    SQLite 允许，MySQL 会警告「Duplicate index … 未来版本将不允许」。
    ⇒ 同列组只留**第一个**。
    """
    out: list[str] = []
    seen: set[tuple[bool, tuple[str, ...]]] = set()
    for idx in table.indexes:
        sql = idx.sql.strip().rstrip(";")
        is_unique = bool(re.match(r"^CREATE\s+UNIQUE\s+INDEX", sql, re.I))
        sql = re.sub(r"^CREATE\s+UNIQUE\s+INDEX", "CREATE UNIQUE INDEX", sql, flags=re.I)
        sql = re.sub(r"^CREATE\s+INDEX", "CREATE INDEX", sql, flags=re.I)
        m = re.search(r"ON\s+\S+\s*\(([^)]*)\)", sql)
        cols = tuple(x.strip().strip('"`[]').split()[0] for x in m.group(1).split(",")) if m else ()
        key = (is_unique, cols)
        if key in seen:
            continue
        seen.add(key)
        # ⚠ MySQL 的索引名是**表内唯一**（不是库级）⇒ 原名照抄即可。
        # ⚠ 但索引名最长 64 字符 ⇒ 超长截断（SQLite 不限）。
        if len(idx.name) > 60:
            sql = re.sub(
                r"^(CREATE\s+(?:UNIQUE\s+)?INDEX\s+)\S+",
                lambda mm, _name=idx.name: mm.group(1) + _name[:60],
                sql,
                flags=re.I,
            )
        out.append(f"{sql}")
    return out


# ---------------------------------------------------------------------------
# 数据搬运
# ---------------------------------------------------------------------------


def _conv_value(col: Column, value: Any) -> Any:
    """把 SQLite 取出的值转成 MySQL 友好的类型。"""
    if value is None:
        return None
    t = col.mysql_type.upper()
    if t.startswith("DATETIME") and isinstance(value, str):
        return _parse_datetime(value)
    if t == "DATE" and isinstance(value, str):
        return _parse_date(value)
    if t.startswith("DECIMAL") and isinstance(value, float):
        # 显式按列的 scale 格式化 ⇒ 舍入行为确定（MySQL 的 DECIMAL 存的是定点数）
        scale = int(t.split(",")[1].rstrip(")"))
        return f"{value:.{scale}f}"
    return value


def _parse_datetime(raw: str) -> datetime | None:
    raw = raw.strip()
    if not raw:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    raise ValueError(f"无法解析的时间戳：{raw!r}")


def _parse_date(raw: str) -> date | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"无法解析的日期：{raw!r}") from exc


def _norm_for_hash(col: Column, value: Any) -> str:
    """把值归一成**可跨库比较**的字符串（校验和用）。

    ⚠ 跨库比较必须抹掉「表示差异」但**保留数值差异**：
    - MySQL 的 DECIMAL 读回来是 ``Decimal``，SQLite 是 ``float`` ⇒ 统一按 scale 取整；
    - 布尔：SQLite 0/1 ↔ MySQL TINYINT 0/1；
    - 时间：SQLite 给**字符串**、MySQL 给 ``datetime`` ⇒ 统一成 ``%Y-%m-%d %H:%M:%S.%f``。
      ⚠ 这一步必须**按列类型**做，不能只判 Python 类型 ——
      否则 SQLite 侧的时间戳按原样（可能没有小数位）参与哈希，
      MySQL 侧按 ``.000000`` 参与 ⇒ **同一个值算出两个哈希**（假红）。
    """
    if value is None:
        return "\x00"
    t = col.mysql_type.upper()
    if t.startswith("DATETIME"):
        v = _parse_datetime(value) if isinstance(value, str) else value
        return v.strftime("%Y-%m-%d %H:%M:%S.%f")
    if t == "DATE":
        v = _parse_date(value) if isinstance(value, str) else value
        return v.strftime("%Y-%m-%d")
    if t.startswith("DECIMAL"):
        scale = int(t.split(",")[1].rstrip(")"))
        return f"{float(value):.{scale}f}"
    if t == "BOOLEAN":
        return "1" if value else "0"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S.%f")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, Decimal):
        return f"{float(value):.9f}"
    if isinstance(value, float):
        return f"{value:.9f}"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def _hash_rows(rows: list[dict[str, Any]], cols: list[Column], hasher: Any) -> None:
    for row in rows:
        for col in cols:
            hasher.update(_norm_for_hash(col, row.get(col.name)).encode("utf-8"))
            hasher.update(b"\x1f")
        hasher.update(b"\x1e")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def read_mysql_url(env_file: str) -> str:
    """从 .env.mysql（或环境变量）读 MySQL 连接串。"""
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("mysql"):
        return url
    with open(env_file, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if line.startswith("DATABASE_URL="):
                url = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    if not url.startswith("mysql"):
        raise SystemExit(f"在 {env_file} 里没找到 MySQL DATABASE_URL")
    return url


def _mysql_engine(url: str):
    """建 MySQL 引擎（连接参数与线上**完全一致**：UTC 会话时区 + CLIENT_FOUND_ROWS）。"""
    from asyncmy.constants import CLIENT as MYSQL_CLIENT

    return create_async_engine(
        url,
        connect_args={
            "init_command": "SET time_zone='+00:00'",
            "client_flag": MYSQL_CLIENT.FOUND_ROWS,
        },
        pool_pre_ping=True,
        pool_recycle=3600,
    )


async def _drop_target_tables(conn, tables: list[Table]) -> None:
    await conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
    for t in reversed(tables):
        await conn.execute(text(f"DROP TABLE IF EXISTS `{t.name}`"))
    await conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    print(f"[drop] 删掉 {len(tables)} 张表")


def _validate_schema(tables: list[Table]) -> None:
    """建表前自检：把「MySQL 一定会报的错误」提前变成**能看懂**的报错。

    ⚠ 不做这层检查的话，MySQL 会先建到一半才报错（error 1170 / 1071），
    留下一堆半成品表，还得回头猜是哪张表哪一列。
    """
    problems: list[str] = []
    for t in tables:
        col_types = {c.name: c.mysql_type.upper() for c in t.columns}
        keyed: list[tuple[str, list[str]]] = [(u.name, u.columns) for u in t.uniques]
        for idx in t.indexes:
            m = re.search(r"ON\s+\S+\s*\(([^)]*)\)", idx.sql)
            if not m:
                continue
            cols = [x.strip().strip('"`[]').split()[0] for x in m.group(1).split(",")]
            keyed.append((idx.name, cols))
        for name, cols in keyed:
            for c in cols:
                ct = col_types.get(c, "")
                if ct.startswith(("TEXT", "LONGTEXT", "BLOB")):
                    problems.append(
                        f"{t.name}: 索引/约束 {name} 覆盖了 TEXT 列 {c}"
                        f"（MySQL 不允许 ⇒ 需在 COLUMN_TYPE_OVERRIDES 里改成 VARCHAR）"
                    )
            # 索引键长度上限：utf8mb4 下 VARCHAR(n) 算 4n 字节，总计 ≤ 3072
            total = 0
            for c in cols:
                ct = col_types.get(c, "")
                vm = re.match(r"^VARCHAR\((\d+)\)$", ct)
                total += int(vm.group(1)) * 4 if vm else 8
            if total > 3072:
                problems.append(
                    f"{t.name}: 索引/约束 {name} 的键长度 {total} 字节 > 3072（utf8mb4 上限）"
                )
    if problems:
        raise RuntimeError("schema 自检未通过：\n  - " + "\n  - ".join(problems))


async def _create_schema(conn, tables: list[Table]) -> None:
    _validate_schema(tables)
    for t in tables:
        await conn.execute(text(build_mysql_ddl(t)))
    for t in tables:
        for ddl in build_mysql_indexes(t):
            await conn.execute(text(ddl))
    print(f"[schema] 建表 {len(tables)} 张（含索引）")


async def _copy_table(conn, src: sqlite3.Connection, table: Table, src_cols: list[Column]) -> int:
    """灌一张表（保留显式 id）。

    ⚠ 用 ``executemany``（SQLAlchemy 收到「参数是 dict 列表」时自动走），
    **不是**拼一条巨大的多值 INSERT ——
    2000 行 × 25 列 = 5 万个占位符，一次性塞进一条语句既慢又容易撞上限。
    """
    names = table.column_names
    select_sql = f'SELECT {", ".join(chr(34) + n + chr(34) for n in names)} FROM "{table.name}"'
    insert_sql = (
        f"INSERT INTO `{table.name}` "
        f"({', '.join('`' + n + '`' for n in names)}) "
        f"VALUES ({', '.join(':' + n for n in names)})"
    )
    cur = src.execute(select_sql)
    total = 0
    while True:
        rows = cur.fetchmany(BATCH_SIZE)
        if not rows:
            break
        payload = []
        for raw in rows:
            item = {}
            for col, val in zip(src_cols, raw, strict=True):
                item[col.name] = _conv_value(col, val)
            payload.append(item)
        await conn.execute(text(insert_sql), payload)
        total += len(payload)
    return total


async def _fix_auto_increment(conn, table: Table) -> None:
    if not table.autoincrement:
        return
    pk = table.pk_columns[0]
    res = await conn.execute(text(f"SELECT MAX(`{pk}`) FROM `{table.name}`"))
    max_id = res.scalar()
    nxt = 1 if max_id is None else int(max_id) + 1
    await conn.execute(text(f"ALTER TABLE `{table.name}` AUTO_INCREMENT = {nxt}"))


async def _verify_table(conn, src: sqlite3.Connection, table: Table) -> tuple[int, int, str, str]:
    """逐表比对：行数 + 内容校验和。返回 (源行数, 目标行数, 源哈希, 目标哈希)。"""
    src_cols = table.columns
    names = table.column_names
    order_cols = table.pk_columns or names

    src_hasher = hashlib.sha256()
    src_rows = 0
    cur = src.execute(
        f"SELECT {', '.join(chr(34) + n + chr(34) for n in names)} "
        f'FROM "{table.name}" ORDER BY {", ".join(chr(34) + c + chr(34) for c in order_cols)}'
    )
    while True:
        rows = cur.fetchmany(BATCH_SIZE)
        if not rows:
            break
        src_rows += len(rows)
        _hash_rows([dict(zip(names, r, strict=True)) for r in rows], src_cols, src_hasher)

    # ⚠ 目标侧用**游标分页**（WHERE pk > 上一页最后一个 pk），不用 OFFSET ——
    # OFFSET 60 万行那种深翻页是 O(n²)，大表能把校验拖成分钟级。
    # ⚠ 游标分页要求排序列**唯一** ⇒ 复合主键退回 OFFSET（本项目没有复合主键）。
    dst_hasher = hashlib.sha256()
    dst_rows = 0
    last_key: Any = None
    pk = order_cols[0]
    cursor_ok = len(order_cols) == 1
    offset = 0
    while True:
        where = ""
        params: dict[str, Any] = {}
        if cursor_ok:
            if last_key is not None:
                where = f" WHERE `{pk}` > :last_key"
                params["last_key"] = last_key
        else:
            where = " LIMIT :lim OFFSET :off"
            params["lim"] = BATCH_SIZE
            params["off"] = offset
        res = await conn.execute(
            text(
                f"SELECT {', '.join('`' + n + '`' for n in names)} "
                f"FROM `{table.name}`{where} "
                + (f"ORDER BY `{pk}` LIMIT {BATCH_SIZE}" if cursor_ok else "")
            ),
            params,
        )
        rows = res.all()
        if not rows:
            break
        dst_rows += len(rows)
        offset += len(rows)
        _hash_rows([dict(zip(names, r, strict=True)) for r in rows], src_cols, dst_hasher)
        last_key = rows[-1][0]

    return src_rows, dst_rows, src_hasher.hexdigest(), dst_hasher.hexdigest()


async def run_migration(source: str, url: str, *, apply: bool, verify: bool, drop: bool) -> int:
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    tables = read_sqlite_schema(src)
    print(f"[source] {source}")
    print(f"[source] {len(tables)} 张表")

    if apply or drop:
        engine = _mysql_engine(url)
        async with engine.begin() as conn:
            await _drop_target_tables(conn, tables)
            if apply:
                await _create_schema(conn, tables)
                for t in tables:
                    n = await _copy_table(conn, src, t, t.columns)
                    await _fix_auto_increment(conn, t)
                    print(f"[copy] {t.name:28s} {n:>7d} 行")
        await engine.dispose()
        if not apply:
            src.close()
            return 0

    if verify or apply:
        engine = _mysql_engine(url)
        bad = 0
        async with engine.connect() as conn:
            for t in tables:
                s_rows, d_rows, s_hash, d_hash = await _verify_table(conn, src, t)
                ok = s_rows == d_rows and s_hash == d_hash
                flag = "OK " if ok else "FAIL"
                if not ok:
                    bad += 1
                print(
                    f"[verify] {flag} {t.name:28s} 源={s_rows:>7d} 目标={d_rows:>7d} "
                    f"hash={'同' if s_hash == d_hash else '不同'}"
                )
        await engine.dispose()
        if bad:
            print(f"[verify] ❌ {bad} 张表不一致")
            return 1
        print("[verify] ✅ 全部表一致")

    src.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="SQLite → MySQL 生产库迁移")
    ap.add_argument("--source", default=DEFAULT_SOURCE, help="源 SQLite 文件")
    ap.add_argument("--env-file", default=DEFAULT_ENV_FILE, help="MySQL 连接串所在文件")
    ap.add_argument("--dry-run", action="store_true", help="只打印 DDL 计划")
    ap.add_argument("--apply", action="store_true", help="建表 + 灌数据")
    ap.add_argument("--verify", action="store_true", help="只校验（行数 + 校验和）")
    ap.add_argument("--drop-target", action="store_true", help="删掉 MySQL 侧目标表")
    args = ap.parse_args()

    if args.dry_run:
        src = sqlite3.connect(f"file:{args.source}?mode=ro", uri=True)
        tables = read_sqlite_schema(src)
        for t in tables:
            print(f"===== {t.name} =====")
            print(build_mysql_ddl(t))
            for ddl in build_mysql_indexes(t):
                print(ddl + ";")
        return 0

    if not (args.apply or args.verify or args.drop_target):
        ap.print_help()
        return 2

    url = read_mysql_url(args.env_file)
    return asyncio.run(
        run_migration(
            args.source,
            url,
            apply=args.apply,
            verify=args.verify,
            drop=args.drop_target,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
