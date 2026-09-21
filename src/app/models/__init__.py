"""models 包：SQLAlchemy ORM 模型。

导入全部模型模块以注册到 Base.metadata（供 create_all / Alembic autogenerate 使用）。
"""

from app.models import (  # noqa: F401
    account,
    analysis,
    central_bank,
    news,
    position,
    push,
    review,
    settings,
    snapshot,
    telemetry,
)
