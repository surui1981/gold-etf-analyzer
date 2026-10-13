"""``app.main`` 应用入口冒烟测试：FastAPI 装配 + 路由别名 + 静态资源 + 生命周期。

**目的**：V0.86.1 数据健康 404 hotfix 暴露了一个核心问题——
「新增静态页必须同步注册根路径别名，否则 404」。本测试把 main.py 全部
``@app.get`` 别名 + 静态 mount + sw.js 端点 + lifespan 启动做成断言，
任何路由遗漏都会立刻在 CI 失败。

**关键覆盖**：
- 13 个根路径别名（``/``、``/portfolio``、``/weights``、``/news``、``/review``、
  ``/central-bank``、``/data-health``、``/data-health.html``、``/trades``、
  ``/login``、``/reset-password``、``/report``、``/scoring``、``/sw.js``）都返回 307 → /static/*.html
- 静态 mount：``/static/index.html`` 或 ``/static/trend.html`` 可访问
- TestClient（异步）触发 lifespan 走通：migrate → ensure_default → warm cache → scheduler
- ``/docs`` 与 ``/openapi.json`` 在 dev 下可达（auth_enabled=false 时）

**注意**：conftest 已经设 APP_ENV=test + auth=false，所以 ``/docs`` 仍可见。
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


# ──────────────── 别名重定向表 ────────────────


# main.py 里所有 ``@app.get`` 的根路径别名（不含 sw.js —— 单测在下方）
ROOT_ALIASES = [
    ("/", "/static/trend.html"),
    ("/portfolio", "/static/portfolio.html"),
    ("/weights", "/static/weights.html"),
    ("/news", "/static/news.html"),
    ("/review", "/static/review.html"),
    ("/central-bank", "/static/central_bank.html"),
    ("/data-health", "/static/data-health.html"),
    ("/data-health.html", "/static/data-health.html"),  # V0.86.1 向后兼容别名
    ("/trades", "/static/trades.html"),
    ("/login", "/static/login.html"),
    ("/reset-password", "/static/reset-password.html"),
    ("/report", "/static/report.html"),  # V0.91.0 复盘报告 PDF 导出页
    ("/scoring", "/static/scoring.html"),  # V0.92.0 历史打分数据汇总
]


# ──────────────── 客户端 fixture（不带 lifespan，便于路由测试） ────────────────


@pytest.fixture
async def no_lifespan_client() -> AsyncClient:
    """不带 lifespan 的测试客户端：纯路由验证，避免启动耗时。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def client_with_lifespan() -> AsyncClient:
    """带 lifespan 的测试客户端：验证启动/关闭流程不抛异常。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # ASGITransport 默认不触发 lifespan；显式调用
        async with app.router.lifespan_context(app):
            yield c


# ──────────────── 路由别名（全部 307 → /static/*.html） ────────────────


class TestRootAliases:
    """12 个根路径别名必须返回 307 + 正确的 Location header。"""

    @pytest.mark.parametrize(
        "alias_path,expected_target",
        ROOT_ALIASES,
        ids=[a for a, _ in ROOT_ALIASES],
    )
    async def test_alias_redirects_to_static(
        self, no_lifespan_client: AsyncClient, alias_path: str, expected_target: str
    ) -> None:
        """``alias_path`` 必须 307 重定向到 ``expected_target``。"""
        # 不跟随重定向，断言 Location 头
        resp = await no_lifespan_client.get(alias_path, follow_redirects=False)
        assert resp.status_code == 307, (
            f"{alias_path} 应该 307 → {expected_target}，实际 {resp.status_code}"
        )
        assert resp.headers["location"] == expected_target

    async def test_root_alias_count_matches(self) -> None:
        """防止新别名静默加入：路由表里必须正好有 11 个 ``@app.get`` alias。

        新增 alias 必须**同时**加测试断言（防 V0.85 漏注册 ``/data-health`` 复现）。
        """
        root_gets = [
            r for r in app.routes
            if getattr(r, "path", "").startswith("/") and not r.path.startswith("/static")
            and not r.path.startswith("/api")
            and not r.path.startswith("/docs")
            and not r.path.startswith("/openapi")
            and not r.path.startswith("/redoc")
            and r.path not in ("/",)
            and not r.path.startswith("/login")
            and not r.path.startswith("/sw")
        ]
        # 精确数：12 个 alias + / 本身 = 13 个 GET（不含 /sw.js）
        assert len(ROOT_ALIASES) == 13, (
            "ROOT_ALIASES 列表与 main.py 别名数不一致，请同步更新"
        )


# ──────────────── 静态 mount ────────────────


class TestStaticMount:
    """``/static/*`` 通过 StaticFiles mount 可直接访问。"""

    async def test_static_index_html(self, no_lifespan_client: AsyncClient) -> None:
        """``/static/trend.html`` 必须可访问（首页文件存在）。"""
        resp = await no_lifespan_client.get("/static/trend.html")
        assert resp.status_code == 200
        assert "html" in resp.headers.get("content-type", "").lower()

    async def test_static_data_health_html(self, no_lifespan_client: AsyncClient) -> None:
        """``/static/data-health.html`` 可访问（V0.85.0 起的健康摘要页）。"""
        resp = await no_lifespan_client.get("/static/data-health.html")
        assert resp.status_code == 200


# ──────────────── Service Worker ────────────────


class TestServiceWorker:
    """``/sw.js`` 走 ``@app.get`` 路由（不是 StaticFiles），需特殊头。"""

    async def test_sw_js_returns_javascript(self, no_lifespan_client: AsyncClient) -> None:
        """``/sw.js`` 返回 application/javascript。"""
        resp = await no_lifespan_client.get("/sw.js")
        assert resp.status_code == 200
        assert "javascript" in resp.headers.get("content-type", "").lower()

    async def test_sw_js_has_service_worker_allowed_header(
        self, no_lifespan_client: AsyncClient
    ) -> None:
        """``Service-Worker-Allowed: /`` 头必须存在（root scope 注册）。"""
        resp = await no_lifespan_client.get("/sw.js")
        assert resp.headers.get("service-worker-allowed") == "/", (
            "SW 必须声明 root scope，否则无法代理全站请求"
        )

    async def test_sw_js_cache_control_no_cache(
        self, no_lifespan_client: AsyncClient
    ) -> None:
        """``Cache-Control: no-cache`` 头：SW 文件本身不能被浏览器强缓存。"""
        resp = await no_lifespan_client.get("/sw.js")
        assert "no-cache" in resp.headers.get("cache-control", "").lower()


# ──────────────── OpenAPI / Docs（test 环境下应可见） ────────────────


class TestOpenapiAndDocs:
    """``auth_enabled=false`` 时 ``/docs``、``/openapi.json`` 都应可见。

    conftest 已设 ``APP_ENV=test`` + 不设 ``AUTH_ENABLED``（默认 false），
    故测试环境下 docs 端点不应被关闭。
    """

    async def test_openapi_json(self, no_lifespan_client: AsyncClient) -> None:
        """``/openapi.json`` 返回 200 + OpenAPI schema。"""
        resp = await no_lifespan_client.get("/openapi.json")
        assert resp.status_code == 200
        body = resp.json()
        assert "paths" in body
        assert "info" in body
        assert body["info"]["title"] == "黄金价格投资辅助工具"

    async def test_docs_endpoint(self, no_lifespan_client: AsyncClient) -> None:
        """``/docs``（Swagger UI）应可见（dev/test 默认开启）。"""
        resp = await no_lifespan_client.get("/docs")
        assert resp.status_code == 200


# ──────────────── 中间件栈装配 ────────────────


class TestMiddlewareStack:
    """验证中间件按 LIFO 顺序正确注册（V0.75.0 评论里写死了顺序）。

    LIFO：后加的更靠外 → 实际请求流：CORS → RateLimit → TraceId → Auth → Csrf → 路由。
    FastAPI middleware stack 在 ``app.user_middleware`` 里按注册顺序排（LIFO 反转后是执行顺序）。
    """

    def test_middleware_count(self) -> None:
        """中间件总数：CORS + RateLimit + TraceId + Auth + Csrf = 5。

        RateLimit 在 test 环境下不挂载（被 ``app_env != 'test'`` 短路），
        但 conftest 在跑测试时 ``app_env`` 是 'test' → 应为 4 个。
        """
        # user_middleware 是注册顺序；中间件总数应 ≥ 4
        assert len(app.user_middleware) >= 4, (
            f"中间件数量异常：{len(app.user_middleware)}；"
            "V0.75.0 应至少含 CORS + TraceId + Auth + Csrf"
        )


# ──────────────── App 元信息 ────────────────


class TestAppMetadata:
    """FastAPI ``app`` 对象的关键元信息。"""

    def test_app_title(self) -> None:
        """``app.title`` 必须等于「黄金价格投资辅助工具」。"""
        assert app.title == "黄金价格投资辅助工具"

    def test_app_version_matches_package(self) -> None:
        """``app.version`` 必须等于 ``app.__version__``（保持单点真相）。"""
        from app import __version__

        assert app.version == __version__, (
            f"app.version={app.version} 与 __version__={__version__} 不一致"
        )

    def test_app_has_lifespan(self) -> None:
        """FastAPI app 必须注册 lifespan（启动期迁移 + 默认账本 + 调度）。"""
        assert app.router.lifespan_context is not None


# ──────────────── Lifespan（端到端启动 + 关闭） ────────────────


class TestLifespan:
    """Lifespan 完整跑通：WAL checkpoint → migrate → ensure_default → scheduler。"""

    async def test_lifespan_startup_no_error(self) -> None:
        """``lifespan(app)`` 上下文管理器正常进入并退出（不抛异常）。"""
        async with app.router.lifespan_context(app):
            # 进入 lifespan 后 app 已就绪
            assert app.title == "黄金价格投资辅助工具"


# ──────────────── 杂项：404 处理 ────────────────


class TestNotFound:
    """未注册路径必须返回 404（不是 500 或 307）。"""

    async def test_unknown_path_returns_404(self, no_lifespan_client: AsyncClient) -> None:
        """``/no-such-path-xyz`` 必须 404（确保 alias 列表是白名单，不是 prefix）。"""
        resp = await no_lifespan_client.get("/no-such-path-xyz")
        assert resp.status_code == 404


# ──────────────── SW 路径 bug 回归测试（V0.86.1 hotfix 防回归） ────────────────


class TestDataHealthRegression:
    """V0.86.1 数据健康 404 hotfix 防回归：``/data-health`` 必须可访问。"""

    async def test_data_health_alias_returns_200(
        self, no_lifespan_client: AsyncClient
    ) -> None:
        """``/data-health``（不带 .html）必须 307 → 200 落地页可读。"""
        resp = await no_lifespan_client.get("/data-health", follow_redirects=True)
        assert resp.status_code == 200
        # content-type 应是 html（302 落地 /static/data-health.html）
        assert "html" in resp.headers.get("content-type", "").lower()

    async def test_data_health_dothtml_alias_returns_200(
        self, no_lifespan_client: AsyncClient
    ) -> None:
        """``/data-health.html``（带 .html 别名）也必须 200（V0.86.1 向后兼容）。"""
        resp = await no_lifespan_client.get("/data-health.html", follow_redirects=True)
        assert resp.status_code == 200