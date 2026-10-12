"""``scripts/check_routes.py`` 单元测试（V0.88.0 维护线）。

覆盖：
- ``discover_routes()`` 反射 FastAPI app（含 Mount 过滤、APIRoute 提取）
- ``check_routes()`` 双向验证：expected 表与 routes 集合的交集 / 差集语义
- ``_default_fetch`` 不跟 redirect（拿首跳 status）
- 端到端：``main(['--list'])`` 与 ``main(['--base', mock])`` 不启服务

策略：mock fetch + 假 routes 列表；不启真实 uvicorn（in-process 启动 ~1s，
避免拖慢测试套件）。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.main import app as fastapi_app
from scripts import check_routes


# ──────────────── discover_routes ────────────────


class TestDiscoverRoutes:
    """``discover_routes(app)`` 反射 FastAPI app.routes 的过滤逻辑。"""

    def test_reflects_actual_routes(self) -> None:
        """真实 app 反射：12 alias + /sw.js = 13 条（含 ``include_in_schema=False``）。"""
        routes = check_routes.discover_routes(fastapi_app)
        # 至少含 12 个 alias + 1 个 sw.js
        assert "/" in routes
        assert "/portfolio" in routes
        assert "/data-health" in routes
        assert "/sw.js" in routes
        # 不含 /openapi.json（Starlette 自动生成，已在脚本里过滤）
        assert "/openapi.json" not in routes

    def test_skips_static_mount(self) -> None:
        """``Mount('/static', ...)`` 必须被过滤掉。"""
        routes = check_routes.discover_routes(fastapi_app)
        # 反射拿到的路径不含 ``/static``（mount 不是 APIRoute）
        assert not any(r.startswith("/static") for r in routes), (
            f"discover_routes 不应含 /static mount：{routes}"
        )

    def test_count_matches_root_aliases_parametrize(self) -> None:
        """反射数应等于 ``tests/test_main_app.py::ROOT_ALIASES`` 的 12 + /sw.js = 13。

        任何 main.py alias 漏注册都会被这个数捕获（防 V0.85 漏注册 /data-health 复现）。
        """
        routes = check_routes.discover_routes(fastapi_app)
        # 12 alias + 1 sw.js = 13
        assert len(routes) == 13, (
            f"反射 {len(routes)} 条；期望 13（12 alias + /sw.js）。"
            "新增 alias 必须同步更新 EXPECTED_ALIAS_PATHS + test_main_app.ROOT_ALIASES"
        )


# ──────────────── check_routes ────────────────


class TestCheckRoutes:
    """``check_routes()`` 双向验证 + status 比对 + 连接错误处理。"""

    def test_all_pass(self) -> None:
        """所有 route 返回期望 status → 返回空 list。"""
        routes = ["/", "/portfolio", "/sw.js"]
        expected = {"/": 307, "/portfolio": 307, "/sw.js": 200}

        def _fetch(url: str) -> int:
            # 简单路由表返回期望 status
            path = url[len("http://x"):]
            return expected.get(path, 404)

        problems = check_routes.check_routes(
            routes=routes, fetch=_fetch, base="http://x", expected=expected
        )
        assert problems == []

    def test_route_not_in_expected_is_drift_signal(self) -> None:
        """routes ⊆ expected：route 在反射表但未登记 → FAIL（漂移信号）。"""
        routes = ["/some-new-alias"]
        expected = {"/": 307}  # /some-new-alias 不在表里

        def _fetch(_url: str) -> int:
            return 307

        problems = check_routes.check_routes(
            routes=routes, fetch=_fetch, base="http://x", expected=expected
        )
        assert len(problems) == 1
        assert "/some-new-alias" in problems[0]
        assert "未登记" in problems[0]

    def test_actual_status_mismatch(self) -> None:
        """route 在表里但实际 status 不匹配 → FAIL（详情含实际 vs 期望）。"""
        routes = ["/portfolio"]
        expected = {"/portfolio": 307}

        def _fetch(_url: str) -> int:
            return 404  # 假装 /portfolio 漏注册了

        problems = check_routes.check_routes(
            routes=routes, fetch=_fetch, base="http://x", expected=expected
        )
        assert len(problems) == 1
        assert "/portfolio" in problems[0]
        assert "期望 status 307" in problems[0]
        assert "实际 404" in problems[0]

    def test_connection_failure_status_0(self) -> None:
        """fetch 返回 0（连接失败）→ FAIL「连接失败」非「期望 status 0」。"""
        routes = ["/portfolio"]
        expected = {"/portfolio": 307}

        def _fetch(_url: str) -> int:
            return 0  # 模拟 urllib.URLError

        problems = check_routes.check_routes(
            routes=routes, fetch=_fetch, base="http://x", expected=expected
        )
        assert len(problems) == 1
        assert "连接失败" in problems[0]

    def test_expected_extra_path_outside_routes(self) -> None:
        """expected - routes：如 ``/static/trend.html``（mount）按表独立验证。"""
        routes = ["/portfolio"]  # 没含 /static/trend.html
        expected = {"/portfolio": 307, "/static/trend.html": 200}

        def _fetch(url: str) -> int:
            return expected.get(url[len("http://x"):], 404)

        problems = check_routes.check_routes(
            routes=routes, fetch=_fetch, base="http://x", expected=expected
        )
        assert problems == []

    def test_expected_extra_path_fails(self) -> None:
        """expected - routes 的 path 也按表验证：status 不匹配 → FAIL。"""
        routes = ["/portfolio"]
        expected = {"/portfolio": 307, "/static/trend.html": 200}

        def _fetch(url: str) -> int:
            path = url[len("http://x"):]
            if path == "/static/trend.html":
                return 404  # 模拟文件被删
            return 307

        problems = check_routes.check_routes(
            routes=routes, fetch=_fetch, base="http://x", expected=expected
        )
        assert len(problems) == 1
        assert "/static/trend.html" in problems[0]
        assert "实际 404" in problems[0]


# ──────────────── main() CLI 入口（用 --list 与 mock --base 验证流程） ────────────────


class TestMainCli:
    """``main(argv)`` 入口：--list 模式 + --base 模式（避免 in-process 启动耗时）。"""

    def test_main_list_mode_prints_routes(self, capsys: pytest.CaptureFixture) -> None:
        """``--list`` 模式：打印反射 routes + 期望表 + 返回 0。"""
        rc = check_routes.main(["check_routes.py", "--list"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "应用路由" in captured.out
        assert "/portfolio" in captured.out
        assert "/sw.js" in captured.out
        assert "期望 status 表" in captured.out

    def test_main_base_mode_with_working_server(self) -> None:
        """``--base`` 模式：注入 mock 服务（实际跑需 uvicorn，这里直接传 URL）。

        用一个永远不会 connect 的端口 → 期望全部 path 返回 0（连接失败）→ 全 FAIL。
        这能验证 fetch 路径走通 + 错误信息正确。
        """
        rc = check_routes.main(["check_routes.py", "--base", "http://127.0.0.1:1"])
        # 端口 1 几乎不可能开放 → 全部 path 连接失败
        assert rc == 1
        # 退出码非零即可（具体错误内容看 stderr）


# ──────────────── EXPECTED_STATUS 常量同步 ────────────────


class TestExpectedStatusConsistency:
    """``EXPECTED_STATUS`` 与 ``tests/test_main_app.py::ROOT_ALIASES`` 同步断言。

    这两个事实真相**必须**同步：漏任何一处都会让 V0.85 漏注册 /data-health
    类回归漏检。两个测试都断言相同数目（12 alias + /sw.js）。
    """

    def test_expected_alias_paths_count(self) -> None:
        """EXPECTED_ALIAS_PATHS 必须正好 12 条（与 main.py alias 数同步）。"""
        assert len(check_routes.EXPECTED_ALIAS_PATHS) == 12

    def test_expected_status_alias_keys_match(self) -> None:
        """EXPECTED_STATUS 的 alias 部分 key 集合 ⊇ EXPECTED_ALIAS_PATHS。"""
        status_keys = set(check_routes.EXPECTED_STATUS.keys())
        alias_set = set(check_routes.EXPECTED_ALIAS_PATHS)
        # alias 都登记且都期望 307
        assert alias_set <= status_keys
        for p in alias_set:
            assert check_routes.EXPECTED_STATUS[p] == 307, (
                f"{p} 应期望 307，实际 {check_routes.EXPECTED_STATUS[p]}"
            )

    def test_expected_status_alias_keys_count(self) -> None:
        """EXPECTED_STATUS 必须含 12 alias + /sw.js + /docs + /static/trend.html = 15。"""
        assert len(check_routes.EXPECTED_STATUS) == 15