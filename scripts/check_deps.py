#!/usr/bin/env python
r"""校验「代码 import 的第三方包」与「pyproject.toml 声明的依赖」一致（第 7 道门禁）。

背景 —— 为什么必须机械校验
--------------------------
`uv.lock` 只锁定**已声明**的依赖，对未声明的 `import` 一无所知。

V0.75.0 的实例（偏差 #60）：`src/app/services/auth.py` 模块级 `import bcrypt`，
但 `pyproject.toml` 漏写 ⇒ CI 的 `uv sync --frozen` 与镜像的 `uv export --frozen --no-dev`
**都不含 bcrypt** ⇒ `tests/conftest.py` 加载即 `ImportError`（864 个用例一个都跑不到）、
容器 `import app.main` 直接崩溃。**而开发者本机手动装过，本地 820 例全绿。**

结论：**「本地全绿」证明不了 CI / 生产可用** —— 该缺陷可 100% 机械检出，却烧掉了
2 个版本、5 个 CI run 连续全红。

判定规则
--------
- `src/**/*.py` 的第三方 import → **必须**在 `[project] dependencies` 中
  （这是**运行时**依赖，镜像只装 dependencies）；
- `tests/**/*.py` 的第三方 import → 可在 `dependencies` **或任一 extra** 中
  （测试依赖允许放 `dev` extra）。

两个刻意的设计取舍
------------------
1. **覆盖 extras**：只看 `dependencies` 会把 `pytest` / `ruff` 误报成未声明。
2. **只查 import，不查「声明了但没用」**：`uvicorn`（启动命令）、`alembic`（迁移 CLI）、
   `aiosqlite`（SQLAlchemy 的 URL 驱动）、`jinja2` 都不被 `import`，但都是真实依赖 ——
   反向校验会产生 4 处固定误报，故**有意不做**。

用法
----
    python scripts/check_deps.py          # 校验（失败非零退出）
    python scripts/check_deps.py --list    # 打印三方 import 与声明清单
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 本项目内部模块：不是第三方包
INTERNAL_MODULES: set[str] = {
    "app",
    "tests",
    "conftest",
    "scripts",
} | {p.stem for p in (ROOT / "scripts").glob("*.py")}

# 导入名 → 发行包名 的**真实别名**（PEP 503 规范化处理不了的那些）。
# 本项目当前 12 个第三方 import 全都无需映射（`py_vapid` / `pydantic_settings` 等
# 经 `[-_.]+ → -` 规范化即可命中），此处保留给将来引入时使用。
IMPORT_TO_DIST: dict[str, str] = {
    "yaml": "PyYAML",
    "PIL": "Pillow",
    "bs4": "beautifulsoup4",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "jwt": "PyJWT",
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "fitz": "PyMuPDF",
    "attr": "attrs",
    "pkg_resources": "setuptools",
}


def normalize(name: str) -> str:
    """PEP 503 名称规范化：`[-_.]+` → `-`，转小写。"""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def dist_name_of(import_name: str) -> str:
    """import 用的模块名 → 发行包规范化名。"""
    return normalize(IMPORT_TO_DIST.get(import_name, import_name))


def spec_dist_name(spec: str) -> str:
    """`"uvicorn[standard]>=0.32,<1.0"` → `uvicorn`。"""
    s = spec.split(";")[0].strip()  # 去掉环境标记
    s = re.sub(r"\[[^\]]*\]", "", s)  # 去掉 extras 标记
    m = re.match(r"^[A-Za-z0-9._-]+", s)
    return normalize(m.group(0)) if m else ""


def third_party_imports(root: Path) -> dict[str, set[str]]:
    """扫描目录下 .py 的**全部** import（含函数内延迟导入），返回 {模块名: {文件}}。

    ⚠ 必须包含函数内的 import：`akshare` 等重依赖通常写在使用处延迟导入，
    只扫顶层会漏掉它们。
    """
    found: dict[str, set[str]] = {}
    for path in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - 语法错误由 ruff / pytest 抓
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                # 相对导入（level > 0）是本项目内部模块
                names = [node.module] if node.level == 0 and node.module else []
            else:
                continue
            for full in names:
                top = full.split(".")[0]
                if top in INTERNAL_MODULES or top in sys.stdlib_module_names:
                    continue
                try:
                    rel = path.relative_to(ROOT).as_posix()
                except ValueError:
                    # 测试会传入仓库外的临时目录
                    rel = path.as_posix()
                found.setdefault(top, set()).add(rel)
    return found


def _load_pyproject() -> tuple[set[str], dict[str, set[str]]]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]
    runtime = {spec_dist_name(d) for d in project.get("dependencies", [])}
    extras = {
        name: {spec_dist_name(d) for d in specs}
        for name, specs in (project.get("optional-dependencies") or {}).items()
    }
    runtime.discard("")
    for v in extras.values():
        v.discard("")
    return runtime, extras


def main(argv: list[str]) -> int:
    runtime, extras = _load_pyproject()
    in_any_extra = {e for v in extras.values() for e in v}
    all_declared = runtime | in_any_extra

    src_imports = third_party_imports(ROOT / "src")
    tests_imports = third_party_imports(ROOT / "tests")
    tests_imports = {k: v for k, v in tests_imports.items() if k not in src_imports}

    if "--list" in argv:
        print(f"dependencies（运行时，{len(runtime)} 项）:")
        for d in sorted(runtime):
            print(f"    {d}")
        for name, specs in sorted(extras.items()):
            print(f"\nextra[{name}]（{len(specs)} 项）:")
            for d in sorted(specs):
                print(f"    {d}")
        print(f"\nsrc/ 第三方 import（{len(src_imports)} 个）:")
        for mod, files in sorted(src_imports.items()):
            print(f"    {mod:20s} -> {dist_name_of(mod):22s} ({len(files)} 文件)")
        print(f"\ntests/ 独有第三方 import（{len(tests_imports)} 个）:")
        for mod in sorted(tests_imports):
            print(f"    {mod:20s} -> {dist_name_of(mod)}")
        return 0

    problems: list[str] = []

    # ① src/ 的 import 必须在 dependencies（运行时依赖）
    for mod, files in sorted(src_imports.items()):
        dist = dist_name_of(mod)
        if dist in runtime:
            continue
        where = [n for n, specs in extras.items() if dist in specs]
        hint = (
            f" —— 它出现在 extra[{', '.join(where)}] 中，但 src/ 是运行时代码，"
            f"镜像执行 `uv export --frozen --no-dev` 不含 extras ⇒ 容器启动即 ImportError"
            if where
            else ""
        )
        problems.append(
            f"src/ 的 `import {mod}` 未在 [project] dependencies 声明"
            f"（规范化名 {dist!r}，涉及 {len(files)} 个文件：{sorted(files)[0]} …）{hint}"
        )

    # ② tests/ 独有 import 可在 dependencies 或任一 extra
    for mod, files in sorted(tests_imports.items()):
        dist = dist_name_of(mod)
        if dist not in all_declared:
            problems.append(
                f"tests/ 的 `import {mod}` 未在 dependencies 或任何 extra 中声明"
                f"（规范化名 {dist!r}，涉及 {sorted(files)[0]} …）"
            )

    print(f"  dependencies        = {len(runtime)} 项")
    print(
        "  extras              = "
        + "、".join(f"{n}({len(v)})" for n, v in sorted(extras.items()))
        + f" 合计 {len(in_any_extra)} 项"
    )
    print(f"  src/ 三方 import     = {len(src_imports)} 个")
    print(f"  tests/ 独有三方 import = {len(tests_imports)} 个")
    print()

    if problems:
        print(f"[FAIL] 发现 {len(problems)} 个依赖声明缺口：")
        for p in problems:
            print(f"  - {p}")
        return 1

    print(
        f"[OK] 依赖声明门禁通过：src/ {len(src_imports)} 个三方 import 全部在 dependencies；"
        f"tests/ 独有 {len(tests_imports)} 个全部已声明"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
