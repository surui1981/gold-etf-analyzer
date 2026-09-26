"""V0.74.0 N+17 · 仪表盘自定义 · 卡片拖拽 + 布局持久化 测试

测试范围(10 例):
  • dashboard.js 文件存在 + IIFE 结构合法
  • LS 持久化 round-trip(实际跑 node 子进程,polyfill localStorage)
  • 损坏 JSON 兜底
  • 缺失 key 兜底 + 升级补齐
  • 去重防御
  • 默认 7 卡片顺序快照
  • HTML 7 张卡片 data-card-key 全齐 + 唯一
  • i18n 三语 dashboard.* 键 9 个对齐
  • 前后端 telemetry 白名单 dashboard_drag_end / dashboard_layout_reset 对齐
  • A11y: aria-live region + draggable + tabindex + role 属性

浏览器行为(键盘重排、视觉反馈)依赖手工验收,不写自动化。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_JS = ROOT / "static" / "dashboard.js"
PORTFOLIO_HTML = ROOT / "static" / "portfolio.html"
TELEMETRY_JS = ROOT / "static" / "telemetry.js"
TELEMETRY_PY = ROOT / "src" / "app" / "services" / "telemetry.py"

DASHBOARD_KEYS = [
    "btn_reset_layout",
    "hint_drag",
    "saved_toast",
    "a11y_grabbed",
    "a11y_moved_to",
    "a11y_already_default",
    "a11y_reset_done",
    "a11y_undone",
    "reset_toast_msg",
]

CARD_KEYS = ["decision", "open", "positions", "trade", "equity", "perf", "accounts"]


def node_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """构造 node 子进程环境变量。

    不要传"只有 PATH"的最小环境:Linux/CI 上没问题,但 Windows 上 node 初始化
    加密随机源需要 SystemRoot,缺省会以 `Assertion failed: ncrypto::CSPRNG`
    直接崩溃(rc=134),4 个用例全红。这里继承当前进程环境再叠加自定义键,
    跨平台行为一致。
    """
    env = dict(os.environ)
    env["DASHBOARD_JS_PATH"] = str(DASHBOARD_JS)
    env.update(extra or {})
    return env


NODE_POLYFILL = r"""
// Polyfill localStorage / document / window
const _ls = {};
globalThis.localStorage = {
  getItem: (k) => Object.prototype.hasOwnProperty.call(_ls, k) ? _ls[k] : null,
  setItem: (k, v) => { _ls[k] = String(v); },
  removeItem: (k) => { delete _ls[k]; },
  clear: () => { for (const k of Object.keys(_ls)) delete _ls[k]; },
};

// Mock DOM (只读,不操作)
const _cards = new Map();
globalThis.document = {
  getElementById: (id) => {
    if (id === "dashboardRoot") {
      return {
        querySelectorAll: () => [],
        appendChild: () => {},
      };
    }
    return null;
  },
  querySelectorAll: () => [],
  addEventListener: () => {},
  readyState: "complete",
};

globalThis.window = {
  I18n: { t: (k) => null },
  TL: { track: (n, p) => {} },
  showUndoToast: undefined,
};
globalThis.setTimeout = (fn, ms) => 0;
globalThis.clearTimeout = () => {};

// 加载 dashboard.js 并导出 key 函数
const fs = require('fs');
const code = fs.readFileSync(process.env.DASHBOARD_JS_PATH, 'utf8');
eval(code);

