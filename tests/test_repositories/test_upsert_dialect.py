"""方言无关 upsert 的 MySQL/SQLite 语义差异回归测试（V0.126.0）

## 为什么要有这个测试

生产库从 SQLite 迁到 MySQL 时踩到一个**只在 MySQL 上炸**的坑：

``news_feed_items`` 的 payload **不带** ``fetched_at`` / ``source``（靠列的
``server_default`` 补），而 ``update_columns`` 里却有它们。

- **SQLite** 的 ``excluded.fetched_at`` **取得到**那个默认值（SQLite 插入时
  就把默认值填进 ``excluded`` 了）⇒ 一切正常；
- **MySQL** 的行别名 ``new.fetched_at`` **只暴露 INSERT 列清单里出现过的列**
  ⇒ 直接报 ``error 1054 Unknown column 'new.fetched_at' in 'field list'``
  ⇒ **整个新闻流 upsert 失败**（而且只在跑那行 SQL 时才炸，不会在启动时炸）。

修法在 :func:`app.repositories.upsert._mysql_update_expressions`：
对「payload 里没有、但要更新」的列，改用该列的**隐式默认值**表达式。

## 本测试的判据

**只看编译出来的 SQL**，不连 MySQL ⇒ 纯离线、秒级、不依赖外部服务。
⇒ 也因此可以在 CI 上跑（CI 只有 SQLite）。

⚠ **反向验证**：把 :func:`_mysql_update_expressions` 临时改回
``{col: stmt.inserted[col] for col in update_columns}``，
本文件里的 ``test_mysql_upsert_..._missing_payload_column`` 必须**变红**
（编译结果里会重新出现 ``new.fetched_at``）。
"""

from __future__ import annotations

import pytest
from sqlalchemy.dialects import sqlite
from sqlalchemy.dialects.mysql import asyncmy

from app.models.news_feed import NewsFeedItem
from app.repositories.upsert import build_upsert


class _FakeBind:
    """只提供 ``dialect`` 的假 bind —— ``session_dialect_name`` 只读这一项。"""

    def __init__(self, dialect):
        self.dialect = dialect


class _FakeSession:
    """只提供 ``get_bind()`` 的假 session（``build_upsert`` 的方言判定只用它）。"""

    def __init__(self, dialect):
        self._bind = _FakeBind(dialect)

    def get_bind(self):
        return self._bind


def _mysql_session():
    """构造一个**与生产同款**的 MySQL 方言（离线，不连库）。

    ⚠ 生产跑的是 **asyncmy** 方言 + MySQL 8.0.46 ⇒ SQLAlchemy 把 upsert 编译成
    **行别名式** ``... AS new ON DUPLICATE KEY UPDATE col = new.col``
    （8.0.20 起 ``VALUES(col)`` 官方标为 deprecated）。
    ⇒ 判据必须按别名式来写，否则测的不是线上真实形态。

    ⚠ ``_requires_alias_for_on_duplicate_key`` 是在 ``Dialect.initialize()``
    （真连库时）里才设的；离线的 ``dialect()`` **不会**调 initialize ⇒
    这里手工调 ``_initialize_mysql()`` 复刻那一步
    （它只读 ``server_version_info``，不需要连接）。
    ⚠ 若将来 SQLAlchemy 改了私有 API，这里会**直接报错**而不是静默测错形态。
    """
    dialect = asyncmy.dialect()
    dialect.server_version_info = (8, 0, 46, 24, 4, 4)  # 生产实测版本
    dialect._initialize_mysql(None)
    assert dialect._requires_alias_for_on_duplicate_key is True
    return _FakeSession(dialect)


# ⚠ 复刻真实的 wallstcn payload：**没有** fetched_at（列的 server_default 补），
#   **有** source（wallstcn 源显式写；readhub 源不写，走 server_default）。
_PAYLOAD_WITHOUT_FETCHED_AT = [
    {
        "external_id": "3198109",
        "title": "新易盛：预计未来毛利率水平可保持相对稳定",
        "summary": "公司在互动平台表示…",
        "url": "https://wallstreetcn.com/livenews/3198109",
        "mobile_url": None,
        "site_name": "华尔街见闻",
        "language": "zh-cn",
        "author_name": "石惠",
        "publish_date": "2026-01-01 00:00:00",
        "source": "wallstcn",
        "category": "财经",
    }
]

_UPDATE_COLUMNS = [
    "title",
    "summary",
    "url",
    "mobile_url",
    "site_name",
    "language",
    "author_name",
    "publish_date",
    "fetched_at",
    "source",
    "category",
]


