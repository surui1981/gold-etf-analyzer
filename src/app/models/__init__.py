"""models 包：SQLAlchemy ORM 模型。

导入全部模型模块以注册到 Base.metadata（供 create_all / Alembic autogenerate 使用）。
"""

from app.models import analysis, news, position, settings, snapshot  # noqa: F401,E402
