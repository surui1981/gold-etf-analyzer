"""数据时效条（freshness.js）引用一致性门禁。

背景（V0.121.2 · P0-6）
------------------------
``static/freshness.js`` 会**自启动**：加载即 fetch 一次
``/api/v1/market/freshness``，之后每 60 秒递归轮询，并把结果渲染进
``#freshnessBar`` / ``#freshnessInline`` 容器。

于是出现两类**静默失效**：

1. **页面引了脚本却没有容器** ⇒ 每 60 秒一次外网请求，拿到数据渲染到
   不存在的节点 ⇒ 纯浪费；读代码却像「本页有时效保护」⇒ 误导。
   （实测：``settings.html``）
2. **页面调了 ``window.FreshnessBar.load()`` 却没有引脚本** ⇒ 该对象恒为
   ``undefined`` ⇒ 守卫静默跳过 ⇒ **死代码**；读代码却像「本页会刷新时效」⇒ 误导。
   （实测：``portfolio.html`` / ``trades.html``）

本门禁把这两类不一致**变成可判红**的检查，而不是靠人工复核发现。

用法::

    python scripts/check_freshness_consistency.py

退出码：0 = 全部一致；1 = 存在不一致。
"""

from __future__ import annotations

import glob
import os
import re
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")

#: 引入 freshness.js 的写法（相对/绝对路径都算）
SCRIPT_TAG_RE = re.compile(r"""<script[^>]*\bsrc\s*=\s*["'][^"']*freshness\.js["'][^>]*>""")
#: 调用 window.FreshnessBar 的写法
BAR_CALL_RE = re.compile(r"\bwindow\s*\.\s*FreshnessBar\b")
#: 容器 id（freshness.js 只认这两个）
CONTAINER_IDS = ("freshnessBar", "freshnessInline")

#: 这两个 id **可能**是运行时注入的（由共享脚本创建）⇒ 静态扫不到时不算缺容器。
#: ⚠ 保守起见只放行**确实存在**的注入点；新增页面若用了别的容器 id 会被本门禁拦下。
RUNTIME_CONTAINER_ALLOWLIST: tuple[str, ...] = ()

#: HTML 注释（跨行）
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
#: JS 块注释（跨行）
BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
#: JS 行注释。
#: ⚠ **不能**用朴素的 ``//[^\n]*`` —— 它会把 ``https://cdn/x/freshness.js``
#:   截成 ``https:`` ⇒ 页面明明引了脚本，门禁却认为「没引」⇒ **假绿**
#:   （假绿比假红危险：假绿会让真缺陷永久放行）。
#: ⇒ 只在 ``//`` 前面是「空白 / 标点 / 行首」时才算注释；
#:   前面是 ``:``（协议）、``"``/``'``（字符串）、``\w``（标识符）时**保留原样**。
LINE_COMMENT_RE = re.compile(r"(?<![:\w'\"/])//[^\n]*")


def _html_files() -> list[str]:
    return sorted(glob.glob(os.path.join(STATIC_DIR, "*.html")))


def _strip_comments(html: str) -> str:
    """剥掉 HTML 注释 + JS 注释，只留**真代码**。"""
    out = HTML_COMMENT_RE.sub("", html)
    out = BLOCK_COMMENT_RE.sub("", out)
    out = LINE_COMMENT_RE.sub("", out)
    return out


def _has_container(html: str) -> bool:
    return any(re.search(rf'\bid\s*=\s*["\']{cid}["\']', html) for cid in CONTAINER_IDS)


def main() -> int:
    problems: list[str] = []
    checked = 0

    for path in _html_files():
        name = os.path.basename(path)
        with open(path, encoding="utf-8") as fh:
            html = fh.read()
        # ⚠ 注释里的引用不算（"summary 装 #freshnessInline + 警示计数 pill" 这类
        #   历史说明文字会被当成真容器 ⇒ 门禁假绿）。
        code = _strip_comments(html)

        loads_script = bool(SCRIPT_TAG_RE.search(code))
        calls_bar = bool(BAR_CALL_RE.search(code))
        has_container = _has_container(code)

        if loads_script or calls_bar:
            checked += 1

        if loads_script and not has_container:
            problems.append(
                f"{name}: 引入了 freshness.js 却没有容器 "
                f"({'/'.join(CONTAINER_IDS)}) ⇒ 脚本会每 60 秒空轮询一次外网接口并渲染到"
                f"不存在的节点（纯浪费 + 误导）。要么补容器，要么别引脚本。"
            )
        if calls_bar and not loads_script:
            problems.append(
                f"{name}: 调用了 window.FreshnessBar 却没有引入 freshness.js "
                f"⇒ 该对象恒为 undefined ⇒ 守卫静默跳过 ⇒ 死代码（读起来却像有时效保护）。"
            )

    print(f"扫描页面：{len(_html_files())} 个；涉及 freshness 的：{checked} 个")
    if problems:
        print(f"\n发现 {len(problems)} 处不一致：")
        for p in problems:
            print(f"  ✗ {p}")
        print("\n结果：FAILED")
        return 1
    print("  ✓ 所有页面的 freshness 引用一致（引了脚本就有容器；调了 API 就引了脚本）")
    print("\n结果：PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
