"""V0.73.0 P3-c i18n fmt.* 格式化 API 全面测试。

复用 test_i18n_api.py 的 _run_i18n_test 风格，用 Node 子进程模拟 DOM，
跑 I18n.fmt.{number, currency, percent, date, time, relative} 在三语下的行为。

PR-N+9 新增：
- fmt.number 三语都用 ',' 分位（zh-CN/en-US/zh-TW 均 1,234.5）
- fmt.currency 验证 ¥ / $ 符号
- fmt.percent 三语都输出 12.3%
- fmt.date 含年份
- fmt.time 24h 或 12h（按 locale）
- fmt.relative 4 个 bucket（just_now / minutes / hours / days）× 3 语
"""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "static"
NODE = "node"


def _run_fmt(lang: str, js_body: str) -> dict:
    """加载三语字典 + i18n.js，把 lang 设到 state.lang（绕过 setLang 异步），执行 js_body。"""
    # 字典对应的 window 全局变量名（V0.73.0 三语）
    var_map = {"zh-CN": "PM_I18N_ZH_CN", "zh-TW": "PM_I18N_zh_TW", "en-US": "PM_I18N_en_US"}
    var_name = var_map[lang]
    # Windows 路径含反斜杠，若直接插进 JS 单引号字符串会被当成转义序列吞掉
    # （`\U`、`\2`、`\g`… → 路径被破坏），故用 json.dumps 生成 JS 安全字面量。
    # Linux / Docker 下路径本来就是正斜杠，因此该问题只在 Windows 上暴露。
    static_js = json.dumps(str(STATIC))
    harness = textwrap.dedent(f"""
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

        const fs = require('fs');
        function loadDict(file) {{
          const text = fs.readFileSync(file, 'utf8');
          const match = text.match(/window\\.PM_I18N_\\w+\\s*=\\s*({{[\\s\\S]*}});?/);
          if (!match) throw new Error('dict not found in ' + file);
          return eval('(' + match[1] + ')');
        }}

        window.PM_I18N_ZH_CN = loadDict({static_js} + '/i18n/zh-CN.js');
        window.PM_I18N_zh_TW = loadDict({static_js} + '/i18n/zh-TW.js');
        window.PM_I18N_en_US = loadDict({static_js} + '/i18n/en-US.js');

        const i18nText = fs.readFileSync({static_js} + '/i18n.js', 'utf8');
        eval(i18nText);

        // 测试 hook：同步注入字典 + 切 lang（绕开 setLang 异步加载）
        window.I18n.__test_setLang('{lang}', window.{var_name});

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


# ── number ──


def test_fmt_number_zh_cn() -> None:
    """fmt.number(1234.5) zh-CN 含 '1,234'。"""
    out = _run_fmt(
        "zh-CN",
        """
        result = window.I18n.fmt.number(1234.5, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    """,
    )
    assert "1,234" in out["result"]


def test_fmt_number_en_us() -> None:
    """fmt.number(1234.5) en-US 含 '1,234'。"""
    out = _run_fmt(
        "en-US",
        """
        result = window.I18n.fmt.number(1234.5, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    """,
    )
    assert "1,234" in out["result"]


def test_fmt_number_zh_tw() -> None:
    """fmt.number(1234.5) zh-TW 含 '1,234'（同 zh-CN locale 规则）。"""
    out = _run_fmt(
        "zh-TW",
        """
        result = window.I18n.fmt.number(1234.5, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    """,
    )
    assert "1,234" in out["result"]


# ── currency ──


def test_fmt_currency_zh_cn() -> None:
    """fmt.currency(1234.5) zh-CN 默认 CNY → 含 ¥。"""
    out = _run_fmt(
        "zh-CN",
        """
        result = window.I18n.fmt.currency(1234.5);
    """,
    )
    assert "¥" in out["result"] or "CNY" in out["result"]


def test_fmt_currency_en_us_dollar() -> None:
    """fmt.currency(1234.5, 'USD') en-US → 含 $。"""
    out = _run_fmt(
        "en-US",
        """
        result = window.I18n.fmt.currency(1234.5, 'USD');
    """,
    )
    assert "$" in out["result"] or "US$" in out["result"]


def test_fmt_currency_zh_tw() -> None:
    """fmt.currency(1234.5) zh-TW 默认 CNY → 含 ¥。"""
    out = _run_fmt(
        "zh-TW",
        """
        result = window.I18n.fmt.currency(1234.5);
    """,
    )
    assert "¥" in out["result"] or "CNY" in out["result"]


# ── percent ──


def test_fmt_percent_zh_cn() -> None:
    """fmt.percent(0.123, 1) zh-CN → '12.3%'。"""
    out = _run_fmt(
        "zh-CN",
        """
        result = window.I18n.fmt.percent(0.123, 1);
    """,
    )
    assert "12.3" in out["result"] and "%" in out["result"]


def test_fmt_percent_en_us() -> None:
    """fmt.percent(0.123, 1) en-US → '12.3%'。"""
    out = _run_fmt(
        "en-US",
        """
        result = window.I18n.fmt.percent(0.123, 1);
    """,
    )
    assert "12.3" in out["result"] and "%" in out["result"]


def test_fmt_percent_zh_tw() -> None:
    """fmt.percent(0.123, 1) zh-TW → '12.3%'。"""
    out = _run_fmt(
        "zh-TW",
        """
        result = window.I18n.fmt.percent(0.123, 1);
    """,
    )
    assert "12.3" in out["result"] and "%" in out["result"]


# ── date / time ──


def test_fmt_date_zh_cn_contains_year() -> None:
    """fmt.date('2026-09-22') zh-CN 含 '2026'。"""
    out = _run_fmt(
        "zh-CN",
        """
        result = window.I18n.fmt.date(new Date('2026-09-22T00:00:00Z'));
    """,
    )
    assert "2026" in out["result"]


def test_fmt_date_en_us_contains_year() -> None:
    """fmt.date('2026-09-22') en-US 含年份信息（2 位简写 '26' 或 4 位 '2026' 都接受）。"""
    out = _run_fmt(
        "en-US",
        """
        result = window.I18n.fmt.date(new Date('2026-09-22T00:00:00Z'));
    """,
    )
    # en-US 默认 dateStyle:'short' 输出 'M/D/YY' → '9/22/26'
    assert "26" in out["result"]


def test_fmt_time_zh_cn() -> None:
    """fmt.time zh-CN 含 '：' 或 ':' + 数字。"""
    out = _run_fmt(
        "zh-CN",
        """
        result = window.I18n.fmt.time(new Date('2026-09-22T09:30:00Z'));
    """,
    )
    # Intl.DateTimeFormat zh-CN 输出形如 "09:30"（24h）
    assert any(c.isdigit() for c in out["result"]) and (
        ":" in out["result"] or "：" in out["result"]
    )


# ── relative (4 buckets × 3 语) ──


def test_fmt_relative_zh_cn_all_buckets() -> None:
    """fmt.relative 4 个时间桶 zh-CN 输出。"""
    out = _run_fmt(
        "zh-CN",
        """
        result = {
            just_now: window.I18n.fmt.relative(30),
            minutes: window.I18n.fmt.relative(60),
            hours: window.I18n.fmt.relative(3600),
            days: window.I18n.fmt.relative(86400),
        };
    """,
    )
    r = out["result"]
    assert r["just_now"] == "刚刚"
    assert r["minutes"] == "1 分钟前"
    assert r["hours"] == "1 小时前"
    assert r["days"] == "1 天前"


def test_fmt_relative_en_us_all_buckets() -> None:
    """fmt.relative 4 个时间桶 en-US 输出。"""
    out = _run_fmt(
        "en-US",
        """
        result = {
            just_now: window.I18n.fmt.relative(30),
            minutes: window.I18n.fmt.relative(60),
            hours: window.I18n.fmt.relative(3600),
            days: window.I18n.fmt.relative(86400),
        };
    """,
    )
    r = out["result"]
    assert r["just_now"] == "Just now"
    # en-US minutes: "{n} min ago"
    assert "min" in r["minutes"] and "ago" in r["minutes"]
    assert "hour" in r["hours"] and "ago" in r["hours"]
    assert "day" in r["days"] and "ago" in r["days"]


def test_fmt_relative_zh_tw_all_buckets() -> None:
    """fmt.relative 4 个时间桶 zh-TW 输出（PR-N+9 验证繁中字典生效）。"""
    out = _run_fmt(
        "zh-TW",
        """
        result = {
            just_now: window.I18n.fmt.relative(30),
            minutes: window.I18n.fmt.relative(60),
            hours: window.I18n.fmt.relative(3600),
            days: window.I18n.fmt.relative(86400),
        };
    """,
    )
    r = out["result"]
    assert r["just_now"] == "剛剛"
    assert r["minutes"] == "1 分鐘前"
    assert r["hours"] == "1 小時前"
    assert r["days"] == "1 天前"
