"""PWA 资源门禁（`scripts/check_pwa_assets.py`）的回归测试。

为什么需要单独测这个脚本：它的三类断言都建立在**跨文件的一致性**上
（`src/app/__init__.py` 的版本 ↔ `static/sw.js` 的 VERSION ↔ 服务端真实路由），
而这三类缺陷全部逃过了既有的静态门禁 —— 以 V0.78.1 之前为例：

- `SHELL_ASSETS` 里 3 条 URL 是 404（`/central_bank` / `/backtest` / `/silver`），
  而 `cache.addAll()` 是**原子操作** ⇒ 整批回滚 ⇒ PWA 离线能力一直是零，
  且没有任何用户可见提示；
- `sw.js` 的 `VERSION` 自 2026-09-21 起停在 `v0.77.1`，跨两个版本未更新 ⇒
  老用户长期「HTML 新 + JS 旧」错配；
- `manifest.json` 的两个快捷方式指向实测 404 的 URL。

本模块的断言分两层（与 `test_scripts_check_links.py` 同一口径）：

1. **负向**：用临时目录注入坏数据，确证脚本**真能抓到问题**。
   只靠「仓库当前恰好是干净的」无法证明门禁有效 —— 那对回归毫无保护力。
2. **金标准**：对真实仓库跑一遍，锁住当前的一致性状态（尤其「307 入口必须保留
   RESTful 写法」这条 —— 见 `test_restful_nav_entries_are_precached` 的说明，
   这恰恰是最容易被「优化」掉的地方）。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_pwa_assets  # noqa: E402

# 当前由 RESTful 路由（RedirectResponse 307 → /static/*.html）提供的导航入口。
# 它们必须留在 SHELL_ASSETS 里以 RESTful 形式出现，理由见下方测试的 docstring。
RESTFUL_NAV_ENTRIES = ("/", "/portfolio", "/review", "/news", "/central-bank", "/trades")

SW_TEMPLATE = """\
const VERSION = "{version}";
const OFFLINE_URL = "/static/offline.html";

