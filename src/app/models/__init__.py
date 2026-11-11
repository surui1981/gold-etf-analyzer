"""models 包：SQLAlchemy ORM 模型。

导入全部模型模块以注册到 Base.metadata（供 create_all / Alembic autogenerate 使用）。
"""

from app.models import (  # noqa: F401
    account,
    ai_chat,
    analysis,
    central_bank,
    daily_macro_factor,
    daily_money_flow_factor,  # V0.126.0 资金流面因子（此前漏注册 ⇒ metadata 只有 20 张表）
    gold_inventory,  # V0.115.0 COMEX 黄金库存日频（首页「贵金属走势」）
    news,
    news_feed,  # V0.126.0 今日要闻（此前漏注册）
    position,
    push,
    reports,  # V0.111.0 报告存档（HTML 上传 + 元数据登记表）
    review,
    scoring_wide,
    settings,
    snapshot,
    telemetry,
    user,
    user_news_favorite,  # V0.126.0 我的收藏（此前漏注册）
)
