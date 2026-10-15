#!/usr/bin/env python
"""校验 FastAPI 路由 + 静态资源可达（HTTP 路由门禁 · V0.88.0）。

背景
----
V0.86.1 数据健康 404 hotfix 暴露了一个核心问题——「新增静态页必须同步注册根路径别名」。
V0.87.0 用 FastAPI TestClient 在 ``tests/test_dependencies/test_main_app.py`` 已覆盖
11 个 alias 307 重定向，但 **TestClient 走 ASGI 内存通道，不验证「真实 HTTP 服务器 +
curl GET → 落地页可达」**。本脚本补上集成层验证：起 in-process uvicorn → urllib GET
每条路由 → 与期望 HTTP status 比对。

判定口径
--------
- 11 个页面 alias → ``307`` 重定向（``RedirectResponse``）
- ``/sw.js``        → ``200``（``FileResponse``）
- ``/docs``         → ``200``（test 环境 auth=false，默认开启 Swagger）
- ``/static/...``   → ``200``（sample：``/static/trend.html``，验证 StaticFiles 工作）

防回归
------
1. ``tests/test_dependencies/test_main_app.py`` 同步维护 ``ROOT_ALIASES`` 列表
   （TestClient 层）+ 本脚本同步维护 ``EXPECTED_STATUS``（HTTP 层）。
   任何漏注册 / 误改路径都会在两层门禁之一被截获。
2. CI 接入：在 uvicorn 步骤后跑 ``python scripts/check_routes.py --list`` 自检。

可测试性
--------
- ``discover_routes(app)`` 拿 ``app.routes`` 反射，单独可测。
- ``check_routes(*, routes, fetch, base, expected)`` 接受注入 fetch，测试可传
  ``FakeFetch`` mock 各 status 码。

用法
----
    python scripts/check_routes.py              # 起 in-process uvicorn 自测
    python scripts/check_routes.py --list       # 打印发现的路由
    python scripts/check_routes.py --base http://127.0.0.1:8889   # 验证外部 server
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Callable

# ──────────────── 期望状态表（事实真相；与 test_main_app.py ROOT_ALIASES 同步） ────────────────


# 13 个页面 alias（与 src/app/main.py 的 @app.get 路径一一对应；
# V0.91.0 新增 /report —— 复盘报告 PDF 导出页；V0.92.0 新增 /scoring —— 打分汇总）
EXPECTED_ALIAS_PATHS: list[str] = [
    "/",
    "/portfolio",
    "/weights",
    "/news",
    "/review",
    "/central-bank",
    "/data-health",
    "/data-health.html",
    "/trades",
    "/login",
    "/reset-password",
    "/report",
    "/scoring",
    "/ask",
]

# 期望 status 表：alias → 307，特殊端点 → 各自 status
EXPECTED_STATUS: dict[str, int] = {
    **{p: 307 for p in EXPECTED_ALIAS_PATHS},
    "/sw.js": 200,
    "/docs": 200,  # dev/test 模式默认开启
    "/static/trend.html": 200,  # StaticFiles mount 健康度抽样
}

# 用于发现端点：扫描 src/app/main.py 的所有 @app.get 等路由
PROJECT_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


__all__ = ["discover_routes", "check_routes", "EXPECTED_STATUS", "main"]


# ──────────────── 路由发现（反射 FastAPI app） ────────────────


def discover_routes(app) -> list[str]:
    """反射 ``app.routes``：返回所有 APIRoute 路径（不含 Mount 与特殊 Starlette 路由）。

    Args:
        app: FastAPI 实例

    Returns:
        路由路径列表（含 ``/``、``/portfolio``、``/sw.js`` 等），不含 ``/static``
        mount 与 ``/openapi.json`` 等 Starlette 自动生成。
    """
    routes: list[str] = []
    for r in app.routes:
        # 跳过 Mount（StaticFiles mount 是 /static/，不进路由表）
        cls_name = type(r).__name__
        if cls_name == "Mount":
            continue
        # APIRoute 有 path + path_params 等
        if cls_name == "APIRoute":
            path = getattr(r, "path", None)
            if path is not None and path != "/openapi.json":
                routes.append(path)
    return routes


# ──────────────── HTTP 验证（可注入 fetch） ────────────────


def _default_fetch(url: str, *, timeout: float = 5.0) -> int:
    """urllib GET 拿 status code；不跟随 redirect，直接读第一跳的 status。"""
    req = urllib.request.Request(url, method="GET")
    try:
        # 不 follow redirect；urllib 默认会跟 → 这里用 opener 拿首个响应
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):  # noqa: ANN001,ANN002,ANN003
                return None

        opener = urllib.request.build_opener(NoRedirect)
        with opener.open(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        # 4xx/5xx 也算 HTTP 响应（不算失败）
        return exc.code
    except (urllib.error.URLError, ConnectionError, OSError):
        return 0  # 0 表示连接失败


def check_routes(
    *,
    routes: list[str],
    fetch: Callable[[str], int],
    base: str,
    expected: dict[str, int] | None = None,
) -> list[str]:
    """双向检查：① expected 表里每条都返期望 status；② routes 必须都在 expected 里。

    Args:
        routes: ``discover_routes()`` 反射出的 FastAPI 路由路径列表
        fetch: 接受 URL 串返回 status code 的函数（测试可注入 mock）
        base: 基地址（含 scheme + host + port，无尾斜杠）
        expected: 期望 status 映射；缺省用 ``EXPECTED_STATUS``

    Returns:
        失败描述列表；空 list = 全过

    双向验证逻辑：
    - ``routes - expected.keys``：新增路由未登记（漂移信号）
    - ``expected.keys ∩ routes``：每条都验 status 是否匹配期望
    - ``expected.keys - routes``：如 ``/static/trend.html``（mount 不在 routes 里），
      仍按期望表验 HTTP status（独立抽样 StaticFiles 健康度）
    """
    expected = expected if expected is not None else EXPECTED_STATUS
    base = base.rstrip("/")
    problems: list[str] = []

    routes_set = set(routes)
    expected_set = set(expected.keys())

    # ① routes ⊆ expected：FastAPI 路由必须登记（漂移信号）
    for path in sorted(routes_set - expected_set):
        problems.append(
            f"{path}: 在 FastAPI 路由表里但未登记在 EXPECTED_STATUS"
            f"（可能新增了 alias，请同步本脚本 EXPECTED_ALIAS_PATHS）"
        )

    # ② expected ∩ routes：验证每条 status
    for path in sorted(routes_set & expected_set):
        url = f"{base}{path}"
        actual = fetch(url)
        want = expected[path]
        if actual == 0:
            problems.append(f"{path}: 连接失败（{url}）")
        elif actual != want:
            problems.append(f"{path}: 期望 status {want}，实际 {actual}")

    # ③ expected - routes：如 /static/trend.html 等 mount 路径，按期望表独立验证
    for path in sorted(expected_set - routes_set):
        url = f"{base}{path}"
        actual = fetch(url)
        want = expected[path]
        if actual == 0:
            problems.append(f"{path}: 连接失败（{url}）")
        elif actual != want:
            problems.append(f"{path}: 期望 status {want}，实际 {actual}")

    return problems


# ──────────────── in-process uvicorn ────────────────


def _find_free_port() -> int:
    """找一个空闲端口（避免与现有服务冲突）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_in_process_server(app, port: int) -> threading.Thread:
    """起 uvicorn.Server 在子线程（daemon=True，脚本退出即随之结束）。"""
    import uvicorn

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="error",
        access_log=False,
    )
    server = uvicorn.Server(config)

    def _run() -> None:
        server.run()

    thread = threading.Thread(target=_run, daemon=True, name="check-routes-uvicorn")
    thread.start()

    # 等 server.started 最多 5 秒
    deadline = time.time() + 5.0
    while time.time() < deadline and not server.started:
        time.sleep(0.05)
    if not server.started:
        server.should_exit = True
        raise RuntimeError("uvicorn 启动超时（5s 内未就绪）")
    return thread


