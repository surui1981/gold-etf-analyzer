"""models 包：SQLAlchemy ORM 模型。

导入全部模型模块以注册到 Base.metadata（供 create_all / Alembic autogenerate 使用）。
"""

from app.models import (  # noqa: F401
    account,
    ai_chat,
    analysis,
    central_bank,
    daily_macro_factor,
    gold_inventory,  # V0.115.0 COMEX 黄金库存日频（首页「贵金属走势」）
    news,
    position,
    push,
    reports,  # V0.111.0 报告存档（HTML 上传 + 元数据登记表）
    review,
    scoring_wide,
    settings,
    snapshot,
    telemetry,
    user,
)
