"""静态页面内联 JS 质量门禁。

本项目前端为「纯静态 HTML + 内联 ``<script>`` + 少量共享 JS」结构（无构建步骤），
因此 HTML 里的 JS 语法错误不会有任何编译期拦截——一旦写错，
整个页面的脚本块会全部失效（按钮无响应、数据不加载），
而服务端日志与后端测试都完全正常，极易漏到线上。

本脚本补齐这一环，做四件事：

1. **语法校验**：抽取每个 ``static/**/*.html`` 的内联脚本，用 ``node --check`` 校验；
   并同样校验 ``static/**/*.js`` 共享脚本（freshness / help / account）；
2. **未定义调用检查**：静态比对函数调用与本地声明，揪出拼错的函数名；
3. **DOM id 一致性检查**：``getElementById("x")`` 引用的 id 必须真实存在于 HTML
   （共享脚本运行时注入的 id 通过 ``.id = "x"`` 赋值语句识别，见 :func:`_shared_js_ids`）；
4. **退出码**：0 = 全部通过；1 = 存在问题（可直接接入 CI / pre-commit）。

用法::

    python scripts/check_static_js.py            # 自动探测 node
    python scripts/check_static_js.py <node路径>  # 显式指定 node
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")

SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S)
ID_RE = re.compile(r'\bid="([^"]+)"')
# 只认「字面量 id」：getElementById("foo")；排除动态拼接 getElementById("t_" + k)
GET_ID_RE = re.compile(r'getElementById\(\s*"([^"]+)"\s*\)')
FUNC_DEF_RE = re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)")
VAR_DEF_RE = re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=")
CLASS_DEF_RE = re.compile(r"\bclass\s+([A-Za-z_$][\w$]*)")
# 对象字面量里的方法简写：`  num(n, digits = 1) {`
SHORTHAND_DEF_RE = re.compile(r"\n\s*([A-Za-z_$][\w$]*)\s*\([^()]*\)\s*\{")
CALL_RE = re.compile(r"(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(")
# 动态 id 前缀：getElementById("c_" + k) / id="${"c_" + k}"  → 记下 "c_" 前缀
DYN_PREFIX_RE = re.compile(r'"([A-Za-z_$][\w$]*_)"\s*\+')
# 共享脚本运行时注入的 id：el.id = "accountSelect"
SHARED_ID_RE = re.compile(r"\.id\s*=\s*[\"']([^\"']+)[\"']")

# 宿主/浏览器全局与语言关键字——不属于「项目内应定义」的符号
GLOBALS = {
    "if", "else", "return", "typeof", "new", "delete", "void", "in", "of",
    "instanceof", "await", "async", "catch", "try", "finally", "throw",
    "switch", "case", "default", "break", "continue", "do", "while", "for",
    # 匿名函数表达式 `function (c) {}` 会被 CALL_RE 误认为调用名为 function 的函数
    "function", "get", "set",
    "Number", "String", "Boolean", "Array", "Object", "JSON", "Math", "Date",
    "RegExp", "Error", "Promise", "Map", "Set", "Symbol", "WeakMap", "Proxy",
    "Reflect", "BigInt", "Function", "parseFloat", "parseInt", "isNaN",
    "isFinite", "encodeURIComponent", "decodeURIComponent", "setTimeout",
    "setInterval", "clearTimeout", "clearInterval", "alert", "confirm",
    "prompt", "document", "window", "console", "localStorage",
    "sessionStorage", "fetch", "require", "module", "exports", "Chart",
    "Blob", "URL", "Intl", "Notification", "getComputedStyle",
    "requestAnimationFrame", "addEventListener", "FileReader",
    "CustomEvent", "Event", "AbortController", "queueMicrotask",
    "matchMedia", "dispatchEvent",
}

# 写在 JS 字符串里的 CSS 函数（如 Chart.js 配色 "rgba(...)"、"var(--up)"），
# 不是 JS 调用，需排除，否则产生大量误报。
CSS_FUNCS = {
    "var", "rgba", "rgb", "hsl", "hsla", "calc", "min", "max", "clamp", "env",
    "url", "translateX", "translateY", "translate", "scale", "rotate",
    "linear-gradient", "radial-gradient", "cubic-bezier", "blur", "brightness",
    "drop-shadow", "repeat", "circle", "polygon", "fit-content", "inset",
    "conic-gradient", "perspective", "matrix", "saturate", "sepia",
}


def _find_node() -> str | None:
    """按 PATH → 常见托管路径的顺序查找 node。"""
    found = shutil.which("node")
    if found:
        return found
    candidates = glob.glob(
        os.path.expanduser("~/.workbuddy/binaries/node/versions/*/node.exe")
    )
    return sorted(candidates)[-1] if candidates else None


def _inline_scripts(html: str) -> list[str]:
    return [b for b in SCRIPT_RE.findall(html) if b.strip()]


def _shared_js_ids() -> set[str]:
    """共享脚本（``static/*.js``）在运行时注入的 DOM id。

    例：``account.js`` 动态创建账本切换器并 ``sel.id = "accountSelect"``，
    页面脚本再 ``getElementById("accountSelect")``——静态看 HTML 里没有该 id，
    若不识别会造成误报。
    """
    ids: set[str] = set()
    for path in glob.glob(os.path.join(STATIC_DIR, "**", "*.js"), recursive=True):
        try:
            with open(path, encoding="utf-8") as fh:
                ids |= set(SHARED_ID_RE.findall(fh.read()))
        except OSError:  # pragma: no cover - 读取失败不影响其余检查
            continue
    return ids


def _node_syntax_error(path: str, node: str) -> str | None:
    """用 ``node --check`` 校验文件语法；返回错误首行，通过则返回 None。"""
    res = subprocess.run([node, "--check", path], capture_output=True, text=True)
    if res.returncode == 0:
        return None
    detail = (res.stdout + res.stderr).strip().splitlines()
    return detail[0] if detail else "语法错误"


def _declared_names(js: str) -> set[str]:
    """收集脚本内所有本地声明名（函数 / 变量 / 解构 / 回调参数）。"""
    names = set(FUNC_DEF_RE.findall(js))
    names |= set(VAR_DEF_RE.findall(js))
    names |= set(CLASS_DEF_RE.findall(js))
    names |= set(SHORTHAND_DEF_RE.findall(js))

    # 函数与箭头函数的形参
    for params in re.findall(r"function[^(]*\(([^)]*)\)", js):
        for p in params.split(","):
            p = p.strip()
            if re.fullmatch(r"[A-Za-z_$][\w$]*", p):
                names.add(p)
    for params in re.findall(r"\(([^)]*)\)\s*=>", js):
        for p in params.split(","):
            p = p.strip()
            if re.fullmatch(r"[A-Za-z_$][\w$]*", p):
                names.add(p)
    for p in re.findall(r"\b([A-Za-z_$][\w$]*)\s*=>", js):
        names.add(p)
    # 数组 / 对象解构
    for group in re.findall(r"(?:const|let|var)\s*\[([^\]]+)\]\s*=", js):
        for p in group.split(","):
            p = p.strip()
            if re.fullmatch(r"[A-Za-z_$][\w$]*", p):
                names.add(p)
    for group in re.findall(r"(?:const|let|var)\s*\{([^}]+)\}\s*=", js):
        for p in group.split(","):
            p = p.split(":")[-1].strip()
            if re.fullmatch(r"[A-Za-z_$][\w$]*", p):
                names.add(p)
    # for 循环变量
    names |= set(re.findall(r"for\s*\(\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)", js))
    return names


def _check_file(path: str, node: str | None) -> list[str]:
    """校验单个 HTML，返回问题描述列表（空列表 = 通过）。"""
    problems: list[str] = []
    rel = os.path.relpath(path, PROJECT_ROOT)
    with open(path, encoding="utf-8") as fh:
        html = fh.read()
    blocks = _inline_scripts(html)

    if not blocks:
        return problems

    # 1) 语法校验
    if node:
        for i, block in enumerate(blocks):
            with tempfile.NamedTemporaryFile(
                "w", suffix=".js", encoding="utf-8", delete=False
            ) as fh:
                fh.write(block)
                tmp = fh.name
            try:
                err = _node_syntax_error(tmp, node)
                if err:
                    problems.append(f"{rel} 内联脚本 #{i} 语法错误：{err}")
            finally:
                os.unlink(tmp)

    js = "\n".join(blocks)

    # 2) 未定义函数调用
    declared = _declared_names(js)
    called = set(CALL_RE.findall(js))
    undefined = sorted(
        c for c in called
        if c not in declared
        and c not in GLOBALS
        and c not in CSS_FUNCS
        and not c[0].isupper()
    )
    if undefined:
        problems.append(
            f"{rel} 疑似调用了未定义的函数：{', '.join(undefined)}"
        )

    # 3) DOM id 一致性
    # 动态拼接生成的 id（如 rowHtml("c_" + k, ...)）无法静态判定，
    # 命中已知前缀的一律放过，避免误报。
    ids_defined = set(ID_RE.findall(html)) | _shared_js_ids()
    ids_used = set(GET_ID_RE.findall(js))
    dyn_prefixes = tuple(set(DYN_PREFIX_RE.findall(js)))
    missing = sorted(
        i for i in ids_used - ids_defined
        if not (dyn_prefixes and i.startswith(dyn_prefixes))
    )
    if missing:
        problems.append(
            f"{rel} JS 引用了 HTML 中不存在的 id：{', '.join(missing)}"
        )

    return problems


def main(argv: list[str]) -> int:
    node = argv[1] if len(argv) > 1 else _find_node()
    if not node:
        print("[warn] 未找到 node，跳过语法校验（仅做静态引用检查）")

    files = sorted(glob.glob(os.path.join(STATIC_DIR, "**", "*.html"), recursive=True))
    if not files:
        print(f"[error] 未找到静态页面：{STATIC_DIR}")
        return 1

    all_problems: list[str] = []
    for path in files:
        problems = _check_file(path, node)
        all_problems.extend(problems)
        rel = os.path.relpath(path, PROJECT_ROOT)
        mark = "FAIL" if problems else "OK  "
        print(f"  [{mark}] {rel}")

    # 共享脚本同样需要语法校验（此前只检查内联脚本，外部 .js 是盲区）
    js_files = sorted(glob.glob(os.path.join(STATIC_DIR, "**", "*.js"), recursive=True))
    for path in js_files:
        rel = os.path.relpath(path, PROJECT_ROOT)
        err = _node_syntax_error(path, node) if node else None
        if err:
            all_problems.append(f"{rel} 语法错误：{err}")
            print(f"  [FAIL] {rel}")
        else:
            print(f"  [OK  ] {rel}")

    print()
    if all_problems:
        print(f"[FAIL] 发现 {len(all_problems)} 个问题：")
        for p in all_problems:
            print(f"  - {p}")
        return 1

    print(
        f"[OK] {len(files)} 个静态页面内联脚本 + {len(js_files)} 个共享脚本全部通过"
        "（语法 / 引用 / DOM id）"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
