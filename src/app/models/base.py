"""ORM 基类：所有模型统一继承 Base。"""

from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 声明式基类（无需手动维护 metadata）。"""


class SourceId(TypeDecorator):
    """源站新闻 id 列类型：**永远**以文本绑定。

    为什么不能只用 ``String(32)``
    ----------------------------
    ``String(32)`` 只声明了列类型，**不管绑什么值**。而绑定发生在 Python 侧
    （``sqlite3`` 把 Python int 绑成 INTEGER），金十 id ≈2.02e19 超出 SQLite
    int64 上限（9.22e18）**2.2 倍**，于是直接抛::

        OverflowError: Python int too large to convert to SQLite INTEGER

    列的 TEXT affinity 救不了 —— 转换要等值**已经进了 SQLite**，而它压根没
    进来。所以必须在 ``process_bind_param`` 里转字符串。

    ⚠ 顺带一提，这也解释了为什么 BigInteger 不够：BigInteger 只解决 int32
    溢出（4.2e9），而这里是 int64 溢出，差着量级。

    读出来是字符串。调用方若要比对，用 ``str(...)`` 归一；API 层由
    ``schemas/news_feed.js_safe_id`` 决定输出数字还是字符串。
    """

    impl = String(32)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return str(value)