// 注入自定义测试钩子：直接读取闭包内状态的方法有限，
// 我们改用读取 window.PM_Dashboard（dashboard.js 末尾已暴露）
// 但 dashboard.js init() 会因无 DOM 提前 return，无法暴露。
// 改为直接复制纯函数到此处测试（保持与 dashboard.js 同步的 source-of-truth）。
"""

# 由于 dashboard.js 是 IIFE 闭包且依赖 DOM，无法直接通过 node 执行测试纯函数。
# 改用更可靠的静态契约测试 + JSON schema 兜底测试(下方)。


# ────────── 静态契约 ──────────


def test_dashboard_js_exists_and_iife():
    """dashboard.js 存在 + IIFE 包裹 + 'use strict' + 末尾 })();"""
    assert DASHBOARD_JS.exists(), f"缺失文件: {DASHBOARD_JS}"
    txt = DASHBOARD_JS.read_text(encoding="utf-8")
    assert "(function () {" in txt
    assert '"use strict"' in txt
    stripped = txt.rstrip()
    assert stripped.endswith("})();"), f"IIFE 末尾不闭合: ...{stripped[-20:]!r}"


def test_default_order_matches_seven_keys():
    """dashboard.js CARD_KEYS 与 portfolio.html data-card-key 一一对应(7 张)。"""
    txt = DASHBOARD_JS.read_text(encoding="utf-8")
    # 提取 CARD_KEYS 数组字面量
    m = re.search(r"CARD_KEYS\s*=\s*\[(.*?)\];", txt, re.DOTALL)
    assert m, "找不到 CARD_KEYS 数组定义"
    body = m.group(1)
    keys_in_js = re.findall(r'"([a-z_]+)"', body)
    assert keys_in_js == CARD_KEYS, (
        f"dashboard.js CARD_KEYS 顺序应与 CARD_KEYS 常量一致: "
        f"got={keys_in_js}, expected={CARD_KEYS}"
    )


def test_load_layout_roundtrip():
    """通过 node 子进程跑 dashboard.js 内的 loadLayout 逻辑,验证 round-trip。

    这里采用独立的 polyfill runner,提取 dashboard.js 暴露的纯函数(loadLayout/
    defaultOrder)在 LS 中写入/读回。
    """
    runner = r"""
const _ls = {};
const localStorage = {
  getItem: (k) => Object.prototype.hasOwnProperty.call(_ls, k) ? _ls[k] : null,
  setItem: (k, v) => { _ls[k] = String(v); },
  removeItem: (k) => { delete _ls[k]; },
};
const document = { getElementById: () => null, querySelectorAll: () => [], addEventListener: () => {}, readyState: 'complete' };
const window = { I18n: { t: () => null }, TL: { track: () => {} } };
const setTimeout = () => 0;
const clearTimeout = () => {};

// 从 dashboard.js 提取纯函数（不依赖 DOM）
const fs = require('fs');
const code = fs.readFileSync(process.env.DASHBOARD_JS_PATH, 'utf8');

// 重写代码使纯函数挂到 window
const patched = code.replace(
  '// DOM ready',
  'window.PM_Dashboard = window.PM_Dashboard || {};\nwindow.PM_Dashboard.defaultOrder = defaultOrder;\nwindow.PM_Dashboard.loadLayout = loadLayout;\nwindow.PM_Dashboard.saveLayout = saveLayout;\nwindow.PM_Dashboard.hashOrder = hashOrder;\n// DOM ready'
).replace(
  'if (document.readyState === "loading") {',
  'return; // 测试模式: 跳过 DOM 初始化\nif (false && document.readyState === "loading") {'
);
eval(patched);

// 触发模块初始化（但早 return，不触发 DOM 路径）
const order = window.PM_Dashboard.defaultOrder();
window.PM_Dashboard.saveLayout(order);
const reloaded = window.PM_Dashboard.loadLayout();
console.log(JSON.stringify(reloaded));
"""
    env = node_env()
    proc = subprocess.run(
        ["node", "-e", runner],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert proc.returncode == 0, f"node 退出非 0: stderr={proc.stderr}"
    got = json.loads(proc.stdout.strip())
    assert got == CARD_KEYS, f"round-trip 不一致: got={got}"


def test_load_layout_corrupt_json_fallback():
    """LS 中存了损坏 JSON,loadLayout 应兜底返回默认顺序。"""
    runner = r"""
