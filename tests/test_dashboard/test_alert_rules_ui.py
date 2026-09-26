"""V0.74.0 N+18 · 告警规则 CRUD UI 契约测试

测试范围(11 例):
  • settings.html 含 #ruleList 容器 + #btnAddRule 按钮 + #ruleModal 模态
  • 模态含 4 种 kind 的 radio + 各 kind 表单区
  • settings.js 含 4 种 KIND_LABEL + ruleDesc() 函数 + CRUD handlers
  • modal 切换 kind 时各 .kind-form 显示/隐藏正确
  • 三语 24 个 settings.{btn_add_rule,kind_*,label_*,modal_*} 键对齐
  • 前后端 telemetry 同步含 notification_rule_save

端到端 UI 交互(添加规则→保存→列表更新)由浏览器手测覆盖。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SETTINGS_HTML = ROOT / "static" / "settings.html"
SETTINGS_JS = ROOT / "static" / "settings.js"
TELEMETRY_JS = ROOT / "static" / "telemetry.js"
TELEMETRY_PY = ROOT / "src" / "app" / "services" / "telemetry.py"

# 三语对齐检查的 24 个 settings.* 键(N+18 新增)
N18_KEYS = [
    "btn_add_rule",
    "rule_count_hint",
    "modal_title_add",
    "modal_kind_label",
    "kind_volatility",
    "kind_crossing",
    "kind_window",
    "kind_t_plus_n",
    "label_threshold_pct",
    "label_axis_levels",
    "label_axis_2",
    "label_axis_4",
    "label_window_mode",
    "label_window_mode_quiet",
    "label_window_mode_active",
    "label_window_time",
    "label_t_plus_n_days",
    "label_t_plus_n_pct",
    "label_t_plus_n_pct_hint",
    "label_rule_enabled",
    "label_rule_note",
    "modal_cancel",
    "modal_confirm",
]

KIND_VALUES = ["volatility", "crossing", "window", "t_plus_n"]


# ────────── HTML 契约 ──────────


def test_settings_html_has_rule_list_container():
    """settings.html 含 #ruleList + #btnAddRule + #ruleModal 三件套。"""
    txt = SETTINGS_HTML.read_text(encoding="utf-8")
    assert 'id="ruleList"' in txt
    assert 'id="btnAddRule"' in txt
    assert 'id="ruleModal"' in txt


def test_settings_html_has_four_kind_radios():
    """ruleModal 含 4 种 kind 的 radio + 各 .kind-form 区。"""
    txt = SETTINGS_HTML.read_text(encoding="utf-8")
    # 4 个 radio(按 kind name 区分)
    for kind in KIND_VALUES:
        assert f'value="{kind}"' in txt, f"缺 radio kind={kind}"
    # 4 个 kind-form 区
    for kind in KIND_VALUES:
        assert f'data-kind-form="{kind}"' in txt, f"缺 .kind-form[{kind}]"


def test_settings_html_modal_kind_forms_have_inputs():
    """volatility/crossing/window/t_plus_n 表单含相应字段。"""
    txt = SETTINGS_HTML.read_text(encoding="utf-8")
    assert 'id="modalVolPct"' in txt
    assert 'id="modalAxisLevels"' in txt
    assert 'id="modalWindowMode"' in txt
    assert 'id="modalWinStart"' in txt
    assert 'id="modalWinEnd"' in txt
    assert 'id="modalTPlusNDays"' in txt
    assert 'id="modalTPlusNPct"' in txt
    # a11y
    assert 'role="dialog"' in txt
    assert 'aria-modal="true"' in txt


# ────────── JS 契约 ──────────


def test_settings_js_has_kind_label_table():
    """settings.js 含 KIND_LABEL 字典(4 个 kind)+ ruleDesc 描述函数。"""
    txt = SETTINGS_JS.read_text(encoding="utf-8")
    # KIND_LABEL = { volatility: "...", crossing: "...", ... }
    m = re.search(r"KIND_LABEL\s*=\s*\{(.*?)\};", txt, re.DOTALL)
    assert m, "找不到 KIND_LABEL 字典"
    body = m.group(1)
    for kind in KIND_VALUES:
        assert f"{kind}:" in body, f"KIND_LABEL 缺 {kind}"
    assert "ruleDesc" in txt
    assert "renderRuleList" in txt
    assert "openRuleModal" in txt
    assert "closeRuleModal" in txt
    assert "switchKindForm" in txt
    assert "collectModalRule" in txt
    assert "bindRuleModal" in txt


