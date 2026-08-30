"""ORM 基类：所有模型统一继承 Base。"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 声明式基类（无需手动维护 metadata）。"""
