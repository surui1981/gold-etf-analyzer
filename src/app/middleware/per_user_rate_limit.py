"""Per-user 限速中间件（V0.97.0 · LLM 烧钱护栏）

叠加在 per-IP 限速（``RateLimitMiddleware``）之上，**只作用于** ``/api/v1/ai/*``
路径。两道护栏：
- **滑动窗口**：每用户 60s 内最多 N 次请求（默认 30）
- **每日 token 配额**：每用户每日累计 token 用量上限（默认 100k）

为什么不单独靠 per-IP
--------------------
家庭网 / NAT 多设备共享 IP，单 IP 限速无法区分用户；LLM 又烧钱（$3/1M input
+ $15/1M output），必须 per-user。

状态：in-memory（与 per-IP 同模式，单进程；多副本需换 Redis，V0.98+ 候选）
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from datetime import date
from typing import ClassVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class PerUserRateLimitMiddleware(BaseHTTPMiddleware):
    """``/api/v1/ai/*`` 路径专用 per-user 限速。"""

    PATH_RE = __import__("re").compile(r"^/api/v1/ai/")
    _BUCKETS: ClassVar[dict[int, deque[float]]] = defaultdict(deque)
    _TOKEN_USAGE: ClassVar[dict[tuple[int, date], int]] = defaultdict(int)
    _LOCK = threading.Lock()

    def __init__(self, app, *, per_min: int = 30, daily_quota: int = 100_000):
        super().__init__(app)
        self._per_min = per_min
        self._daily_quota = daily_quota

    async def dispatch(self, request: Request, call_next):
        if not self.PATH_RE.match(request.url.path):
            return await call_next(request)

        user = getattr(request.state, "user", None)
        if user is None:
            # 端点层 require_user 兜底；这里放过
            return await call_next(request)

        now = time.monotonic()
        today = date.today()
        with self._LOCK:
            bucket = self._BUCKETS[user.id]
            cutoff = now - 60
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self._per_min:
                return JSONResponse(
                    {"detail": "rate_limited", "code": "ai_per_user_rpm"},
                    status_code=429,
                    headers={"Retry-After": "60"},
                )
            usage = self._TOKEN_USAGE[(user.id, today)]
            if usage >= self._daily_quota:
                return JSONResponse(
                    {"detail": "quota_exceeded", "code": "ai_daily_quota"},
                    status_code=429,
                    headers={"X-Quota-Reset": today.isoformat()},
                )
            bucket.append(now)
        return await call_next(request)