def test_mysql_dialect_uses_row_alias_form():
    """钉住**生产的 SQL 形态**：行别名式 ``AS new ... = new.<col>``。

    ⚠ 这条不是测业务逻辑，是测「判据本身测的是线上真实形态」：
    若 SQLAlchemy 将来退回旧的 ``VALUES(col)`` 写法，本文件其余断言会
    **假绿**（因为 ``new.fetched_at`` 那条根本不会出现）⇒ 必须先把形态钉死。
    """
    stmt = build_upsert(
        _mysql_session(),
        NewsFeedItem.__table__,
        _PAYLOAD_WITHOUT_FETCHED_AT,
        index_elements=["source", "external_id"],
        update_columns=_UPDATE_COLUMNS,
    )
    sql = str(stmt.compile(dialect=_mysql_session().get_bind().dialect))
    assert "AS new" in sql, f"不是行别名式写法（判据会假绿）：\n{sql}"
    assert "VALUES(title)" not in sql, f"退回旧写法了：\n{sql}"


def test_mysql_upsert_missing_payload_column_uses_default_not_alias():
    """payload 缺 fetched_at ⇒ MySQL 分支**不得**引用 ``new.fetched_at``。

    反向验证：把 ``_mysql_update_expressions`` 改回直接用 ``stmt.inserted[col]``
    ⇒ 编译结果里会重新出现 ``new.fetched_at`` ⇒ 本用例**变红**。
    """
    stmt = build_upsert(
        _mysql_session(),
        NewsFeedItem.__table__,
        _PAYLOAD_WITHOUT_FETCHED_AT,
        index_elements=["source", "external_id"],
        update_columns=_UPDATE_COLUMNS,
    )
    sql = str(stmt.compile(dialect=_mysql_session().get_bind().dialect))

    # ⚠ 关键断言：MySQL 的行别名 new **只暴露 INSERT 列清单里的列**
    assert "new.fetched_at" not in sql, f"引用了不存在的行别名列：\n{sql}"
    # 改用该列的隐式默认值（server_default=func.now() ⇒ CURRENT_TIMESTAMP）
    assert "fetched_at = CURRENT_TIMESTAMP" in sql or "fetched_at = now()" in sql, (
        f"没有回退到列默认值：\n{sql}"
    )


def test_mysql_upsert_present_payload_column_uses_alias():
    """payload 里有的列**照旧**用行别名 `new.<col>`（不能被默认值兜底覆盖）。"""
    payload = [
        {
            **_PAYLOAD_WITHOUT_FETCHED_AT[0],
            "fetched_at": "2026-01-01 00:00:00",
        }
    ]
    stmt = build_upsert(
        _mysql_session(),
        NewsFeedItem.__table__,
        payload,
        index_elements=["source", "external_id"],
        update_columns=_UPDATE_COLUMNS,
    )
    sql = str(stmt.compile(dialect=_mysql_session().get_bind().dialect))
    assert "new.fetched_at" in sql, f"payload 里有的列应走行别名：\n{sql}"


def test_sqlite_upsert_always_uses_excluded():
    """SQLite 分支不受影响：一律用 ``excluded.<col>``。

    ⚠ SQLite 的 ``excluded`` **包含**被省略列的默认值 ⇒ 不需要（也不能）做
    MySQL 那样的默认值兜底。
    """
    stmt = build_upsert(
        _FakeSession(sqlite.dialect()),
        NewsFeedItem.__table__,
        _PAYLOAD_WITHOUT_FETCHED_AT,
        index_elements=["source", "external_id"],
        update_columns=_UPDATE_COLUMNS,
    )
    sql = str(stmt.compile(dialect=sqlite.dialect()))
    assert "excluded.fetched_at" in sql, f"SQLite 分支应一律用 excluded：\n{sql}"
    assert "new." not in sql, f"SQLite 分支不该出现 MySQL 的行别名：\n{sql}"


def test_mysql_upsert_rejects_mismatched_unique_key():
    """⚠ 不变量①：唯一键对不上 ⇒ 直接抛错（不静默写出重复行）。"""
    with pytest.raises(RuntimeError, match="upsert 目标唯一键不存在"):
        build_upsert(
            _mysql_session(),
            NewsFeedItem.__table__,
            _PAYLOAD_WITHOUT_FETCHED_AT,
            index_elements=["external_id"],  # 少一列 ⇒ 表上没这个唯一键
            update_columns=_UPDATE_COLUMNS,
        )
