"""UX 6.8 · 新手引导与帮助体系 —— 静态数据完整性测试。

help.js 是浏览器端脚本，无法直接通过 pytest 在 Node 环境运行。
本文件通过对 help.js 的源码做正则解析，验证：

  1. 7 大类术语分组（GLOSSARY）至少 30+ 条
  2. 12 项关键术语 inline tooltip 配置完整（覆盖 5 页）
  3. 5 个 HTML 页面 tour 步骤至少各有 1 步
  4. 5 个 HTML 页面都正确注入 help.css + help.js
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELP_JS = ROOT / "static" / "help.js"
HELP_CSS = ROOT / "static" / "help.css"

EXPECTED_PAGES = [
    "/static/trend.html",
    "/portfolio",
    "/weights",
    "/news",
    "/central-bank",
]


# ─────────────── help.js 解析辅助 ───────────────


def _extract_const(name: str) -> str:
    """从 help.js 抽取出 const <NAME> = { ... };  字面量文本。"""
    src = HELP_JS.read_text(encoding="utf-8")
    m = re.search(rf"const\s+{name}\s*=\s*(\{{[\s\S]*?\n\s*\}});", src)
    assert m, f"未在 help.js 找到 const {name}"
    return m.group(1)


def _extract_balanced_object(text: str, key: str) -> dict:
    """从 help.js 字面量中抠出 KEY: { ... } 对应对象的 Python 字典近似。

    help.js 用双引号 + JS 对象字面量，这里只做粗粒度提取（行级解析）。
    """
    pat = re.compile(rf'"{re.escape(key)}"\s*:\s*\{{')
    m = pat.search(text)
    assert m, f"未在 help.js 找到对象 {key}"
    start = m.end()
    depth = 1
    i = start
    while i < len(text) and depth > 0:
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    body = text[start : i - 1]
    # 抽取 "term": "def" 形式
    entries: dict[str, str] = {}
    for tm in re.finditer(r'"([^"\\]+)"\s*:\s*"((?:[^"\\]|\\.)*)"', body):
        entries[tm.group(1)] = tm.group(2)
    return entries


def _extract_array_of_objects(text: str, key: str) -> list[dict]:
    """从 help.js 字面量中抠出 KEY: [ { ... }, ... ] 数组。"""
    pat = re.compile(rf'"{re.escape(key)}"\s*:\s*\[')
    m = pat.search(text)
    assert m, f"未在 help.js 找到数组 {key}"
    start = m.end()
    depth = 1
    i = start
    while i < len(text) and depth > 0:
        c = text[i]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
        i += 1
    body = text[start : i - 1]
    objs: list[dict] = []
    # 在 body 中切分顶层 {...}
    depth2 = 0
    obj_start = None
    for idx, ch in enumerate(body):
        if ch == "{":
            if depth2 == 0:
                obj_start = idx
            depth2 += 1
        elif ch == "}":
            depth2 -= 1
            if depth2 == 0 and obj_start is not None:
                obj_body = body[obj_start : idx + 1]
                obj: dict = {}
                for tm in re.finditer(r'(\w+)\s*:\s*"((?:[^"\\]|\\.)*)"', obj_body):
                    obj[tm.group(1)] = tm.group(2)
                objs.append(obj)
                obj_start = None
    return objs


# ─────────────── 测试项 ───────────────


def test_help_js_exists() -> None:
    """help.js 必须存在且非空。"""
    assert HELP_JS.exists(), "help.js 不存在"
    assert HELP_JS.stat().st_size > 1000, "help.js 太小，可能未完成"


def test_help_css_exists() -> None:
    """help.css 必须存在。"""
    assert HELP_CSS.exists(), "help.css 不存在"
    text = HELP_CSS.read_text(encoding="utf-8")
    # 至少包含 modal + 按钮 + tour 浮层三类样式
    assert "#pmHelpBtn" in text
    assert "#pmHelpModal" in text
    assert "#pmhTourMask" in text or "pmhTourMask" in text


def test_glossary_has_seven_categories() -> None:
    """GLOSSARY 至少 7 个核心分组（评估/指标/宏观/品种/交易/系统/时段）；V0.73.0 起允许 8+（新增国际化类）。"""
    text = _extract_const("GLOSSARY")
    cats = re.findall(r'"([^"\\]+)"\s*:\s*\{', text)
    expected_core = {
        "评估指数类",
        "指标/均线类",
        "宏观因子类",
        "品种代码类",
        "交易动作类",
        "系统状态类",
        "时段类",
    }
    assert expected_core.issubset(set(cats)), f"GLOSSARY 缺少核心分组：{expected_core - set(cats)}"
    assert len(cats) >= 7, f"GLOSSARY 至少 7 个分组，实际 {len(cats)}"


def test_glossary_has_at_least_30_terms() -> None:
    """GLOSSARY 总术语数 ≥ 30。"""
    text = _extract_const("GLOSSARY")
    entries = re.findall(r'"([^"\\]+)"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    assert len(entries) >= 30, f"术语数 {len(entries)} 不足 30"


@pytest.mark.parametrize(
    "term",
    [
        "综合指数",
        "技术面",
        "宏观面",
        "消息面",
        "RSI(14)",
        "MA5 / MA20 / MA40",
        "T12M",
        "DXY (美元指数)",
        "美债 10Y / 30Y",
        "VIX",
        "cb_gold",
        "Au99.99",
        "COMEX",
        "SGE",
        "518880",
        "ETF",
        "开仓",
        "加仓 / 减仓",
        "清仓",
        "软删除",
        "撤销",
        "仓位推荐",
        "live",
        "stale",
        "mock",
        "BJT",
    ],
)
def test_glossary_contains_key_term(term: str) -> None:
    """关键术语必须在 GLOSSARY 中可查到（且定义非空）。"""
    text = _extract_const("GLOSSARY")
    for cat in (
        "评估指数类",
        "指标/均线类",
        "宏观因子类",
        "品种代码类",
        "交易动作类",
        "系统状态类",
        "时段类",
    ):
        cat_obj = _extract_balanced_object(text, cat)
        if cat_obj.get(term):
            return
    pytest.fail(f"术语 {term!r} 在 GLOSSARY 中未找到或定义为空")


def test_inline_tooltips_cover_five_pages() -> None:
    """INLINE 配置覆盖 5 个页面，每页 ≥ 1 项，总数 = 12。"""
    text = _extract_const("INLINE")
    total = 0
    for page in EXPECTED_PAGES:
        items = _extract_array_of_objects(text, page)
        assert items, f"页面 {page} 缺少 INLINE 配置"
        total += len(items)
        for item in items:
            assert "selector" in item and "term" in item, f"{page} 配置项缺少 selector/term"
    assert total >= 12, f"INLINE 总数 {total} 应 ≥ 12（关键术语自动注入）"


@pytest.mark.parametrize("page", EXPECTED_PAGES)
def test_tour_steps_for_each_page(page: str) -> None:
    """每个页面在 TOUR_STEPS 中至少 2 步，且第一步必须指向 .topnav。"""
    text = _extract_const("TOUR_STEPS")
    steps = _extract_array_of_objects(text, page)
    assert len(steps) >= 2, f"{page} 至少 2 步引导"
    assert steps[0]["selector"] == ".topnav", f"{page} 第一步必须指向顶栏 .topnav"


def test_path_map_covers_all_pages() -> None:
    """PATH_MAP 同时支持 /static/xxx.html 与 /xxx 路由。"""
    text = _extract_const("PATH_MAP")
    for page in EXPECTED_PAGES:
        assert f'"{page}"' in text, f"PATH_MAP 缺少 {page}"


def test_help_version_constant_present() -> None:
    """VERSION 必须声明且符合 Vx.y.z 模式（每次大版本升级时 bump）。

    不再硬编码 V0.58.0 —— V0.72.0 升级通知中心页面时同步 bump VERSION（强制用户重看所有 tour）。
    """
    src = HELP_JS.read_text(encoding="utf-8")
    m = re.search(r'const\s+VERSION\s*=\s*"([^"]+)"', src)
    assert m, "VERSION 未声明"
    assert re.match(r"^V\d+\.\d+\.\d+$", m.group(1)), f"VERSION 格式不合法：{m.group(1)}"


def test_localstorage_namespace_is_pm_help() -> None:
    """localStorage key 必须以 pm_help_ 开头。"""
    text = _extract_const("LS")
    assert "pm_help_tour_" in text
    assert "pm_help_seen_version" in text


# ─────────────── HTML 注入验证 ───────────────


@pytest.mark.parametrize(
    "page",
    [
        "trend.html",
        "portfolio.html",
        "weights.html",
        "news.html",
        "central_bank.html",
    ],
)
def test_html_injects_help_css(page: str) -> None:
    """5 个 HTML 页面均需引入 help.css。"""
    html = (ROOT / "static" / page).read_text(encoding="utf-8")
    assert 'href="/static/help.css"' in html, f"{page} 未引入 help.css"


@pytest.mark.parametrize(
    "page",
    [
        "trend.html",
        "portfolio.html",
        "weights.html",
        "news.html",
        "central_bank.html",
    ],
)
def test_html_injects_help_js(page: str) -> None:
    """5 个 HTML 页面均需引入 help.js（defer）。"""
    html = (ROOT / "static" / page).read_text(encoding="utf-8")
    assert 'src="/static/help.js" defer' in html, f"{page} 未引入 help.js"


@pytest.mark.parametrize(
    "page",
    [
        "trend.html",
        "portfolio.html",
        "weights.html",
        "news.html",
        "central_bank.html",
    ],
)
def test_help_css_loaded_after_responsive(page: str) -> None:
    """help.css 必须在 responsive.css 之后加载（保证覆盖样式生效）。"""
    html = (ROOT / "static" / page).read_text(encoding="utf-8")
    responsive_pos = html.find('href="/static/responsive.css"')
    help_pos = html.find('href="/static/help.css"')
    assert responsive_pos > 0 and help_pos > 0
    assert help_pos > responsive_pos, f"{page} help.css 必须在 responsive.css 之后"
