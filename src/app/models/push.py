"""V0.72.0 P3-b：Web Push 订阅表（push_subscriptions）。

每条记录代表一个浏览器/设备的 push 订阅：
- 同一 endpoint 多次订阅视为同一订阅（id UPSERT）。
- 推送失败 410 Gone 时自动 archive（archived_at != NULL）；月度清理脚本可删除 archived > 30d。
- 当前无 user_id（V0.72.0 单用户模型）；V0.75+ 多用户时加 user_id 列 + 扩唯一键。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PushSubscription(Base):
    """Web Push 订阅记录。"""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    endpoint: Mapped[str] = mapped_column(String(512), comment="FCM/Mozilla 推送端点")
    p256dh: Mapped[str] = mapped_column(Text, comment="椭圆曲线公钥（base64url）")
    auth: Mapped[str] = mapped_column(Text, comment="认证密钥（base64url）")
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    # ⚠ V0.80.0 数据隔离（#159 第 2 批）：推送订阅归属用户。
    # 移除了 endpoint 的 unique=True —— 改为 (user_id, endpoint) 复合唯一
    # （迁移 a3f2c1d5e6f7 已建 ix_push_subscriptions_user_endpoint）。
    # 理由：同一台设备可能登录不同用户，端点标识本身不足以定位订阅归属。
    user_id: Mapped[int] = mapped_column(
        Integer, default=1, index=True, comment="归属用户 users.id（V0.75.2 加列）"
    )

    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="410 Gone 时设此字段；查询时 WHERE archived_at IS NULL",
    )

    __table_args__ = (Index("ix_push_subscriptions_archived_at", "archived_at"),)