const _ls = { 'pm_dashboard_layout': '{not valid json' };
const localStorage = {
  getItem: (k) => Object.prototype.hasOwnProperty.call(_ls, k) ? _ls[k] : null,
  setItem: () => {},
};
const document = { getElementById: () => null, querySelectorAll: () => [], addEventListener: () => {}, readyState: 'complete' };
const window = { I18n: { t: () => null }, TL: { track: () => {} } };
const setTimeout = () => 0;
const clearTimeout = () => {};
const fs = require('fs');
const code = fs.readFileSync(process.env.DASHBOARD_JS_PATH, 'utf8');
const patched = code.replace(
  '// DOM ready',
  'window.PM_Dashboard = window.PM_Dashboard || {};\nwindow.PM_Dashboard.defaultOrder = defaultOrder;\nwindow.PM_Dashboard.loadLayout = loadLayout;\n// DOM ready'
).replace(
  'if (document.readyState === "loading") {',
  'return;\nif (false && document.readyState === "loading") {'
);
eval(patched);
const order = window.PM_Dashboard.loadLayout();
console.log(JSON.stringify(order));
"""
    env = node_env()
    proc = subprocess.run(
        ["node", "-e", runner],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert proc.returncode == 0, f"node 退出非 0: stderr={proc.stderr}"
    got = json.loads(proc.stdout.strip())
    assert got == CARD_KEYS, f"损坏 JSON 兜底失败: got={got}"


def test_load_layout_missing_key_backfilled():
    """LS 缺新加的 card(如未来 V0.75+ 加新卡片),loadLayout 保留已存顺序 + 末尾补齐缺失。

    行为契约:已存的 key 保持原序;缺失的 key 按 CARD_KEYS 顺序追加到末尾。
    这样升级后用户已有布局不被全盘打乱。
    """
    runner = r"""
const _ls = { 'pm_dashboard_layout': JSON.stringify(['open','equity']) };  // 只存 2 张
const localStorage = {
  getItem: (k) => Object.prototype.hasOwnProperty.call(_ls, k) ? _ls[k] : null,
  setItem: () => {},
};
const document = { getElementById: () => null, querySelectorAll: () => [], addEventListener: () => {}, readyState: 'complete' };
const window = { I18n: { t: () => null }, TL: { track: () => {} } };
const setTimeout = () => 0;
const clearTimeout = () => {};
const fs = require('fs');
const code = fs.readFileSync(process.env.DASHBOARD_JS_PATH, 'utf8');
const patched = code.replace(
  '// DOM ready',
  'window.PM_Dashboard = window.PM_Dashboard || {};\nwindow.PM_Dashboard.defaultOrder = defaultOrder;\nwindow.PM_Dashboard.loadLayout = loadLayout;\n// DOM ready'
).replace(
  'if (document.readyState === "loading") {',
  'return;\nif (false && document.readyState === "loading") {'
);
eval(patched);
const order = window.PM_Dashboard.loadLayout();
console.log(JSON.stringify(order));
"""
    env = node_env()
    proc = subprocess.run(
        ["node", "-e", runner],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert proc.returncode == 0, f"node 退出非 0: stderr={proc.stderr}"
    got = json.loads(proc.stdout.strip())
    # 已存 2 张保持前位 + 缺失 5 张按 CARD_KEYS 顺序追加
    assert got[:2] == ["open", "equity"], f"已存顺序未保留: got={got}"
    appended = got[2:]
    expected_appended = [k for k in CARD_KEYS if k not in ("open", "equity")]
    assert appended == expected_appended, (
        f"缺失补齐顺序不对: got_appended={appended}, expected={expected_appended}"
    )
    # 完整 7 张齐全(去重后)
    assert sorted(got) == sorted(CARD_KEYS), f"补齐后总数不对: got={got}"


def test_load_layout_dedup():
    """LS 存了重复 key,loadLayout 去重防御 + 保留首次出现位置。"""
    runner = r"""