const SHELL_ASSETS = [
{entries}
];
"""


def _render_entry(entry: str) -> str:
    r"""把一个条目渲染成 sw.js 里的一行。

    三种写法必须区分开 —— 这正是初版测试夹具出错的地方（把 `OFFLINE_URL`
    写成了 `"OFFLINE_URL"`，于是它被当作 URL 字面量、常量引用路径根本没被测到）：

    - `RAW:xxx`      → 原样写入（用于构造畸形条目，验证脚本会显式报错）
    - `CONST_NAME`   → **不加引号**，即常量引用（真实 sw.js 里 `OFFLINE_URL` 就是这样）
    - 其余            → 加引号，即 URL 字面量
    """
    if entry.startswith("RAW:"):
        return f"    {entry[4:]},"
    if re.fullmatch(r"[A-Z][A-Z0-9_]*", entry):
        return f"    {entry},"
    return f'    "{entry}",'


def _build_fixture(
    tmp_path: Path,
    *,
    app_version: str = "0.1.0",
    sw_version: str | None = None,
    shell_entries: tuple[str, ...] = ("/", "/static/app.js"),
    manifest: object | None = None,
    extra_static: tuple[str, ...] = ("app.js",),
) -> dict[str, Path]:
    """在 tmp_path 下造一个最小可用的假仓库，返回 check_all() 的关键字参数。

    ⚠ SHELL_ASSETS 的数组收尾必须是 `\\n];`（脚本的 SHELL_ARRAY_RE 依赖这个换行）。
    """
    app_dir = tmp_path / "src" / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "__init__.py").write_text(f'__version__ = "{app_version}"\n', encoding="utf-8")
    (app_dir / "main.py").write_text('@app.get("/")\ndef index() -> None: ...\n', encoding="utf-8")

    static_dir = tmp_path / "static"
    static_dir.mkdir(exist_ok=True)
    for name in extra_static:
        (static_dir / name).write_text("// stub\n", encoding="utf-8")

    entries = "\n".join(_render_entry(e) for e in shell_entries)
    (static_dir / "sw.js").write_text(
        SW_TEMPLATE.format(version=sw_version or f"v{app_version}", entries=entries),
        encoding="utf-8",
    )

    if manifest is None:
        manifest = {
            "start_url": "/",
            "shortcuts": [{"name": "主页", "url": "/"}],
            "icons": [{"src": "/static/app.js"}],
        }
    (static_dir / "manifest.json").write_text(
        manifest if isinstance(manifest, str) else json.dumps(manifest),
        encoding="utf-8",
    )

    return {
        "init_py": app_dir / "__init__.py",
        "main_py": app_dir / "main.py",
        "sw_js": static_dir / "sw.js",
        "manifest": static_dir / "manifest.json",
        "static_dir": static_dir,
    }


# ─────────────────────────── 负向：门禁必须会报错 ───────────────────────────


def test_detects_sw_version_mismatch(tmp_path: Path) -> None:
    """V0.78.1 的核心缺陷：SW 缓存版本落后于应用版本。"""
    kwargs = _build_fixture(tmp_path, app_version="0.78.1", sw_version="v0.77.1")
    problems, info = check_pwa_assets.check_all(**kwargs)

    assert info.sw_version == "v0.77.1"
    assert info.expected == "v0.78.1"
    assert any("VERSION" in p and "0.77.1" in p for p in problems), problems


def test_detects_shell_asset_pointing_to_missing_file(tmp_path: Path) -> None:
    """SHELL_ASSETS 里的 /static/ 文件不存在 —— 会导致 addAll 整批回滚。"""
    kwargs = _build_fixture(tmp_path, shell_entries=("/", "/static/gone.js"))
    problems, _ = check_pwa_assets.check_all(**kwargs)

    assert any("/static/gone.js" in p and "文件不存在" in p for p in problems), problems


def test_detects_shell_asset_on_unregistered_route(tmp_path: Path) -> None:
    """非 /static/ 的路径必须能在 main.py 路由表里找到。"""
    kwargs = _build_fixture(tmp_path, shell_entries=("/", "/no-such-page"))
    problems, _ = check_pwa_assets.check_all(**kwargs)

    assert any("/no-such-page" in p and "未注册路由" in p for p in problems), problems


def test_detects_manifest_shortcut_404(tmp_path: Path) -> None:
    """V0.78.1 修掉的真实缺陷：快捷方式指向服务端不存在的 /silver。"""
    kwargs = _build_fixture(
        tmp_path,
        manifest={
            "start_url": "/",
            "shortcuts": [{"name": "白银", "url": "/silver"}],
            "icons": [{"src": "/static/app.js"}],
        },
    )
    problems, _ = check_pwa_assets.check_all(**kwargs)

    assert any("/silver" in p and "未注册路由" in p for p in problems), problems


def test_detects_manifest_missing_start_url(tmp_path: Path) -> None:
    kwargs = _build_fixture(tmp_path, manifest={"icons": []})
    problems, info = check_pwa_assets.check_all(**kwargs)

    assert any("缺少 start_url" in p for p in problems), problems
    assert info.manifest_counts["start_url"] == 0


def test_detects_manifest_invalid_json(tmp_path: Path) -> None:
    kwargs = _build_fixture(tmp_path, manifest="{ this is not json")
    problems, _ = check_pwa_assets.check_all(**kwargs)

    assert any("不是合法 JSON" in p for p in problems), problems


def test_unparseable_shell_entry_raises(tmp_path: Path) -> None:
    """无法解析的条目必须**显式报错**，而不是静默跳过。

    脚本的既定口径是「遇到解析不了的写法直接 raise」—— 静默漏检比误报危险得多。
    """
    kwargs = _build_fixture(tmp_path, shell_entries=("/", "RAW:SOME_EXPR + 1"))
    with pytest.raises(SystemExit):
        check_pwa_assets.check_all(**kwargs)


def test_unknown_const_reference_raises(tmp_path: Path) -> None:
    """引用了未定义的常量也要报错（只支持 `const X = "...";` 的简单形式）。"""
    kwargs = _build_fixture(tmp_path, shell_entries=("/", "UNDEFINED_URL"))
    with pytest.raises(SystemExit):
        check_pwa_assets.check_all(**kwargs)


# ─────────────────────────── 正向：干净输入必须通过 ───────────────────────────


def test_clean_fixture_passes(tmp_path: Path) -> None:
    """全部正确时不得报出任何问题（否则门禁会误报，误报会让人失去信任）。"""
    kwargs = _build_fixture(tmp_path)
    problems, info = check_pwa_assets.check_all(**kwargs)

    assert problems == []
    assert info.sw_version == "v0.1.0"
    assert info.shell_urls == ["/", "/static/app.js"]


def test_shell_entry_referencing_const_is_expanded(tmp_path: Path) -> None:
    """`OFFLINE_URL` 这类常量引用要展开成真实 URL 后再校验。

    ⚠ 这正是本门禁第一个容易出错的地方：用正则抓字面量字符串会**漏掉符号引用**
    （真实仓库里 OFFLINE_URL 对应的 /static/offline.html 就是这样一条）。
    """
    kwargs = _build_fixture(
        tmp_path,
        shell_entries=("/", "OFFLINE_URL"),
        extra_static=("app.js", "offline.html"),
    )
    problems, info = check_pwa_assets.check_all(**kwargs)

    assert problems == []
    assert "/static/offline.html" in info.shell_urls


# ──────────────────────── 金标准：锁住真实仓库的现状 ────────────────────────


def test_real_repo_passes() -> None:
    """真实仓库当前必须通过 —— 本门禁已接入 CI，它是「PWA 资源一致性」的基线。"""
    problems, info = check_pwa_assets.check_all()
    assert problems == [], problems
    assert info.shell_urls, "SHELL_ASSETS 不应为空"


def test_real_repo_sw_version_matches_app_version() -> None:
    """V0.78.1 的修复本身必须被锁住：两个版本号不得再脱钩。

    ⚠ 注意与 `static/dashboard.js` 的同名 VERSION 区分 —— 那个是**布局 schema 锚**，
       改了会重置老用户布局，不可跟着发版走。
    """
    _, info = check_pwa_assets.check_all()
    assert info.sw_version == info.expected


def test_restful_nav_entries_are_precached() -> None:
    """这 6 条导航入口必须以 **RESTful 形式**留在 SHELL_ASSETS 里。

    它们看着「绕了一道」——请求 `/portfolio` 会 307 到 `/static/portfolio.html`，
    于是很自然会被当成冗余项「优化」成直连地址。但那样会**破坏离线能力**：

    `sw.js` 的 fetch 分支里，HTML 页面走 network-first，离线兜底是
    `caches.match(request)` —— 而 `request.url` 就是用户地址栏里的 `/portfolio`。
    所以缓存 key 必须是 `/portfolio` 才可能命中；改成 `/static/portfolio.html` 后，
    离线访问 `/portfolio` 查不到缓存，直接落到 `offline.html`。

    （`cache.addAll` 会跟随 307，并以**原始 URL** 为 key 缓存最终响应体。）
    """
    _, info = check_pwa_assets.check_all()
    for entry in RESTFUL_NAV_ENTRIES:
        assert entry in info.shell_urls, f"{entry} 不在 SHELL_ASSETS 中：{info.shell_urls}"


def test_rel_handles_path_outside_repo(tmp_path: Path) -> None:
    """`_rel()` 对仓库外路径不得抛 ValueError（check_deps.py 曾踩过这个坑）。"""
    outside = tmp_path / "outside" / "sw.js"
    assert check_pwa_assets._rel(outside) == outside.as_posix()
