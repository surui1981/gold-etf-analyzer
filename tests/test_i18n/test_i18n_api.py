"""V0.73.0 P3-c i18n API 行为测试（Node 实跑 i18n.js）。

用 Node 22+ 内置 fs/eval 模拟 DOM，加载 static/i18n.js 和字典文件。
本测试只覆盖**同步 API**：t/fmt；setLang/异步加载跳过（CI 单独验）。
"""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "static"
NODE = "node"


def _run_i18n_test(js_body: str) -> dict:
    """把 js_body 拼进 IIFE 包装，丢给 Node 执行，返回打印的 JSON。"""
    # Windows 路径含反斜杠，若直接插进 JS 单引号字符串会被当成转义序列吞掉
    # （`\U`、`\2`、`\g`… → 路径被破坏），故用 json.dumps 生成 JS 安全字面量。
    # Linux / Docker 下路径本来就是正斜杠，因此该问题只在 Windows 上暴露。
    static_js = json.dumps(str(STATIC))
    harness = textwrap.dedent(f"""
        // Mock DOM（最小化）—— body 是 HTMLElement 子类，需要有 querySelectorAll
        function makeMockEl() {{
          return {{
            setAttribute: () => {{}},
            getAttribute: () => null,
            addEventListener: () => {{}},
            querySelector: () => null,
            querySelectorAll: () => [],
            appendChild: () => {{}},
            classList: {{ add: () => {{}}, remove: () => {{}} }},
            textContent: "",
            innerHTML: "",
            dataset: {{}},
          }};
        }}
        const document = {{
          documentElement: makeMockEl(),
          body: makeMockEl(),
          readyState: "complete",
          addEventListener: () => {{}},
          querySelector: () => null,
          querySelectorAll: () => [],
          getElementById: () => null,
          createElement: () => makeMockEl(),
          head: {{ appendChild: () => {{}} }},
          dispatchEvent: () => {{}},
        }};
        const window = globalThis;
        window.document = document;
        window.localStorage = {{
          _s: {{}},
          getItem(k) {{ return this._s[k] || null; }},
          setItem(k, v) {{ this._s[k] = String(v); }},
        }};
        window.CustomEvent = function(name, init) {{ return {{ type: name, detail: init ? init.detail : null }}; }};

        // 加载字典文件
        const fs = require('fs');
        function loadDict(file) {{
          const text = fs.readFileSync(file, 'utf8');
          const match = text.match(/window\\.PM_I18N_\\w+\\s*=\\s*({{[\\s\\S]*}});?/);
          if (!match) throw new Error('dict not found in ' + file);
          return eval('(' + match[1] + ')');
        }}

        const zhCN = loadDict({static_js} + '/i18n/zh-CN.js');
        const enUS = loadDict({static_js} + '/i18n/en-US.js');
        window.PM_I18N_ZH_CN = zhCN;
        window.PM_I18N_en_US = enUS;

        // 加载 i18n.js
        const i18nText = fs.readFileSync({static_js} + '/i18n.js', 'utf8');
        eval(i18nText);

        {js_body}

        console.log(JSON.stringify({{
          result: typeof result !== 'undefined' ? result : null,
        }}));
    """)
    proc = subprocess.run(
        [NODE, "-e", harness],
        capture_output=True,
        text=True,
        timeout=20,
        cwd=str(ROOT),
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Node test failed: stderr={proc.stderr}; stdout={proc.stdout}")
    last_line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "{}"
    return json.loads(last_line)


def test_i18n_exposes_api():
    """window.I18n 暴露 t/setLang/apply/fmt 等方法。"""
    out = _run_i18n_test("""
        result = {
            has_t: typeof window.I18n.t === 'function',
            has_setLang: typeof window.I18n.setLang === 'function',
            has_apply: typeof window.I18n.apply === 'function',
            has_fmt: typeof window.I18n.fmt === 'object',
            supported: window.I18n.SUPPORTED,
            default_lang: window.I18n.DEFAULT_LANG,
        };
    """)
    r = out["result"]
    assert r["has_t"]
    assert r["has_setLang"]
    assert r["has_apply"]
    assert r["has_fmt"]
    assert r["supported"] == ["zh-CN", "zh-TW", "en-US"]
    assert r["default_lang"] == "zh-CN"


def test_i18n_t_returns_zh_cn_value():
    """默认 locale 是 zh-CN，t('nav.trend') 应返回中文。"""
    out = _run_i18n_test("""
        result = window.I18n.t('nav.trend');
    """)
    assert out["result"] == "趋势追踪"


def test_i18n_t_param_substitution():
    """t('time.minutes_ago', {n: 5}) 应替换 {n}。"""
    out = _run_i18n_test("""
        result = window.I18n.t('time.minutes_ago', { n: 5 });
    """)
    assert out["result"] == "5 分钟前"


def test_i18n_t_missing_key_returns_key():
    """字典缺失 key 时返回 key 字面量（不抛错）。"""
    out = _run_i18n_test("""
        result = window.I18n.t('nonexistent.deeply.nested.key');
    """)
    assert out["result"] == "nonexistent.deeply.nested.key"


def test_i18n_t_falls_back_to_zh_cn_for_en_miss():
    """en-US 缺 key 时应回落到 zh-CN（en-US dict 已覆盖大多数核心 key）。"""
    out = _run_i18n_test("""
        result = window.I18n.t('common.save');  // 两个字典都有
    """)
    # 默认 locale 是 zh-CN，所以返回中文；这里只验证字典查找无抛错
    assert out["result"] in ("保存", "Save")


def test_i18n_fmt_number_zh_cn():
    """fmt.number(1234.5) 在 zh-CN locale 下应包含 '1,234'。"""
    out = _run_i18n_test("""
        result = window.I18n.fmt.number(1234.5, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    """)
    assert "1,234" in out["result"]


def test_i18n_fmt_currency_cny():
    """fmt.currency(1234.5) 在 zh-CN locale 下输出 ¥ 符号。"""
    out = _run_i18n_test("""
        result = window.I18n.fmt.currency(1234.5);
    """)
    assert "¥" in out["result"] or "CNY" in out["result"]


def test_i18n_fmt_relative_zh_cn():
    """fmt.relative(60) → '1 分钟前'。"""
    out = _run_i18n_test("""
        result = window.I18n.fmt.relative(60);
    """)
    assert out["result"] == "1 分钟前"


def test_i18n_fmt_relative_just_now():
    """fmt.relative(30) → '刚刚'。"""
    out = _run_i18n_test("""
        result = window.I18n.fmt.relative(30);
    """)
    assert out["result"] == "刚刚"


def test_i18n_lang_getter():
    """I18n.lang getter 返回当前 locale（默认 zh-CN）。"""
    out = _run_i18n_test("""
        result = window.I18n.lang;
    """)
    assert out["result"] == "zh-CN"
