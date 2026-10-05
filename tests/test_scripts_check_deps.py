"""依赖声明门禁（`scripts/check_deps.py`）的回归测试。

动机：偏差 #60 的 `bcrypt` 缺陷（代码 `import` 了、`pyproject.toml` 没声明）能 100% 机械检出，
却烧掉了 2 个版本、5 个 CI run 连续全红 + 镜像完全不可用。本模块确保这道门禁本身可靠。

除纯函数测试外，**回归断言 `starlette` 仍在 `dependencies` 中** —— 它是 V0.78.1 由本门禁
首跑抓出的真实缺口（`src/app/middleware/*.py` 直接 `import starlette`），删掉它测试即红。
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_deps  # noqa: E402


def _declared() -> tuple[set[str], dict[str, set[str]]]:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]
    runtime = {check_deps.spec_dist_name(d) for d in project.get("dependencies", [])}
    extras = {
        n: {check_deps.spec_dist_name(d) for d in specs}
        for n, specs in (project.get("optional-dependencies") or {}).items()
    }
    return runtime, extras


def test_pep503_normalization() -> None:
    """`[-_.]+` → `-` 且转小写（PEP 503）。"""
    assert check_deps.dist_name_of("py_vapid") == "py-vapid"
    assert check_deps.dist_name_of("pydantic_settings") == "pydantic-settings"
    assert check_deps.dist_name_of("SQLAlchemy") == "sqlalchemy"


def test_alias_map_for_real_aliases() -> None:
    """PEP 503 规范化处理不了的别名必须走映射表。"""
    assert check_deps.dist_name_of("yaml") == "pyyaml"
    assert check_deps.dist_name_of("PIL") == "pillow"
    assert check_deps.dist_name_of("bs4") == "beautifulsoup4"


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("fastapi>=0.115,<1.0", "fastapi"),
        ("uvicorn[standard]>=0.32,<1.0", "uvicorn"),
        ('httpx>=0.27; python_version >= "3.11"', "httpx"),
        ("py-vapid>=1.9,<2.0", "py-vapid"),
    ],
)
def test_spec_dist_name_strips_extras_and_markers(spec: str, expected: str) -> None:
    """从依赖声明串里取出发行包名。"""
    assert check_deps.spec_dist_name(spec) == expected


def test_third_party_imports_skips_stdlib_and_internal(tmp_path: Path) -> None:
    """标准库与本项目内部模块不算第三方。"""
    (tmp_path / "m.py").write_text(
        "import os\nimport sys\nfrom __future__ import annotations\n"
        "from app.services import trend\nimport httpx\n",
        encoding="utf-8",
    )
    found = check_deps.third_party_imports(tmp_path)
    assert set(found) == {"httpx"}


def test_third_party_imports_sees_function_level_imports(tmp_path: Path) -> None:
    """函数内的延迟导入也要算 —— `akshare` 等重依赖正是这种写法。"""
    (tmp_path / "m.py").write_text(
        "def f():\n    import akshare  # noqa: PLC0415\n    return akshare\n",
        encoding="utf-8",
    )
    assert "akshare" in check_deps.third_party_imports(tmp_path)


def test_repo_src_imports_are_all_declared() -> None:
    """仓库 src/ 的全部三方 import 必须在 dependencies 中（门禁主体）。"""
    runtime, _ = _declared()
    imports = check_deps.third_party_imports(REPO_ROOT / "src")
    undeclared = sorted(m for m in imports if check_deps.dist_name_of(m) not in runtime)
    assert undeclared == [], f"以下包被 import 但未声明：{undeclared}"


def test_starlette_stays_declared() -> None:
    """回归：`starlette` 必须留在 dependencies（V0.78.1 由本门禁首跑抓出）。"""
    runtime, _ = _declared()
    assert "starlette" in runtime


def test_test_only_imports_allowed_in_extras() -> None:
    """tests/ 独有的 import 允许放在 extra（如 dev）里 —— 不能只看 dependencies。"""
    runtime, extras = _declared()
    in_extra = {e for v in extras.values() for e in v}
    tests_imports = check_deps.third_party_imports(REPO_ROOT / "tests")
    src_imports = check_deps.third_party_imports(REPO_ROOT / "src")
    only_tests = {m for m in tests_imports if m not in src_imports}
    undeclared = sorted(
        m for m in only_tests if check_deps.dist_name_of(m) not in (runtime | in_extra)
    )
    assert undeclared == [], f"tests/ 独有且未声明的包：{undeclared}"
