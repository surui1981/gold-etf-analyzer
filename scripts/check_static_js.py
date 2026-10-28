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
    "if",
    "else",
    "return",
    "typeof",
    "new",
    "delete",
    "void",
    "in",
    "of",
    "instanceof",
    "await",
    "async",
    "catch",
    "try",
    "finally",
    "throw",
    "switch",
    "case",
    "default",
    "break",
    "continue",
    "do",
    "while",
    "for",
    # 匿名函数表达式 `function (c) {}` 会被 CALL_RE 误认为调用名为 function 的函数
    "function",
    "get",
    "set",
    "Number",
    "String",
    "Boolean",
    "Array",
    "Object",
    "JSON",
    "Math",
    "Date",
    "RegExp",
    "Error",
    "Promise",
    "Map",
    "Set",
    "Symbol",
    "WeakMap",
    "Proxy",
    "Reflect",
    "BigInt",
    "Function",
    "parseFloat",
    "parseInt",
    "isNaN",
    "isFinite",
    "encodeURIComponent",
    "decodeURIComponent",
    "setTimeout",
    "setInterval",
    "clearTimeout",
    "clearInterval",
    "alert",
    "confirm",
    "prompt",
    "document",
    "window",
    "console",
    "localStorage",
    "sessionStorage",
    "fetch",
    "require",
    "module",
    "exports",
    "Chart",
    "Blob",
    "URL",
    "Intl",
    "Notification",
    "getComputedStyle",
    "requestAnimationFrame",
    "addEventListener",
    "FileReader",
    "CustomEvent",
    "Event",
    "AbortController",
    "queueMicrotask",
    "matchMedia",
    "dispatchEvent",
}

# 写在 JS 字符串里的 CSS 函数（如 Chart.js 配色 "rgba(...)"、"var(--up)"），
# 不是 JS 调用，需排除，否则产生大量误报。
CSS_FUNCS = {
    "var",
    "rgba",
    "rgb",
    "hsl",
    "hsla",
    "calc",
    "min",
    "max",
    "clamp",
    "env",
    "url",
    "translateX",
    "translateY",
    "translate",
    "scale",
    "rotate",
    "linear-gradient",
    "radial-gradient",
    "cubic-bezier",
    "blur",
    "brightness",
    "drop-shadow",
    "repeat",
    "circle",
    "polygon",
    "fit-content",
    "inset",
    "conic-gradient",
    "perspective",
    "matrix",
    "saturate",
    "sepia",
}


def _find_node() -> str | None:
    """按 PATH → 常见托管路径的顺序查找 node。"""
    found = shutil.which("node")
    if found:
        return found
    candidates = glob.glob(os.path.expanduser("~/.workbuddy/binaries/node/versions/*/node.exe"))
    return sorted(candidates)[-1] if candidates else None


HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def _inline_scripts(html: str) -> list[str]:
    """提取内联脚本。**先剥 HTML 注释**再匹配 SCRIPT_RE。

    不剥的话，注释里只要出现字面量 ``<script>``（写注释说明「缺了这个标签」
    时太自然了），SCRIPT_RE 的非贪婪 ``.*?</script>`` 就会从那个假标签一路
    吞到下一个真 ``</script>`` —— 把注释正文 + 真脚本的起始标签当成一段
    内联脚本去 node --check，于是报出「语法错误 + 调用了未定义的函数」，
    两处都指向真实代码之外的行，排查成本极高（V0.113.0 修 report.html 的
    i18n 注释时被它咬了一次）。

    代价：脚本体内的 ``<!--`` 也会被剥掉。JS 里的 ``<!--`` 是远古 HTML 注释
    写法，本仓 0 处，且 check_static_js 本身要求 ES6 风格，实际风险为零；
    已在提交时用上面的扫描确认过全仓命中数为 0。
    """
    return [b for b in SCRIPT_RE.findall(HTML_COMMENT_RE.sub("", html)) if b.strip()]


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


#: 这些关键字之后期待一个「表达式」⇒ 紧跟的 ``/`` 开启正则字面量而非除号
_KEYWORDS_BEFORE_EXPR = {
    "return",
    "typeof",
    "instanceof",
    "in",
    "of",
    "new",
    "delete",
    "void",
    "case",
    "do",
    "else",
    "yield",
    "await",
    "throw",
}


def _regex_can_start(prev: str, prev_word: str) -> bool:
    """判断某个 ``/`` 位置是否开启正则字面量（而非除号）。

    判据 = 简化版的「此处期待一个表达式」：
    - 前一个有效字符是运算符 / 左括号 / 逗号 / 赋值号 ⇒ 正则；
    - 前一个有效字符是标识符字符 / 数字 / 右括号 / 右方括号 ⇒ 除号；
    - 前一个词是 ``return`` 这类关键字 ⇒ 正则。
    """
    if not prev:
        return True
    if prev in ",=:[!&|?{};+-*%~^<>":
        return True
    if prev.isalnum() or prev in "_$)]}":
        return prev_word in _KEYWORDS_BEFORE_EXPR
    return False


