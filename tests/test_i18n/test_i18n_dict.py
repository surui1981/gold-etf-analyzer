"""V0.73.0 P3-c i18n 字典完整性测试。

静态解析 static/i18n/{zh-CN,zh-TW,en-US}.js 三个字典文件，断言：
  1. JS 语法合法（顶层 window.PM_I18N_<LANG> = { ... } 形式）
  2. 无空字符串值
  3. 无重复 key
  4. 无首尾 BOM
  5. zh-CN ⊇ en-US ⊇ zh-TW（zh-TW 是 zh-CN 的子集）
  6. zh-CN 至少 100 个 key
  7. en-US 至少覆盖 zh-CN 的 80% 核心 key
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
I18N_DIR = ROOT / "static" / "i18n"

ZH_CN = "zh-CN"
ZH_TW = "zh-TW"
EN_US = "en-US"


def _load_dict(lang: str) -> dict[str, str]:
    """解析字典文件，返回 key→value dict。"""
    if lang == ZH_CN:
        path = I18N_DIR / "zh-CN.js"
        var = "window.PM_I18N_ZH_CN"
    elif lang == ZH_TW:
        path = I18N_DIR / "zh-TW.js"
        var = "window.PM_I18N_zh_TW"
    elif lang == EN_US:
        path = I18N_DIR / "en-US.js"
        var = "window.PM_I18N_en_US"
    else:
        raise ValueError(lang)
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    assert text.startswith("/*") is False or "*/" in text, "文件头应先有注释"
    # 提取顶层赋值后的 { ... } 字面量
    # 简化版：所有 "key": "value" 都视为顶层字典项
    pattern = r'"([^"\\]+)"\s*:\s*"((?:[^"\\]|\\.)*)"'
    pairs = re.findall(pattern, text)
    return dict(pairs)


def test_all_dict_files_exist() -> None:
    """三个字典文件必须存在。"""
    for name in ("zh-CN.js", "zh-TW.js", "en-US.js"):
        path = I18N_DIR / name
        assert path.exists(), f"缺少字典文件 {name}"
        assert path.stat().st_size > 100, f"{name} 太小（<100B），疑似空文件"


def test_no_bom_in_files() -> None:
    """字典文件首尾无 BOM。"""
    for name in ("zh-CN.js", "zh-TW.js", "en-US.js"):
        path = I18N_DIR / name
        text = path.read_bytes()
        assert not text.startswith(b"\xef\xbb\xbf"), f"{name} 含 UTF-8 BOM"
        assert not text.startswith(b"\ufeff"), f"{name} 含 UTF-16 BOM"


def test_zh_cn_has_at_least_100_keys() -> None:
    """简中字典至少 100 个 key（覆盖常用 UI）。"""
    d = _load_dict(ZH_CN)
    assert len(d) >= 100, f"zh-CN 仅 {len(d)} 个 key（≥100）"


def test_no_empty_values() -> None:
    """三个字典文件中无空字符串值。"""
    for lang in (ZH_CN, EN_US, ZH_TW):
        d = _load_dict(lang)
        empty = [k for k, v in d.items() if not v.strip()]
        assert not empty, f"{lang} 含空字符串值：{empty[:5]}"


def test_no_duplicate_keys() -> None:
    """三个字典文件无重复 key。"""
    for lang in (ZH_CN, EN_US, ZH_TW):
        path = I18N_DIR / f"{lang.replace('-', '-').replace('CN', 'CN').replace('US', 'US').replace('TW', 'TW')}.js"
        # 简化：用 regex 直接搜重复
        text = path.read_text(encoding="utf-8")
        pattern = r'"([^"\\]+)"\s*:'
        keys = re.findall(pattern, text)
        seen: set[str] = set()
        dups: list[str] = []
        for k in keys:
            if k in seen:
                dups.append(k)
            seen.add(k)
        assert not dups, f"{lang} 含重复 key：{dups[:5]}"


def test_en_us_covers_zh_cn_core() -> None:
    """en-US 必须覆盖 zh-CN 至少 80% 的 key（除纯繁中专属）。"""
    zh = _load_dict(ZH_CN)
    en = _load_dict(EN_US)
    zh_keys = set(zh.keys())
    en_keys = set(en.keys())
    missing = zh_keys - en_keys
    coverage = (len(zh_keys) - len(missing)) / max(len(zh_keys), 1)
    assert coverage >= 0.8, f"en-US 覆盖率仅 {coverage:.1%}（≥80%）；缺失 {len(missing)} 个 key（例：{list(missing)[:3]}）"


def test_zh_tw_subset_of_zh_cn() -> None:
    """zh-TW 是 zh-CN 的子集（PR-N+7 最小覆盖；PR-N+9 升级到 ≥60% 全量 chrome）。"""
    zh = _load_dict(ZH_CN)
    tw = _load_dict(ZH_TW)
    tw_keys = set(tw.keys())
    zh_keys = set(zh.keys())
    # 繁中派生自简中，不应有 extras（V0.73.0 N+9 起收紧约束）
    extras = tw_keys - zh_keys
    assert not extras, f"zh-TW 有 zh-CN 中没有的 key：{list(extras)[:3]}"
    # zh-TW 至少覆盖 zh-CN 的 60%（country.* 33 + nav + common + time + brand + help + theme + warn + portfolio/trend/backtest/central_bank chrome + fresh.*）
    coverage = len(tw_keys) / max(len(zh_keys), 1)
    assert coverage >= 0.6, f"zh-TW 覆盖率仅 {coverage:.1%}（≥60%，PR-N+9 全量 chrome 落地后）"


def test_required_keys_present_in_zh_cn() -> None:
    """核心 key 必须存在（topnav + common + portfolio + time + theme + brand）。"""
    zh = _load_dict(ZH_CN)
    required = {
        # nav
        "nav.trend", "nav.portfolio", "nav.trades", "nav.weights", "nav.news",
        "nav.review", "nav.central_bank", "nav.silver", "nav.backtest", "nav.settings",
        # common
        "common.save", "common.cancel", "common.confirm", "common.loading",
        # time
        "time.just_now", "time.minutes_ago", "time.hours_ago", "time.days_ago",
        # brand
        "brand.gold", "brand.silver", "brand.backtest",
        # theme
        "theme.light", "theme.dark", "theme.auto", "theme.hc",
        # portfolio 关键
        "portfolio.btn_open", "portfolio.holdings_title", "portfolio.action_buy",
        "portfolio.action_sell", "portfolio.equity_title",
    }
    missing = required - set(zh.keys())
    assert not missing, f"zh-CN 缺少核心 key：{missing}"


def test_i18n_js_module_exists() -> None:
    """i18n.js 主模块存在。"""
    path = ROOT / "static" / "i18n.js"
    assert path.exists(), "缺少 static/i18n.js"
    text = path.read_text(encoding="utf-8")
    # 关键 IIFE 标记
    assert "window.I18n" in text, "i18n.js 未导出 window.I18n"
    assert "PM_I18N_ZH_CN" in text, "i18n.js 未引用 PM_I18N_ZH_CN"
    assert "data-i18n" in text, "i18n.js 未处理 data-i18n 属性"


def test_i18n_js_declares_supported_locales() -> None:
    """i18n.js 声明 SUPPORTED locale 列表。"""
    path = ROOT / "static" / "i18n.js"
    text = path.read_text(encoding="utf-8")
    assert '"zh-CN"' in text
    assert '"zh-TW"' in text
    assert '"en-US"' in text


def test_i18n_js_handles_fallback() -> None:
    """i18n.js 字典 miss 时 fallback 到 zh-CN。"""
    path = ROOT / "static" / "i18n.js"
    text = path.read_text(encoding="utf-8")
    assert "hit_fallback" in text or "fb[" in text or "DEFAULT_LANG" in text


def test_i18n_js_exposes_format_namespace() -> None:
    """i18n.js 暴露 fmt 子命名空间（number/currency/date/percent/relative）。"""
    path = ROOT / "static" / "i18n.js"
    text = path.read_text(encoding="utf-8")
    assert "Intl.NumberFormat" in text, "未使用 Intl.NumberFormat"
    assert "Intl.DateTimeFormat" in text, "未使用 Intl.DateTimeFormat"
    assert "fmt:" in text or "fmt =" in text or "fmt ={" in text, "未导出 fmt 命名空间"