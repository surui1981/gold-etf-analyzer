"""V0.72.0 P3-b：per-IP 滑动窗口限速中间件。

设计要点
--------
- **滑动窗口（sliding window）**：60s 内最多 ``rate_limit_per_min`` 次；超限返 429 + ``Retry-After``。
- **per-IP 隔离**：用 ``X-Forwarded-For`` 头（nginx 反代场景）取首个 IP；无则取 ``scope['client']``。
- **in-memory dict**：简单 ``defaultdict(list)``；单进程适用（V0.72.0 阶段无多副本）。
  后续多副本部署需换 Redis 共享状态。
- **env 控制开关** ``RATE_LIMIT_PER_MIN=0`` 禁用（dev 友好）。
- **不过滤 OPTIONS**：CORS 预检频繁，不应被限速。
- **跳过 /static/**：静态资产（HTML/JS/CSS/图片）走 FastAPI fallback 时也不计数。
  - 理由：浏览器一次页面加载会拉 HTML + 5+ JS + 2+ CSS + favicon = 10+ 请求，
    把静态当 API 一起限会让正常用户频繁看到"加载失败"提示（V0.83.2 实测）。
  - env ``RATE_LIMIT_SKIP_STATIC=false`` 可关闭（极端场景下需要）。
  - 仅 API 路径（/api/、/auth/、其他业务路由）进入滑动窗口。

测试
----
mock 客户端 IP + 时间切片，验证窗口边界 + 超限返 429 + Retry-After 头。
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

WINDOW_SECONDS = 60.0


class RateLimitMiddleware(BaseHTTPMiddleware):
    """per-IP 滑动窗口限速（默认 600 req/min，env ``RATE_LIMIT_PER_MIN=0`` 禁用）。

    V0.83.3 升级：默认 120 → 600，跳过 /static/ 路径。
    - 实测：单页面加载 ~10 请求 + freshness.js 60s 轮询，120/min 频繁打满，
      触发"数据时效加载失败"误报。
    - /static/* 是浏览器自动拉的展示资源（非 API 滥用），与限流目标无关。
    """

    def __init__(self, app, per_min: int, skip_static: bool = True) -> None:
        super().__init__(app)
        self._per_min = per_min
        self._skip_static = skip_static
        # IP -> deque[float]（每次请求的 epoch 秒）
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        # 禁用 / OPTIONS / 静态路径 全部 bypass
        if self._per_min <= 0 or request.method == "OPTIONS":
            return await call_next(request)
        if self._skip_static and request.url.path.startswith("/static/"):
            return await call_next(request)

        ip = self._client_ip(request)
        now = time.time()
        hits = self._hits[ip]

        # 清理窗口外的旧记录（从左端 pop 直到最新命中在 60s 内）
        while hits and now - hits[0] > WINDOW_SECONDS:
            hits.popleft()

        if len(hits) >= self._per_min:
            retry_after = int(WINDOW_SECONDS - (now - hits[0]))
            return JSONResponse(
                status_code=429,
                content={"detail": "rate limit exceeded", "retry_after": retry_after},
                headers={"Retry-After": str(retry_after)},
            )

        hits.append(now)
        return await call_next(request)

    @staticmethod
    def _client_ip(request: Request) -> str:
        """优先取 X-Forwarded-For 头首个 IP（Nginx 反代场景），否则取 ``request.client.host``。"""
        xff = request.headers.get("x-forwarded-for")
        if xff:
            # 多级代理取第一个；逗号分隔
            return xff.split(",")[0].strip()
        if request.client is not None:
            return request.client.host or "unknown"
        return "unknown"
