"""V0.72.0 P3-b：Web Push 订阅端点的 Pydantic schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class PushKeys(BaseModel):
    """WebCrypto PushSubscription 密钥对。"""

    p256dh: str = Field(..., min_length=10)
    auth: str = Field(..., min_length=10)


class PushSubscriptionIn(BaseModel):
    """前端 navigator.serviceWorker.pushManager.subscribe() 的 JSON 输出。"""

    endpoint: str = Field(..., min_length=10)
    keys: PushKeys
    # 浏览器类型（用于后续按设备过滤推送）；可选
    user_agent: str | None = None


class PushSubscriptionOut(BaseModel):
    """订阅记录返回。"""

    id: int
    endpoint: str
    user_agent: str | None
    created_at: datetime
    archived_at: datetime | None = None


class VapidPublicKeyOut(BaseModel):
    """公钥响应（前端 subscribe 时使用）。"""

    key: str


class PushTestResult(BaseModel):
    """测试推送发送结果。"""

    sent: int
    failed: int
    total: int
    message: str


# type alias for the channel literal
PushChannel = Literal["webpush"]
