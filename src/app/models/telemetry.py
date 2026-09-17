"""前端埋点表（V0.68.0 客户端埋点底座）。

设计要点
--------
- **append-only** —— 不更新、不删除（除按 retention 清理外）；前端只 INSERT，由 ``sendBeacon``
  批量上报（默认 4 秒或 20 条 flush）；服务端仅写、不解析业务字段
- **payload 字段为 JSON 文本** —— 业务侧自由扩展，``event_type`` 用于派生指标聚合
- **轻量索引** —— ``(event_type, created_at)`` 复合索引支撑派生 SQL；``created_at`` 单列索引
  支撑 retention 清理；不建唯一约束（允许同时间重复事件）
- **trace_id 可选** —— 由 V0.67.0 中间件在 HTTP 层注入，本表不依赖；
  主要用于「同一会话内」关联浏览 + 操作

事件类型（V0.68.0 第一版）：
- ``page_view``：页面访问（每次首屏 + 软刷新）
- ``action_click``：按钮 / 链接点击（带 ``target``）
- ``range_change``：时间区间切换（趋势 / 收益曲线）
- ``palette_open`` / ``palette_query`` / ``palette_select``：命令面板三阶段
- ``nav_drawer_open`` / ``nav_drawer_select``：汉堡抽屉两阶段
- ``error_caught``：前端捕获的异常
"""

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TelemetryEvent(Base):
    """前端埋点事件（append-only）。"""

    __tablename__ = "telemetry_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 事件类型（白名单由前端常量保证；服务端不强制枚举以便扩展）
    event_type: Mapped[str] = mapped_column(String(32), comment="page_view / action_click / ...")

    # 事件源页（路径，不含域名；例 /static/trend.html）
    page: Mapped[str] = mapped_column(String(128), comment="事件源页面路径")

    # 业务负载（JSON 字符串，自由扩展；服务端只透传不解析）
    payload: Mapped[str] = mapped_column(Text, default="{}", comment="JSON 负载")

    # 用户识别（V0.75.0 多用户前恒为 "1"；预留字段）
    user_id: Mapped[str] = mapped_column(String(32), default="1", index=True)

    # 客户端会话 ID（前端每次会话生成 UUIDv4 hex 持久化 localStorage）
    session_id: Mapped[str] = mapped_column(String(32), default="-", index=True)

    # HTTP 层 trace_id（V0.67.0 中间件注入；同会话关联用）
    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


# 复合索引：按事件类型 + 时间范围查询（派生指标聚合最常用）
Index(
    "ix_telemetry_events_type_created",
    TelemetryEvent.event_type,
    TelemetryEvent.created_at,
)


__all__ = ["TelemetryEvent"]