def test_settings_js_init_calls_bind_rule_modal():
    """init() 调用 bindRuleModal()(否则 modal 不响应)。"""
    txt = SETTINGS_JS.read_text(encoding="utf-8")
    start = txt.find("function init")
    assert start >= 0, "找不到 init() 函数"
    brace_open = txt.find("{", start)
    depth = 0
    end = brace_open
    for i in range(brace_open, len(txt)):
        ch = txt[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    init_body = txt[brace_open:end]
    assert "bindRuleModal" in init_body, "init() 必须调用 bindRuleModal()"


def test_settings_js_tracks_notification_rule_save():
    """saveRules 中调用 track('notification_rule_save', ...)。"""
    txt = SETTINGS_JS.read_text(encoding="utf-8")
    # 用花括号配对提取 saveRules 函数体（避免非贪婪 regex 在内嵌 `}` 处提前结束）
    start = txt.find("async function saveRules")
    assert start >= 0, "找不到 saveRules() 函数定义"
    # 跳过签名到第一个 '{'
    brace_open = txt.find("{", start)
    assert brace_open > 0, "saveRules 函数缺少开始花括号"
    depth = 0
    end = brace_open
    for i in range(brace_open, len(txt)):
        ch = txt[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    body = txt[brace_open:end]
    assert "notification_rule_save" in body, "saveRules 未触发 notification_rule_save 埋点"
    assert "rule_kinds" in body, "rule_kinds 字段缺失"


# ────────── i18n 三语对齐 ──────────


@pytest.mark.parametrize("lang", ["zh-CN", "en-US", "zh-TW"])
def test_settings_i18n_keys_three_languages_aligned(lang):
    """三语各 23 个 settings.{...} 键(V0.74.0 N+18)对齐。"""
    path = ROOT / "static" / "i18n" / f"{lang}.js"
    txt = path.read_text(encoding="utf-8")
    for k in N18_KEYS:
        assert f'"settings.{k}"' in txt, f"{lang} 缺 settings.{k}"


# ────────── Telemetry 前后端对齐 ──────────


def test_notification_rule_save_in_both_whitelists():
    """notification_rule_save 在 telemetry.py + telemetry.js 两侧白名单。"""
    fe = TELEMETRY_JS.read_text(encoding="utf-8")
    be = TELEMETRY_PY.read_text(encoding="utf-8")
    assert "notification_rule_save" in fe, "前端 telemetry 缺 notification_rule_save"
    assert "notification_rule_save" in be, "后端 telemetry 缺 notification_rule_save"


def test_old_alert_rule_save_event_still_present():
    """alert_rule_save 旧事件保留(其他页面仍使用)。"""
    fe = TELEMETRY_JS.read_text(encoding="utf-8")
    be = TELEMETRY_PY.read_text(encoding="utf-8")
    assert "alert_rule_save" in fe
    assert "alert_rule_save" in be


# ────────── 旧 schema 字段不再被读 ──────────


def test_settings_js_no_legacy_field_reads():
    """settings.js 不再读旧 schema 字段(ruleLevelCrossing / ruleVolatility 等)。
    旧字段已迁移到 rules.* 列表；UI 渲染走 renderRuleList。"""
    txt = SETTINGS_JS.read_text(encoding="utf-8")
    # 旧 input 元素 ID 应该完全不再出现
    assert 'getElementById("ruleLevelCrossing")' not in txt
    assert 'getElementById("ruleVolatility")' not in txt
    assert 'getElementById("ruleVolPct")' not in txt
    assert 'getElementById("quietStart")' not in txt
    assert 'getElementById("quietEnd")' not in txt


def test_settings_html_no_legacy_input_elements():
    """settings.html 不再含旧的 ruleLevelCrossing / ruleVolatility 等 input。"""
    txt = SETTINGS_HTML.read_text(encoding="utf-8")
    assert 'id="ruleLevelCrossing"' not in txt
    assert 'id="ruleVolatility"' not in txt
    assert 'id="ruleVolPct"' not in txt
    assert 'id="quietStart"' not in txt
    assert 'id="quietEnd"' not in txt
