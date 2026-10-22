"""i18n key 全语种覆盖门禁。

背景：本项目前端为「纯静态 HTML」结构（无构建步骤），i18n 字符串直接写在
``static/i18n/{zh-CN,en-US,zh-TW}.js`` 三个 JS 对象里；HTML 通过
``data-i18n="key"`` / ``data-i18n-html="key"`` 引用。V0.83 commit 4 迁移 8
页面时，常见 bug 是「HTML 引用了新 key，zh-TW 忘加」—— 模板字符串 ``${x.prop}``
在 zh-TW 缺 key 时会静默渲染成空字符串或显示原始 key 字面（参考 MEMORY
``frontend-undefined-rendering.md``）。

本脚本做两件事：

1. **V0.83-touched key 3 语覆盖检查（严格，exit 1）**：检查 V0.83 commit 1-4
   引入 / 修改的所有 i18n key 在 3 语文件里都存在。这是 C4 的核心门禁，
   防 V0.83 重构期间静默回归。
2. **全量 HTML 引用扫描（软提示，不失败）**：扫描所有 ``static/**/*.html``
   提取 ``data-i18n`` / ``data-i18n-html`` 引用（含 ``key1|key2`` 回落链），
   报告所有 3 语缺失作为已知预存 gap（V0.83 之前的历史欠账，单独 ticket）。

退出码：0 = V0.83-touched key 全部覆盖；1 = 存在 V0.83-touched key 缺失。

用法::

    python scripts/check_i18n_keys.py            # 默认 V0.83-scope（严格）
    python scripts/check_i18n_keys.py --all      # 全量扫描（仅报告，不退出码 1）
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
STATIC_DIR = os.path.join(ROOT, "static")
I18N_DIR = os.path.join(STATIC_DIR, "i18n")
LANGS = ["zh-CN", "en-US", "zh-TW"]

# data-i18n / data-i18n-html 属性值
ATTR_RE = re.compile(r'data-i18n(?:-html)?="([^"]+)"')

# JS 对象里的 "key": "value" 定义（最简匹配，不处理嵌套转义——i18n 文件里没嵌套）
KEY_DEF_RE = re.compile(r'"([A-Za-z0-9_.\-]+)"\s*:\s*"')

# V0.83 commit 1-4 触及的 i18n key 前缀 / 命名空间。
# 这些 key 由 V0.83 重构引入或修改，必须在 3 语文件都存在（核心门禁）。
# 维护约定：每次新增 V0.83+ 命名空间时，同步加到此清单。
V083_KEY_PREFIXES = (
    # C1 (warning.js + theme.css + summary min-height)：无 i18n 新增
    # C2 (freshness diff + help.js dedup)：
    "help.source_warn_prompt",
    # C3 (8 页面迁移 warn-footer)：
    "warn.",                # warn.title / warn.b*_strong / warn.b*_rest / warn.collapse_toggle / warn.dismiss_session
    "central_bank.warn_",   # 央行页 4 项特定键（含 _pre/_wgc 后缀）
    "silver.warn_b",        # 白银页第 5 条特定键
    "backtest.warn_b",      # 回测页 5 条特定键
    "health.warn_b",        # 数据健康页 3 条 HTML 整段键
    # C3 brand / nav：topnav 整批迁移，沿用既有 namespace（已 3 语覆盖，仅在 HTML 引用）
    "brand.",
    "nav.",
    # V0.97.0：AI 智能分析页
    "ai.",
    # V0.100：消息面未打分 → 综合指数 pending（trend.html + silver.html 共用 trend.* namespace）
    "trend.",
    "silver.",
    # V0.102：今日要闻页（readhub 财经新闻流；nav + headlines.* 全 3 语覆盖）
    "headlines.",
    # V0.103：我的收藏（favorites.* 全 3 语覆盖，47 键 + nav.favorites + brand.favorites）
    "favorites.",
    # V0.111.0：报告存档（reports.* 全 3 语覆盖，49 键 + nav.archive + brand.archive）
    "reports.",
    # V0.112.0：命令面板（cmd.* 12 键 + nav.cmd_palette）
    #   文案由 command-palette.js 用 I18n.t() 取，缺键会静默回落到代码里的 fb 常量
    #   —— 也就是说「忘了加 zh-TW」不会报错，只会悄悄显示简体，所以必须进严格清单。
    "cmd.",
    # V0.115.0：首页贵金属走势区（home.* 整个 namespace 纳入，67 键，实测 3 语零缺口）
    "home.",
)


def is_v083_key(key: str) -> bool:
    """判断 key 是否属于 V0.83 触及的命名空间。"""
    for prefix in V083_KEY_PREFIXES:
        if key == prefix or key.startswith(prefix):
            return True
    return False


def extract_html_keys(static_dir: str) -> tuple[set[str], dict[str, set[str]]]:
    """返回 (所有引用 key, {key: {files using it}})。

    扫描两种来源：
    1. **HTML data-i18n 属性**（`data-i18n="key"` / `data-i18n-html="key"`，支持
       ``key1|key2`` 回落链）
    2. **JS 模板字面量**（V0.83.2 共享 topnav.js 把链接 / brand 的 i18n key 写在
       JS 数组里而非 HTML 模板——`{ i18n: "nav.trend" }`）—— 加 JS 扫描后，删除
       `nav.*` / `brand.*` key 仍会被门禁拦到。

    不扫描 i18n.js / i18n/*.js 自身（避免递归自引用）。
    """
    all_keys: set[str] = set()
    usage: dict[str, set[str]] = defaultdict(set)
    # 1) HTML data-i18n 属性
    for path in glob.glob(os.path.join(static_dir, "**", "*.html"), recursive=True):
        rel = os.path.relpath(path, static_dir)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        for m in ATTR_RE.finditer(content):
            raw = m.group(1).strip()
            for k in raw.split("|"):
                k = k.strip()
                if not k or k.startswith("{{"):
                    continue
                all_keys.add(k)
                usage[k].add(rel)
    # 2) JS 模板字面量（仅 static/*.js，避开 i18n/ 自身）
    js_attr_re = re.compile(r'i18n:\s*["\']([A-Za-z0-9_.\-]+)["\']')
    # V0.112.0：补 I18n.t('key') 形式。此前只扫 `i18n: "key"`（topnav.js 的 SCENES
    #   对象字面量），而 JS 里另一大类写法 —— 直接调 I18n.t('some.key') —— 扫不到：
    #   headlines.js 有 11 处、command-palette.js 有 12 处都落在门外。这些键要是某语
    #   漏了，门禁不报，运行时 I18n.t() 又会回落到 key 字面量 / 代码里的 fb 常量 ——
    #   两边都是「安静地显示错的东西」，正是本门禁要拦的那类静默回归。
    #   注意只认**字符串字面量**实参：I18n.t(item.i18n) / I18n.t(key) 这类变量形式
    #   扫不出来，也不该扫 —— 它们的 key 由别处（SCENES）已覆盖。
    js_call_re = re.compile(r'I18n\.t\(\s*["\']([A-Za-z0-9_.\-]+)["\']')
    # V0.112.0：补 tr('key', 'fallback') 形式。tr(key, fallback) 是本项目**既有的**
    #   i18n 约定（V0.86 decision-explainer.js 首用，本次 command-palette.js 沿用）——
    #   字典没命中就返回 fallback，而不是像 I18n.t 那样返回 key 字面量。
    #   此前这批键同样在门外：decision-explainer.js 约 15 个 decision.explain_*、
    #   command-palette.js 12 个 cmd.*，漏一语都不会报。
    #   实测 `tr(` 只出现在这两个文件里，且都是 i18n 用途，无同名误伤。
    tr_call_re = re.compile(r'\btr\(\s*["\']([A-Za-z0-9_.\-]+)["\']')
    for path in glob.glob(os.path.join(static_dir, "*.js")):
        rel = os.path.relpath(path, static_dir)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        for rx in (js_attr_re, js_call_re, tr_call_re):
            for m in rx.finditer(content):
                k = m.group(1)
                if not k:
                    continue
                all_keys.add(k)
                usage[k].add(rel)
    return all_keys, usage


def extract_defined_keys(i18n_dir: str) -> dict[str, set[str]]:
    """返回 {lang: {keys defined in file}}。"""
    defined: dict[str, set[str]] = {}
    for lang in LANGS:
        path = os.path.join(i18n_dir, f"{lang}.js")
        if not os.path.exists(path):
            print(f"[ERR] 缺失 i18n 文件：{path}", file=sys.stderr)
            sys.exit(2)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        keys = set(KEY_DEF_RE.findall(content))
        defined[lang] = keys
    return defined


def report_missing(missing: dict[str, list[str]], usage: dict[str, set[str]], title: str) -> int:
    """返回失败计数。"""
    fail = 0
    if not missing:
        print(f"\n  [OK]   {title}：全部覆盖")
        return 0
    for lang, keys in missing.items():
        for k in keys:
            files = ", ".join(sorted(usage[k]))
            print(f"  [FAIL] {lang}.js 缺失 key '{k}'  ::  used in {files}")
            fail += 1
    return fail


def check_dict_loaded() -> int:
    """有 data-i18n 的页必须引字典文件，否则整页渲染成 key 字面量。

    这不是「key 缺失」类的问题 —— key 在 3 语字典里全都有，门禁原本一路绿灯，
    而 /report 的正文当时直接显示着 `report.section_positions`。
    根因在 i18n.js:46：非默认语言会动态插 <script>，**唯独默认语言 zh-CN 走
    syncLoadDefault()**，只读 window.PM_I18N_ZH_CN，不自己去取字典文件。
    所以漏引字典文件这件事没有任何机制会报错，只能静态扫。
    """
    print("\n" + "-" * 70)
    print("字典文件加载检查（有 data-i18n 的页必须引 /static/i18n/zh-CN.js）")
    fail = 0
    scanned = 0
    for name in sorted(os.listdir(STATIC_DIR)):
        if not name.endswith(".html"):
            continue
        path = os.path.join(STATIC_DIR, name)
        with open(path, encoding="utf-8") as f:
            src = f.read()
        if "data-i18n" not in src:
            continue
        scanned += 1
        if "/static/i18n/zh-CN.js" not in src:
            print(f"  [FAIL] {name} 用了 data-i18n 但没引字典文件 → 整页会渲染成 key 字面量")
            fail += 1
    if not fail:
        print(f"  [OK]   {scanned} 个带 data-i18n 的页全部引了字典文件")
    return fail


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="扫描全部 HTML key（仅报告，不失败）")
    args = parser.parse_args()

    print("=" * 70)
    if args.all:
        print("i18n key 全量扫描（仅报告，不退出码 1）")
    else:
        print("V0.83 C4 · i18n key 3 语覆盖门禁（V0.83 命名空间严格模式）")
    print("=" * 70)

    defined = extract_defined_keys(I18N_DIR)
    used, usage = extract_html_keys(STATIC_DIR)

    for lang in LANGS:
        print(f"  [INFO] {lang}.js 定义 {len(defined[lang])} 个 key")
    print(f"  [INFO] HTML 引用去重后 {len(used)} 个 key")

    # 1) V0.83-touched key 严格覆盖检查（默认）/ 全量扫描（--all）
    if args.all:
        scope = used
        scope_label = "全量 HTML 引用"
    else:
        scope = {k for k in used if is_v083_key(k)}
        scope_label = f"V0.83 命名空间 (前缀 {len(V083_KEY_PREFIXES)} 类)"

    print(f"  [INFO] 扫描范围：{scope_label} = {len(scope)} 个 key")

    missing: dict[str, list[str]] = defaultdict(list)
    for k in sorted(scope):
        for lang in LANGS:
            if k not in defined[lang]:
                missing[lang].append(k)

    fail = report_missing(missing, usage, f"{scope_label} key 3 语覆盖")

    # 1b) 字典文件是否真的被页面加载（V0.113.0 新增）
    fail += check_dict_loaded()

    # 2) --all 模式额外报告 V0.83 namespace 之外的 gap（不失败）
    if args.all:
        out_of_scope = sorted(used - scope)
        if out_of_scope:
            print(f"\n  [INFO] V0.83 命名空间外 {len(out_of_scope)} 个 key（预存 gap，独立 ticket 跟踪）")

    # 3) 未使用 key 软提示（不失败）
    unused = set()
    for lang in LANGS:
        unused |= defined[lang] - used
    if unused:
        sample = sorted(unused)[:5]
        print(f"\n  [WARN] {len(unused)} 个 key 定义但 HTML 未引用（部分由 JS 动态拼接）")
        for k in sample:
            print(f"         - {k}")
        if len(unused) > 5:
            print(f"         ... +{len(unused) - 5} more")

    print("\n" + "=" * 70)
    print(f"结果：{fail} missing / {len(scope)} in-scope")
    print("=" * 70)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
