#!/usr/bin/env python3
"""版本号 4 处同步门禁 + CHANGELOG 顺序门禁。

**为什么要有这个门禁**
发版要同步 4 个地方：`src/app/__init__.py` 的 `__version__` /
`pyproject.toml` 的 `version` / `uv.lock` 的项目包 version /
`static/sw.js` 的 `const VERSION`。

此前只有 `check_pwa_assets.py` 校验了其中**一对**（`__init__.py` ↔ `sw.js`），
`pyproject.toml` ↔ `uv.lock` 这一对**无人看管** ——
改了 `pyproject.toml` 忘了跑 `uv lock`，CI 的 `uv sync --frozen` 会炸，
而本地跑任何门禁都是绿的。V0.100.1（改 static 必须 bump sw.js）就是这条链路断过的教训。

**解析方式刻意选抗干扰的**
- `__version__` 用 `ast` 解析 —— 注释和文档串里写 `__version__ = "9.9.9"` 骗不过去
  （记忆「断言必须先剥注释」：靠正则剥注释迟早漏一处）
- `pyproject.toml` / `uv.lock` 用 `tomllib` —— TOML 有嵌套结构，
  `uv.lock` 里几十个包各带一个 `version`，正则很容易抓错块
- `sw.js` 才用正则（它是 JS，没有标准库解析器），
  但锚定 `^const VERSION = "..."` 且只扫 `static/sw.js` 一个文件
  （`static/dashboard.js` 有同名的 `VERSION`，语义无关，不可混为一谈）

**CHANGELOG 顺序门禁**
本门禁还要求 CHANGELOG 的版本段**严格降序、无重复**。
这不是洁癖：2026-10-24 之前，CHANGELOG 里 `## [V0.104.0]` 出现过两次，
第一次那段里实际混装着 V0.102.0 / V0.103.0 / V0.100.1 / V0.100.2 / V0.103.1 五个版本的内容，
而真正的 V0.100.0 段被夹在两个 V0.104.0 之间（它的 `### Discipline` 更是被甩到了文件末尾）。
**顺序乱了 = 版本归属乱了 = 查发版史会查错。**

退出码：0 = 全绿，1 = 有 FAIL。
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INIT_PY = ROOT / "src" / "app" / "__init__.py"
PYPROJECT = ROOT / "pyproject.toml"
UV_LOCK = ROOT / "uv.lock"
SW_JS = ROOT / "static" / "sw.js"
CHANGELOG = ROOT / "CHANGELOG.md"
INDEX_MD = ROOT / "docs" / "releases" / "index.md"
VERSION_STATUS = ROOT / "docs" / "version-status.md"
RELEASES = ROOT / "docs" / "releases"

PROJECT_NAME = "gold-etf-analyzer"

SW_VERSION_RE = re.compile(r'^const\s+VERSION\s*=\s*"(v[^"]+)"', re.M)
CHANGELOG_SECTION_RE = re.compile(r"^## \[V([0-9.]+)(\s+hotfix)?\]", re.M)


class Result:
    """收集每条断言的通过/失败，最后统一汇总（门禁必须报数，不能只报绿）。"""

    def __init__(self) -> None:
        self.passed = 0
        self.failed: list[str] = []

    def check(self, label: str, ok: bool, detail: str = "") -> bool:
        if ok:
            self.passed += 1
            print(f"  [OK]   {label}")
        else:
            self.failed.append(f"{label}" + (f" —— {detail}" if detail else ""))
            print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))
        return ok


def read_version_from_python(path: Path) -> str:
    """用 ast 取 `__version__` 的字面量值。

    刻意不用正则：`# __version__ = "9.9.9"` 这种注释行、或者 docstring 里
    恰好以 `__version__ = ` 开头的行，正则都会中招，ast 不会。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "__version__"
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ):
                    return node.value.value
    raise SystemExit(f"[FAIL] 无法从 {path.relative_to(ROOT)} 解析出 __version__ 的字符串字面量")


def read_pyproject_version(path: Path) -> str:
    with path.open("rb") as f:
        data = tomllib.load(f)
    try:
        return str(data["project"]["version"])
    except KeyError:
        raise SystemExit(f"[FAIL] {path.relative_to(ROOT)} 缺少 [project].version") from None


def read_uv_lock_version(path: Path) -> str:
    """取 lockfile 里 **本项目** 那个包的 version。

    uv.lock 里每个依赖包各带一个 `version`，必须按 name 定位，
    正则 `version = "..."` 会抓到第一个依赖的版本。
    """
    with path.open("rb") as f:
        data = tomllib.load(f)
    for pkg in data.get("package", []):
        if pkg.get("name") == PROJECT_NAME:
            return str(pkg.get("version", ""))
    raise SystemExit(f"[FAIL] {path.relative_to(ROOT)} 里找不到 package {PROJECT_NAME!r}")


