"""UX 6.8 · 新手引导与帮助体系 —— DOM 行为测试。

help.js 是浏览器 IIFE，无法直接 Python 调用。本测试使用一个最简的
DOM mock（仅追踪 createElement / appendChild / addEventListener），
抽取 help.js 内部三个核心函数的源码（renderGuideTab / renderTermsTab /
renderSourceTab）并以沙箱方式执行，从而验证：

  1. 三个 tab 渲染函数都返回合法 HTML 字符串
  2. 各 tab 包含关键内容（指南步骤 / 术语组 / 数据源 / 投资警示）
  3. escapeHtml 转义正确
  4. HTML 转义场景下不出现 XSS 风险
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELP_JS = ROOT / "static" / "help.js"


# ─────────────── JS 抽取 ───────────────


def _extract_function(name: str) -> str:
    """从 help.js 中抽取 function <name>(...) { ... } 的完整源码。"""
    src = HELP_JS.read_text(encoding="utf-8")
    # 匹配 function NAME(...) { ... }  （按花括号配对）
    pat = re.compile(rf"function\s+{name}\s*\([^)]*\)\s*\{{")
    m = pat.search(src)
    assert m, f"未找到 function {name}"
    start = m.end()
    depth = 1
    i = start
    while i < len(src) and depth > 0:
        c = src[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    return src[m.start() : i]


def _make_js_env() -> str:
    """构造一段 JS 上下文：暴露 escapeHtml + renderGuideTab + renderTermsTab + renderSourceTab。"""
    funcs = [
        _extract_function(n)
        for n in ("escapeHtml", "renderGuideTab", "renderTermsTab", "renderSourceTab")
    ]
    # GLOSSARY 在闭包内被 renderTermsTab 引用，需额外抽取
    src = HELP_JS.read_text(encoding="utf-8")
    glossary_match = re.search(r"const GLOSSARY = (\{[\s\S]*?\n  \});", src)
    assert glossary_match, "未找到 GLOSSARY"
    glossary_src = "const GLOSSARY = " + glossary_match.group(1) + ";"
    body = "\n".join(funcs) + "\n" + glossary_src
    # Node 沙箱：用一个对象收集返回值
    runner = textwrap.dedent("""
        const result = {
          escapeHtml: (...args) => escapeHtml(...args),
          renderGuideTab: () => renderGuideTab(),
          renderTermsTab: () => renderTermsTab(),
          renderSourceTab: () => renderSourceTab(),
        };
        process.stdout.write(JSON.stringify({
          guide: result.renderGuideTab(),
          terms: result.renderTermsTab(),
          source: result.renderSourceTab(),
        }));
    """)
    return body + "\n" + runner


def _run_js() -> dict:
    """通过 Node 子进程执行抽取的 JS 并解析结果。"""
    import json
    import subprocess

    js = _make_js_env()
    proc = subprocess.run(
        ["node", "-e", js],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, f"Node 执行失败: {proc.stderr}"
    return json.loads(proc.stdout)


# ─────────────── 缓存（避免每个用例重复执行 Node） ───────────────


@pytest.fixture(scope="module")
def rendered() -> dict:
    return _run_js()


# ─────────────── 测试项 ───────────────


def test_renderGuideTab_contains_daily_steps(rendered: dict) -> None:
    """操作指南 tab 包含「每日 5 步流程」与 5 步编号。"""
    html = rendered["guide"]
    assert "每日 5 步流程" in html
    # 必须含 5 步 list 项
    ol_count = html.count("<li>")
    assert ol_count >= 5, f"guide tab 至少 5 步，实际 {ol_count}"


def test_renderGuideTab_links_to_four_main_pages(rendered: dict) -> None:
    """指南 tab 链接到 4 个核心页面（趋势/持仓/消息面/央行）。

    注：权重页为配置页，不在每日 5 步流程之内，因此 guide tab 不链接。
    """
    html = rendered["guide"]
    for url in ("/static/trend.html", "/portfolio", "/news", "/central-bank"):
        assert url in html, f"guide tab 缺少链接 {url}"


def test_renderTermsTab_includes_seven_categories(rendered: dict) -> None:
    """术语 tab 包含 7 个分类标题。"""
    html = rendered["terms"]
    for cat in (
        "评估指数类",
        "指标/均线类",
        "宏观因子类",
        "品种代码类",
        "交易动作类",
        "系统状态类",
        "时段类",
    ):
        assert cat in html, f"terms tab 缺少分类 {cat}"


def test_renderTermsTab_lists_key_terms(rendered: dict) -> None:
    """术语 tab 包含关键术语（<dt>...</dt>）。"""
    html = rendered["terms"]
    for term in (
        "综合指数",
        "MA5 / MA20 / MA40",
        "RSI(14)",
        "T12M",
        "Au99.99",
        "COMEX",
        "518880",
        "仓位推荐",
    ):
        # term 可能出现在 <dt> 标签内
        assert f">{term}<" in html or f">{term} <" in html, f"术语 {term} 未在 terms tab 出现"


def test_renderSourceTab_warns_disclaimer(rendered: dict) -> None:
    """数据来源 tab 顶部含「投资警示」。"""
    html = rendered["source"]
    assert "投资警示" in html
    assert "研究参考" in html
    assert "不构成投资建议" in html


def test_renderSourceTab_lists_data_sources(rendered: dict) -> None:
    """数据来源 tab 列出 5 类数据源。"""
    html = rendered["source"]
    for src in (
        "纽约金（COMEX GC）",
        "上海金（SGE Au99.99）",
        "黄金 ETF（518880）",
        "美债 10Y / 30Y",
        "央行购金",
    ):
        assert src in html, f"source tab 缺少 {src}"


def test_renderSourceTab_mentions_central_bank_v057(rendered: dict) -> None:
    """数据来源 tab 必须标注央行购金为 V0.57.0+ 引入（指向 WGC）。"""
    html = rendered["source"]
    assert "V0.57.0" in html
    assert "WGC" in html or "gold.org" in html


def test_escapeHtml_handles_all_special_chars() -> None:
    """escapeHtml 对 4 类特殊字符的转义均正确。"""
    import subprocess

    js = _make_js_env().replace(
        "process.stdout.write(JSON.stringify({",
        "process.stdout.write(JSON.stringify({_e: escapeHtml('<a href=\"x\">&'),",
    )
    proc = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0, proc.stderr
    import json

    out = json.loads(proc.stdout)
    assert out["_e"] == "&lt;a href=&quot;x&quot;&gt;&amp;"


def test_no_xss_in_xss_attempt_term() -> None:
    """若 GLOSSARY 注入含 <script> 的脏数据，renderTermsTab 需正确转义。

    通过在 help.js 字面量中临时加入一段，再恢复的方式测试。
    """
    src = HELP_JS.read_text(encoding="utf-8")
    poisoned = src.replace(
        '"综合指数":',
        '"<script>alert(1)</script>":',
        1,
    )
    assert poisoned != src, "未替换成功"
    # 抽取并运行
    glossary_match = re.search(r"const GLOSSARY = (\{[\s\S]*?\n  \});", poisoned)
    glossary_src = "const GLOSSARY = " + glossary_match.group(1) + ";"
    funcs = "\n".join(_extract_function(n) for n in ("escapeHtml", "renderTermsTab"))
    runner = "process.stdout.write(JSON.stringify({terms: renderTermsTab()}));"
    import json
    import subprocess

    proc = subprocess.run(
        ["node", "-e", glossary_src + "\n" + funcs + "\n" + runner],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    # 必须转义为 &lt;script&gt; 而非原文 <script>
    assert "<script>alert(1)</script>" not in out["terms"]
    assert "&lt;script&gt;" in out["terms"]