# ──────────────── CLI 入口 ────────────────


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="HTTP 路由可达性门禁（V0.88.0）")
    parser.add_argument("--list", action="store_true", help="只打印发现的路由")
    parser.add_argument(
        "--base",
        default=None,
        help="外部 server 地址（如 http://127.0.0.1:8889）；不传则起 in-process uvicorn",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="in-process uvicorn 端口（默认自动选空闲）",
    )
    args = parser.parse_args(argv[1:])

    # 反射 app 拿列表
    try:
        from app.main import app as fastapi_app
    except Exception as exc:
        print(f"[FAIL] 导入 app.main 失败：{exc}", file=sys.stderr)
        return 1

    routes = discover_routes(fastapi_app)

    if args.list:
        print(f"应用路由 {len(routes)} 条（反射 FastAPI app.routes）：")
        for r in sorted(routes):
            print(f"    {r}")
        print(f"\n期望 status 表 {len(EXPECTED_STATUS)} 条：")
        for path, status in sorted(EXPECTED_STATUS.items()):
            print(f"    {status}  {path}")
        return 0

    # 决定 base URL
    if args.base:
        base = args.base.rstrip("/")
        # 外部 server 不需要管理生命周期
    else:
        port = args.port if args.port else _find_free_port()
        base = f"http://127.0.0.1:{port}"
        try:
            _start_in_process_server(fastapi_app, port)
        except Exception as exc:
            print(f"[FAIL] 起 in-process uvicorn 失败：{exc}", file=sys.stderr)
            return 1

    # 验证
    problems = check_routes(routes=routes, fetch=_default_fetch, base=base)

    if problems:
        print(f"[FAIL] 发现 {len(problems)} 个路由问题：")
        for p in problems:
            print(f"  - {p}")
        return 1

    print(f"[OK] HTTP 路由门禁通过：{len(routes)} 条路由全部返回期望 status（base={base}）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))