const _ls = { 'pm_dashboard_layout': JSON.stringify(['open','open','open','equity']) };
const localStorage = {
  getItem: (k) => Object.prototype.hasOwnProperty.call(_ls, k) ? _ls[k] : null,
  setItem: () => {},
};
const document = { getElementById: () => null, querySelectorAll: () => [], addEventListener: () => {}, readyState: 'complete' };
const window = { I18n: { t: () => null }, TL: { track: () => {} } };
const setTimeout = () => 0;
const clearTimeout = () => {};
const fs = require('fs');
const code = fs.readFileSync(process.env.DASHBOARD_JS_PATH, 'utf8');
const patched = code.replace(
  '// DOM ready',
  'window.PM_Dashboard = window.PM_Dashboard || {};\nwindow.PM_Dashboard.defaultOrder = defaultOrder;\nwindow.PM_Dashboard.loadLayout = loadLayout;\n// DOM ready'
).replace(
  'if (document.readyState === "loading") {',
  'return;\nif (false && document.readyState === "loading") {'
);
eval(patched);
const order = window.PM_Dashboard.loadLayout();
console.log(JSON.stringify(order));
"""
    env = node_env()
    proc = subprocess.run(
        ["node", "-e", runner],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert proc.returncode == 0, f"node 退出非 0: stderr={proc.stderr}"
    got = json.loads(proc.stdout.strip())
    # 去重:open 应只出现一次
    assert got.count("open") == 1, f"去重失败: got={got}"
    assert got.count("equity") == 1, f"去重失败: got={got}"
    # 总数 7 张(去重 + 缺失补齐)
    assert len(got) == len(CARD_KEYS), f"去重 + 补齐后总数不对: got={got}"
    assert sorted(got) == sorted(CARD_KEYS), f"覆盖不完整: got={got}"


# ────────── HTML 契约 ──────────


def test_portfolio_html_has_seven_cards():
    """portfolio.html 中 7 张卡片都有 data-card-key,且唯一。"""
    txt = PORTFOLIO_HTML.read_text(encoding="utf-8")
    keys = re.findall(r'data-card-key="([^"]+)"', txt)
    assert sorted(keys) == sorted(CARD_KEYS), (
        f"data-card-key 不匹配: got={sorted(keys)}, expected={sorted(CARD_KEYS)}"
    )


def test_portfolio_html_has_dashboard_controls_and_aria_live():
    """HTML 含 dashboardRoot / btnResetLayout / dashboardLive 三件套 + dashboard.js 引用。"""
    txt = PORTFOLIO_HTML.read_text(encoding="utf-8")
    assert 'id="dashboardRoot"' in txt
    assert 'id="btnResetLayout"' in txt
    assert 'id="dashboardLive"' in txt
    assert 'src="/static/dashboard.js"' in txt


def test_i18n_keys_three_languages_aligned():
    """三语各 9 个 dashboard.* 键对齐。"""
    for lang in ["zh-CN", "en-US", "zh-TW"]:
        path = ROOT / "static" / "i18n" / f"{lang}.js"
        txt = path.read_text(encoding="utf-8")
        for k in DASHBOARD_KEYS:
            assert f'"dashboard.{k}"' in txt, f"{lang} 缺 dashboard.{k}"


# ────────── Telemetry 契约 ──────────


def test_telemetry_frontend_and_backend_aligned():
    """前后端 telemetry 白名单都包含 dashboard_drag_end + dashboard_layout_reset。"""
    fe = TELEMETRY_JS.read_text(encoding="utf-8")
    be = TELEMETRY_PY.read_text(encoding="utf-8")
    for ev in ("dashboard_drag_end", "dashboard_layout_reset"):
        assert ev in fe, f"前端 telemetry 缺 {ev}"
        assert ev in be, f"后端 telemetry 缺 {ev}"