def read_sw_version(path: Path) -> str:
    """取 sw.js 的 `const VERSION`（带 `v` 前缀，如 `v0.116.0`）。"""
    m = SW_VERSION_RE.search(path.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit(f"[FAIL] 无法从 {path.relative_to(ROOT)} 解析出 const VERSION")
    return m.group(1)


def changelog_sections(path: Path) -> list[tuple[str, bool]]:
    """返回 [(版本号, 是否 hotfix 后缀)]，按文件出现顺序。"""
    out: list[tuple[str, bool]] = []
    for m in CHANGELOG_SECTION_RE.finditer(path.read_text(encoding="utf-8")):
        out.append((m.group(1), bool(m.group(2))))
    return out


def version_key(version: str, is_hotfix: bool) -> tuple[int, int, int, int]:
    """排序键。hotfix 后缀排在同版本基础段**之上**（与仓库现状一致：
    `V0.97.2 hotfix` 段明确写了「不 bump 版本号」，它与 `V0.97.2` 同版本号）。"""
    nums = [int(x) for x in version.split(".")]
    while len(nums) < 3:
        nums.append(0)
    return (nums[0], nums[1], nums[2], 1 if is_hotfix else 0)


def main(argv: list[str]) -> int:
    r = Result()

    app_version = read_version_from_python(INIT_PY)
    pyproject_version = read_pyproject_version(PYPROJECT)
    uv_version = read_uv_lock_version(UV_LOCK)
    sw_version = read_sw_version(SW_JS)
    sw_version = sw_version[1:] if sw_version.startswith("v") else sw_version

    print(f"  应用版本（src/app/__init__.py） = {app_version}")
    print(f"  pyproject.toml [project]      = {pyproject_version}")
    print(f"  uv.lock package.{PROJECT_NAME} = {uv_version}")
    print(f"  static/sw.js const VERSION     = v{sw_version}")
    print()

    # ── 1) 4 处版本号必须两两相等 ──
    for label, got, want in (
        ("pyproject.toml == __version__", pyproject_version, app_version),
        ("uv.lock == __version__", uv_version, app_version),
        ("sw.js VERSION == __version__", sw_version, app_version),
    ):
        r.check(label, got == want, f"实际 {got!r}，期望 {want!r}")

    # ── 2) CHANGELOG 最新版本段 == 应用版本 ──
    sections = changelog_sections(CHANGELOG)
    r.check("CHANGELOG 有版本段", bool(sections), "未匹配到任何 `## [V...]`")
    if sections:
        newest, newest_hotfix = sections[0]
        r.check(
            "CHANGELOG 最新版本段 == 应用版本",
            (newest, newest_hotfix) == (app_version, False),
            f"CHANGELOG 最新是 V{newest}{' hotfix' if newest_hotfix else ''}，应用是 {app_version}",
        )

        # ── 3) CHANGELOG 版本段严格降序（抓重复段与错位）──
        keys = [version_key(v, h) for v, h in sections]
        offenders = []
        for i in range(len(keys) - 1):
            if keys[i] <= keys[i + 1]:
                offenders.append(
                    f"第 {i + 1} 段 V{sections[i][0]}{' hotfix' if sections[i][1] else ''} "
                    f"未严格大于下一段 V{sections[i + 1][0]}"
                    f"{' hotfix' if sections[i + 1][1] else ''}"
                )
        r.check(
            f"CHANGELOG {len(sections)} 个版本段严格降序、无重复",
            not offenders,
            "；".join(offenders[:5]),
        )

    # ── 4) 当前版本必须有 release notes ──
    note = RELEASES / f"v{app_version}.md"
    r.check(f"当前版本有 release notes（docs/releases/v{app_version}.md）", note.is_file())

    # ── 5) 当前版本必须在 index.md 登记 ──
    if INDEX_MD.is_file():
        idx = INDEX_MD.read_text(encoding="utf-8")
        # 匹配**链接目标**而不是裸子串：裸子串会让 `v0.116.0.md.x` 里的
        # `v0.116.0.md` 也算命中 —— 反向验证实测：把 index.md 里的
        # `v0.116.0.md` 改成 `v0.116.0.md.x`，裸子串检查仍然全绿（假绿）。
        link_re = re.compile(rf"\(\s*v{re.escape(app_version)}\.md\s*\)")
        r.check(
            "当前版本在 docs/releases/index.md 登记",
            bool(link_re.search(idx)),
            f"index.md 里找不到指向 v{app_version}.md 的 markdown 链接目标",
        )

    # ── 6) version-status.md 声明的基线版本必须等于应用版本 ──
    # 这份文档是「当前是哪个版本」的单一真源，它一旦发版就会过期。
    # 过期而不报红 = 文档开始撒谎，比没有文档更坏 —— 所以把它纳入门禁。
    if VERSION_STATUS.is_file():
        vs_text = VERSION_STATUS.read_text(encoding="utf-8")
        m = re.search(r"基线：\s*V([0-9.]+)", vs_text)
        r.check(
            "version-status.md 声明的基线版本 == 应用版本",
            bool(m) and m.group(1) == app_version,
            (
                f"version-status.md 声明的是 V{m.group(1)}，应用是 {app_version}"
                if m
                else "version-status.md 里找不到「基线：VX.Y.Z」声明"
            ),
        )
    else:
        r.check("version-status.md 存在", False, f"缺 {VERSION_STATUS.relative_to(ROOT)}")

    print()
    print("=" * 70)
    if r.failed:
        print(f"结果：{r.passed} passed / {len(r.failed)} failed")
        print("=" * 70)
        print("[FAIL] 版本同步门禁未通过：")
        for f in r.failed:
            print(f"  - {f}")
        return 1
    print(f"结果：{r.passed} passed")
    print("=" * 70)
    print(
        f"[OK] 版本同步门禁通过：4 处版本号一致（{app_version}）、CHANGELOG 版本段严格降序、"
        f"当前版本有 release notes 且已登记、version-status.md 基线未过期"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