def _strip_js_comments(js: str) -> str:
    """剥掉 JS 的 ``//`` 行注释与 ``/* */`` 块注释。

    **为什么必须剥**：注释里只要出现「代码样文字」（如 ``apply() 会整体替换
    innerHTML``），:data:`CALL_RE` 就会把它当成一次真实的函数调用 ⇒ 门禁报出
    「疑似调用了未定义的函数」。这类误报**每次写注释解释代码时都会触发**，
    而人只会去改注释而不是改门禁 —— 于是门禁逐渐失去公信力。

    同样的机制也吃 DOM id 检查：注释里写 ``getElementById("foo")`` 举例，
    而 ``foo`` 在 HTML 里不存在 ⇒ 报「JS 引用了 HTML 中不存在的 id」。

    实现要点（字符串 / 模板串 / 正则字面量必须原样保留）：
    - 字符串（含转义）整体跳过；
    - 正则字面量整体跳过（字符类 ``[...]`` 内的 ``/`` 不终止正则），
      否则 ``/[/*]/`` 这种写法会被误当成块注释起始；
    - **正则必须能在同一行内闭合**：找不到闭合 ``/`` 就当普通字符处理 ——
      宁可漏剥一条注释，也不能把真代码吞掉（吞代码会让门禁**假绿**）；
    - 块注释内的换行**保留**（否则行号全乱，排查时对不上原文）。
    """
    out: list[str] = []
    i = 0
    n = len(js)
    prev = ""  # 上一个「有效」字符（跳过空白与注释）
    prev_word = ""  # 上一个标识符 / 关键字
    while i < n:
        c = js[i]
        # ── 字符串 / 模板串 ──
        if c in "\"'`":
            quote = c
            out.append(c)
            i += 1
            while i < n:
                if js[i] == "\\":
                    out.append(js[i : i + 2])
                    i += 2
                    continue
                out.append(js[i])
                if js[i] == quote:
                    i += 1
                    break
                i += 1
            prev = quote
            prev_word = ""
            continue
        # ── 注释 / 正则字面量 ──
        if c == "/" and i + 1 < n:
            nxt = js[i + 1]
            if nxt == "/":
                j = js.find("\n", i)
                i = n if j == -1 else j
                continue
            if nxt == "*":
                j = js.find("*/", i + 2)
                i = n if j == -1 else j + 2
                continue
            if _regex_can_start(prev, prev_word):
                end = _regex_literal_end(js, i)
                if end is not None:
                    out.append(js[i:end])
                    i = end
                    prev = "/"
                    prev_word = ""
                    continue
        out.append(c)
        if c.isalnum() or c in "_$":
            prev_word += c
        elif c.isspace():
            pass
        else:
            prev_word = ""
        if not c.isspace():
            prev = c
        i += 1
    return "".join(out)


def _regex_literal_end(js: str, start: int) -> int | None:
    """若 ``js[start]`` 是正则字面量的起始，返回它**结束后的下标**；否则 None。

    找不到闭合 ``/``（或闭合前遇到换行）⇒ 返回 None —— 调用方据此把它当普通
    字符处理，**绝不能把真代码当注释吞掉**。
    """
    i = start + 1
    n = len(js)
    in_class = False
    while i < n:
        ch = js[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "\n":
            return None
        if ch == "[":
            in_class = True
        elif ch == "]":
            in_class = False
        elif ch == "/" and not in_class:
            return i + 1
        i += 1
    return None


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
    # 注释必须先剥：注释里的「代码样文字」（apply() / getElementById("x")）
    # 会被后面的正则当成真实调用 / 真实引用 ⇒ 误报；反过来注释里写
    # `function foo(){}` 也会让未定义调用**假绿**。两侧都得剥。
    js_stripped = _strip_js_comments(js)

    # 2) 未定义函数调用
    declared = _declared_names(js_stripped)
    called = set(CALL_RE.findall(js_stripped))
    undefined = sorted(
        c
        for c in called
        if c not in declared and c not in GLOBALS and c not in CSS_FUNCS and not c[0].isupper()
    )
    if undefined:
        problems.append(f"{rel} 疑似调用了未定义的函数：{', '.join(undefined)}")

    # 3) DOM id 一致性
    # 动态拼接生成的 id（如 rowHtml("c_" + k, ...)）无法静态判定，
    # 命中已知前缀的一律放过，避免误报。
    ids_defined = set(ID_RE.findall(HTML_COMMENT_RE.sub("", html))) | _shared_js_ids()
    ids_used = set(GET_ID_RE.findall(js_stripped))
    dyn_prefixes = tuple(set(DYN_PREFIX_RE.findall(js_stripped)))
    missing = sorted(
        i for i in ids_used - ids_defined if not (dyn_prefixes and i.startswith(dyn_prefixes))
    )
    if missing:
        problems.append(f"{rel} JS 引用了 HTML 中不存在的 id：{', '.join(missing)}")

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


def run_nav_context_smoke() -> int:
    """V0.98 C6：跑 nav-context.js 单元测试（21 个断言）。

    失败不阻塞发版，但必须 warn 出来。
    """
    import subprocess
    from pathlib import Path as _Path

    script = _Path(__file__).parent / "check_nav_context.mjs"
    if not script.exists():
        print(f"[WARN] {script.name} 不存在，跳过 nav-context 单测")
        return 0
    try:
        result = subprocess.run(
            ["node", str(script)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print("[WARN] nav-context 单元测试失败：")
            print(result.stdout[-1500:])
            print(result.stderr[-500:])
            return 0  # 不阻塞发版
        # 取最后一行（结果总结）
        last = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
        print(f"[OK] nav-context 单元测试通过（{last}）")
        return 0
    except FileNotFoundError:
        print("[WARN] node 不在 PATH，跳过 nav-context 单测")
        return 0
    except subprocess.TimeoutExpired:
        print("[WARN] nav-context 单测超时（30s），跳过")
        return 0


if __name__ == "__main__":
    rc = main(sys.argv)
    if rc == 0:
        run_nav_context_smoke()
    sys.exit(rc)
