#!/usr/bin/env python
r"""校验 PWA 静态资源清单与实际服务端一致（PWA 资源门禁）。

背景
----
三类缺陷的共同根因是**静态资源里写了服务端不存在的 URL**，而它们全部逃过既有门禁：

1. `static/sw.js` 的 `SHELL_ASSETS` 由 `cache.addAll()` 预缓存，它是**原子操作** ——
   任一 URL 失败即**整批回滚**，`SHELL_CACHE` 为空、PWA 离线能力归零，
   且**没有任何用户可见提示**。历史上曾写入 3 条服务端不存在的 URL
   （`/central_bank` / `/backtest` / `/silver`，实测 404）⇒ precache 从未成功过一次。

2. `static/sw.js` 的 `const VERSION`（决定 SW 缓存名 `gold-shell-*` / `gold-runtime-*`）。
   它自 2026-09-21 创建后一直停在 `v0.77.1`，而 `static/` 已跨两个版本持续改动。
   失效链三步叠加且**全静默**：`/static/` 走 cache-first 且不后台更新 → `sw.js` 字节
   未变故浏览器**不重装 SW** → 即便重装，`activate` 按 `VERSION` 清缓存而名字没变。
   后果是**「HTML 新 + JS 旧」错配**（新版结论卡 / i18n 词典不生效），比整站皆旧更难查。
   ⚠ 与 `static/dashboard.js:26` 的同名 `VERSION`（布局 schema 锚，**不可动**）语义无关。

3. `static/manifest.json` 的 `shortcuts[].url`。它不在任何 JS / HTML 门禁的扫描范围内，
   实测曾指向 `/silver` / `/backtest`（404）—— PWA 长按图标的快捷方式点了打不开。

本脚本把上述三件事机械化。

判定「URL 能被服务端解析」的口径（纯静态，不启动服务）
------------------------------------------------------
- `/static/...`          → 对应文件在 `static/` 下**存在**；
- 其余路径（含 `/`）      → 在 `src/app/main.py` 的 `@app.<method>("/...")` 路由中出现。

⚠ 若将来引入 `StaticFiles` 之外的动态挂载点或带参数的资源路径，需同步扩展本脚本，
   不要让它**静默漏检** —— 漏检比误报危险得多。

可测试性
--------
全部输入路径（`__init__.py` / `main.py` / `sw.js` / `manifest.json` / `static/`）
均可注入（见 `check_all()`），故本门禁有**常驻回归测试**
`tests/test_scripts_check_pwa_assets.py` —— 负向验证因而可重复执行。
V0.78.1 首次上线时该验证是手工做的，做完即不可复查；
另两道新门禁（check_links / check_deps）当时已各带 10 / 11 例，唯本道不对等。

用法
----
    python scripts/check_pwa_assets.py          # 校验（失败非零退出）
    python scripts/check_pwa_assets.py --list   # 打印解析出的清单与路由表
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
SW_JS = STATIC / "sw.js"
MANIFEST = STATIC / "manifest.json"
MAIN_PY = ROOT / "src" / "app" / "main.py"
INIT_PY = ROOT / "src" / "app" / "__init__.py"

# `const NAME = "value";` 形式的简单字符串常量 —— 用于解析 SHELL_ASSETS 里的符号引用
# （如 `OFFLINE_URL`）。变量套变量（`const A = B;`）不支持：出现即报错，好过静默漏检。
CONST_RE = re.compile(r'^const\s+([A-Z][A-Z0-9_]*)\s*=\s*"([^"]*)"\s*;', re.M)

# main.py 里注册的 HTTP 路由路径（页路由都是字面量，故静态提取可靠）
ROUTE_RE = re.compile(r'@app\.(?:get|post|put|delete|patch)\(\s*"([^"]+)"')

SHELL_ARRAY_RE = re.compile(r"const\s+SHELL_ASSETS\s*=\s*\[(.*?)\n\];", re.S)
APP_VERSION_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.M)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _rel(path: Path) -> str:
    """相对仓库根的展示路径；目标在仓库外（测试注入的临时文件）时原样返回。

    ⚠ 不可直接用 relative_to：它对仓库外路径抛 ValueError ——
      check_deps.py 曾因此让两个测试失败。
    """
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _app_version(init_py: Path = INIT_PY) -> str:
    m = APP_VERSION_RE.search(_read(init_py))
    if not m:
        raise SystemExit(f"[FAIL] 无法从 {_rel(init_py)} 解析 __version__")
    return m.group(1)


def _routes(main_py: Path = MAIN_PY) -> set[str]:
    """main.py 注册的全部路由路径。"""
    return set(ROUTE_RE.findall(_read(main_py)))


def _parse_shell_assets(text: str) -> tuple[dict[str, str], list[str]]:
    r"""返回 (字符串常量符号表, SHELL_ASSETS 展开后的 URL 列表)。

    ⚠ 注释只支持**整行**或「空白 + `//`」两种形式（本项目现状如此）。
    值内部含 `//` 的 URL 不会被误伤（`\s+//` 要求斜杠前有空白）。
    """
    consts = dict(CONST_RE.findall(text))

    m = SHELL_ARRAY_RE.search(text)
    if not m:
        raise SystemExit("[FAIL] 无法从 sw.js 定位 SHELL_ASSETS 数组")

    urls: list[str] = []
    for raw_line in m.group(1).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue
        line = re.sub(r"\s+//.*$", "", line).strip().rstrip(",").strip()
        if not line:
            continue

        if line.startswith('"') and line.endswith('"'):
            urls.append(line[1:-1])
        elif re.fullmatch(r"[A-Z][A-Z0-9_]*", line):
            if line not in consts:
                raise SystemExit(
                    f"[FAIL] SHELL_ASSETS 引用了未知常量 {line} —— "
                    f"本脚本只支持 `const {line} = \"...\";` 的简单形式，请同步扩展解析逻辑"
                )
            urls.append(consts[line])
        else:
            raise SystemExit(
                f"[FAIL] SHELL_ASSETS 存在无法解析的条目：{line!r} —— "
                f"请同步扩展本脚本，不要静默漏检"
            )

    return consts, urls


def _why_unresolvable(url: str, routes: set[str], static_dir: Path = STATIC) -> str | None:
    """可解析返回 None，否则返回失败原因。"""
    if url.startswith("/static/"):
        rel = url[len("/static/") :]
        if (static_dir / rel).is_file():
            return None
        return f"static/{rel} 文件不存在"
    if url in routes:
        return None
    return f"服务端未注册路由 {url}（既非 static 文件，也不在 main.py 路由表）"


def _check_manifest(
    routes: set[str],
    manifest: Path = MANIFEST,
    static_dir: Path = STATIC,
) -> tuple[list[str], dict[str, int]]:
    """校验 manifest.json 的目标可否解析。返回 (问题列表, 各类目标计数)。"""
    problems: list[str] = []
    counts = {"start_url": 0, "shortcuts": 0, "icons": 0}
    where = _rel(manifest)
    try:
        data = json.loads(_read(manifest))
    except json.JSONDecodeError as exc:
        return [f"{where} 不是合法 JSON：{exc}"], counts

    targets: list[tuple[str, str]] = []

    start_url = data.get("start_url")
    if isinstance(start_url, str):
        targets.append(("start_url", start_url))
        counts["start_url"] = 1
    else:
        problems.append(f"{where} 缺少 start_url")

    for i, sc in enumerate(data.get("shortcuts") or []):
        if not isinstance(sc, dict):
            problems.append(f"shortcuts[{i}] 不是对象")
            continue
        name = sc.get("name", f"#{i}")
        url = sc.get("url")
        if isinstance(url, str):
            targets.append((f"shortcuts[{i}]「{name}」", url))
            counts["shortcuts"] += 1
        else:
            problems.append(f"shortcuts[{i}]「{name}」缺少 url")

    for i, icon in enumerate(data.get("icons") or []):
        if isinstance(icon, dict) and isinstance(icon.get("src"), str):
            targets.append((f"icons[{i}]", icon["src"]))
            counts["icons"] += 1

    for label, url in targets:
        why = _why_unresolvable(url, routes, static_dir)
        if why:
            problems.append(f"{where} 的 {label} → {url}：{why}")

    return problems, counts


class Info(NamedTuple):
    """门禁的观测结果，供 main() 打印与测试断言。"""

    app_version: str
    sw_version: str | None
    expected: str
    shell_urls: list[str]
    manifest_counts: dict[str, int]


def check_all(
    *,
    init_py: Path = INIT_PY,
    main_py: Path = MAIN_PY,
    sw_js: Path = SW_JS,
    manifest: Path = MANIFEST,
    static_dir: Path = STATIC,
) -> tuple[list[str], Info]:
    """执行三类断言，返回 (问题列表, 观测结果)。

    全部输入路径可注入 —— 这是「负向验证可重复执行」的前提：测试可用临时目录
    构造假的 sw.js / manifest.json，确证脚本真能抓到问题，而不是只依赖
    「仓库当前恰好是干净的」这一事实（后者对回归毫无保护力）。
    """
    app_version = _app_version(init_py)
    routes = _routes(main_py)
    consts, shell_urls = _parse_shell_assets(_read(sw_js))

    problems: list[str] = []

    # ① SW 缓存版本必须与运行中的应用版本一致
    sw_version = consts.get("VERSION")
    expected = f"v{app_version}"
    if sw_version is None:
        problems.append("static/sw.js 未找到 `const VERSION = \"...\";`（SW 缓存名的组成部分）")
    elif sw_version != expected:
        problems.append(
            f"static/sw.js 的 VERSION={sw_version!r} ≠ 应用版本 {expected!r}"
            f" —— 不更新它，已安装 PWA 的浏览器会继续用旧缓存里的 /static/ 资源"
        )

    # ② SHELL_ASSETS 每条都要能解析（cache.addAll 是原子操作，一条错则整批回滚）
    for url in shell_urls:
        why = _why_unresolvable(url, routes, static_dir)
        if why:
            problems.append(f"sw.js 的 SHELL_ASSETS 条目 {url}：{why}")

    # ③ manifest.json 的 start_url / shortcuts / icons
    manifest_problems, counts = _check_manifest(routes, manifest, static_dir)
    problems.extend(manifest_problems)

    info = Info(
        app_version=app_version,
        sw_version=sw_version,
        expected=expected,
        shell_urls=shell_urls,
        manifest_counts=counts,
    )
    return problems, info


def main(argv: list[str]) -> int:
    if "--list" in argv:
        routes = _routes()
        _, shell_urls = _parse_shell_assets(_read(SW_JS))
        print(f"应用版本（src/app/__init__.py）: {_app_version()}")
        print(f"main.py 注册路由 {len(routes)} 条：")
        for r in sorted(routes):
            print(f"    {r}")
        print(f"\nSHELL_ASSETS {len(shell_urls)} 条：")
        for u in shell_urls:
            print(f"    {u}")
        return 0

    problems, info = check_all()
    counts = info.manifest_counts

    print(f"  sw.js VERSION      = {info.sw_version}（期望 {info.expected}）")
    print(f"  SHELL_ASSETS       = {len(info.shell_urls)} 条")
    print(
        f"  manifest.json      = start_url {counts['start_url']} 条"
        f" + shortcuts {counts['shortcuts']} 条 + icons {counts['icons']} 个"
    )
    print()

    if problems:
        print(f"[FAIL] 发现 {len(problems)} 个问题：")
        for p in problems:
            print(f"  - {p}")
        return 1

    print(
        f"[OK] PWA 资源门禁通过：SW 缓存版本与应用版本一致（{info.expected}）、"
        f"SHELL_ASSETS {len(info.shell_urls)} 条全部可解析、"
        f"manifest.json {sum(counts.values())} 个目标全部存在"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
