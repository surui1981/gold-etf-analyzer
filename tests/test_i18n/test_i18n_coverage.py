"""V0.73.0 P3-c i18n 字典覆盖率与本地化一致性测试。

PR-N+9 新增：
- zh-TW 字典覆盖率 ≥ 60%（PR-N+7 是 10%，PR-N+9 升到 60%）
- zh-TW 必含 chrome 命名空间（country.* 33 + portfolio/trend/backtest/central_bank 关键键）
- country.* 33 个 key 在三语都存在
- freshness.js 无残留硬编码中文（10 个 forbidden 字符串）
- 9 个静态 HTML 各 ≥ 5 个 data-i18n 属性（PR-N+8 落地后回归确认；V0.75.0 扩到 12 个页面）
- fresh.* 13 个 key 在三语都存在
- zh-TW 关键 15 个 key 无残留英文
- **V0.75.0 新增**：全站 `data-i18n*` 引用的 key 必须都能在 zh-CN 字典解析（防「原文被静默替换成原始 key」）
- **V0.75.1 新增**：synthesis-card.js 引用的 `syn.*` key 三语齐全 + 三语 `syn.*` 键集合严格一致
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
I18N_DIR = ROOT / "static" / "i18n"
STATIC_DIR = ROOT / "static"

ZH_CN = "zh-CN"
ZH_TW = "zh-TW"
EN_US = "en-US"


def _load_dict(lang: str) -> dict[str, str]:
    """解析字典文件，返回 key→value dict。"""
    if lang == ZH_CN:
        path = I18N_DIR / "zh-CN.js"
    elif lang == ZH_TW:
        path = I18N_DIR / "zh-TW.js"
    elif lang == EN_US:
        path = I18N_DIR / "en-US.js"
    else:
        raise ValueError(lang)
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    pattern = r'"([^"\\]+)"\s*:\s*"((?:[^"\\]|\\.)*)"'
    pairs = re.findall(pattern, text)
    return dict(pairs)


# ── 1. zh-TW 覆盖率 ≥ 60% ──


def test_zh_tw_coverage_at_least_60pct() -> None:
    """PR-N+9：zh-TW 字典覆盖率从 10% 升到 ≥ 60%。"""
    zh_cn = _load_dict(ZH_CN)
    zh_tw = _load_dict(ZH_TW)
    coverage = len(zh_tw) / max(len(zh_cn), 1)
    assert coverage >= 0.6, (
        f"zh-TW 覆盖率仅 {coverage:.1%}（≥60%）；当前 {len(zh_tw)}/{len(zh_cn)}；"
        f"PR-N+9 全量 chrome 落地后应 ≥ 60%"
    )


# ── 2. zh-TW 必含 chrome 命名空间 ──


def test_zh_tw_covers_required_chrome() -> None:
    """zh-TW 必含 ~50 个关键 chrome key（覆盖 10 个页面 hero / button / column / footer）。"""
    zh_tw = _load_dict(ZH_TW)
    required = {
        # country.*（8 个代表 key；完整 33 由下个测试覆盖）
        "country.China",
        "country.Russia",
        "country.Poland",
        "country.Turkey",
        "country.Singapore",
        "country.Uzbekistan",
        "country.Germany",
        "country.region_global",
        # portfolio.* chrome
        "portfolio.btn_open",
        "portfolio.action_buy",
        "portfolio.action_sell",
        "portfolio.action_hold",
        "portfolio.action_reduce",
        "portfolio.action_add",
        "portfolio.holdings_title",
        "portfolio.kpi_total_pl",
        # trend.* chrome
        "trend.h1",
        "trend.tab_daily",
        "trend.tab_weekly",
        "trend.tab_monthly",
        "trend.level_strong_up",
        "trend.level_strong_down",
        # backtest.* chrome
        "backtest.h1",
        "backtest.tagline",
        "backtest.btn_run",
        # central_bank.* chrome
        "central_bank.h1",
        "central_bank.intro_long",
        "central_bank.kpi_t12m",
        "central_bank.col_country",
        "central_bank.col_iso",
        "central_bank.btn_apply",
        "central_bank.btn_reset",
        # fresh.* （PR-N+9 新）
        "fresh.title",
        "fresh.tip_session",
        "fresh.tip_windows",
        "fresh.alert_mock",
        "fresh.alert_cached",
        "fresh.load_failed",
    }
    missing = required - set(zh_tw.keys())
    assert not missing, f"zh-TW 缺少 chrome keys：{sorted(missing)}"


# ── 3. country.* 33 个 key 在三语都存在 ──


def test_country_keys_in_all_3_locales() -> None:
    """33 个 country.* key 在 zh-CN / zh-TW / en-US 都必须存在。"""
    required = {
        "country.China",
        "country.Russia",
        "country.India",
        "country.Turkey",
        "country.Poland",
        "country.Singapore",
        "country.Czech",
        "country.Hungary",
        "country.Uzbekistan",
        "country.Iran",
        "country.Qatar",
        "country.Bulgaria",
        "country.Egypt",
        "country.Jordan",
        "country.Kazakhstan",
        "country.Malaysia",
        "country.Serbia",
        "country.Ghana",
        "country.Mauritius",
        "country.Philippines",
        "country.Kyrgyzstan",
        "country.Slovakia",
        "country.Slovenia",
        "country.Bangladesh",
        "country.Thailand",
        "country.Indonesia",
        "country.Mongolia",
        "country.Japan",
        "country.South_Korea",
        "country.Germany",
        "country.Switzerland",
        "country.region_global",
        "country.region_official",
    }
    for lang in (ZH_CN, ZH_TW, EN_US):
        d = _load_dict(lang)
        missing = required - set(d.keys())
        assert not missing, f"{lang} 缺少 country.* keys：{sorted(missing)[:5]}"


# ── 4. freshness.js 无残留硬编码中文 ──


def test_no_hardcoded_chinese_in_freshness_js() -> None:
    """freshness.js 移除硬编码中文文案（保留 emoji / CSS class / 字段名 + _t() fallback 字面量）。

    `_t("key", "fallback zh-CN string")` 形式作为 i18n.js 加载前的安全兜底是允许的；
    其他位置的硬编码中文文案应全部走字典。
    """
    js = (STATIC_DIR / "freshness.js").read_text(encoding="utf-8")
    # 移除所有注释
    code = re.sub(r"/\*[\s\S]*?\*/", "", js)
    code = re.sub(r"//[^\n]*", "", code)
    # 移除所有 _t("key", "fallback") 调用中的 fallback 字面量（保留第一个参数 i18n key）
    code = re.sub(r'_t\("[^"]+"\s*,\s*"[^"]*"\)', '_t("KEY", "FALLBACK")', code)
    forbidden = [
        "刚刚采集",
        "分钟前采集",
        "小时前采集",
        "天前采集",
        "本地时间",
        "请勿据此决策",
        "演示数据",
        "缓存数据",
        "下一时点",
        "数据截止",
        "数据时效",
        "时段：",
        "交易时间：",
    ]
    for word in forbidden:
        assert word not in code, f"freshness.js 残留硬编码中文：{word!r}"


# ── 5. 9 个静态 HTML 各 ≥ 5 个 data-i18n 属性 ──


@pytest.mark.parametrize(
    "html_name",
    [
        "trend.html",
        "portfolio.html",
        "news.html",
        "weights.html",
        "trades.html",
        "review.html",
        "central_bank.html",
        "silver.html",
        "backtest.html",
        "settings.html",
        "data-health.html",
        "login.html",
    ],
)
def test_html_pages_have_data_i18n(html_name: str) -> None:
    """PR-N+8 落地后所有静态页面都应 ≥ 5 个 data-i18n 属性。"""
    html = (STATIC_DIR / html_name).read_text(encoding="utf-8")
    n = len(re.findall(r"data-i18n\s*=", html))
    assert n >= 5, f"{html_name} 仅 {n} 个 data-i18n 属性（≥5）"


# ── 6.5 所有 data-i18n* 引用的 key 必须在 zh-CN 字典存在（V0.75.0 新增）──


def test_all_data_i18n_keys_resolve_in_zh_cn() -> None:
    """**反向校验**：HTML 中每一个 `data-i18n*` 引用的 key 都必须能在 zh-CN 字典里找到。

    为什么必须有这条：`I18n.apply()` 对未知 key 的行为是 **`el.textContent = t(key)`**，
    而 `t()` 找不到时返回 **key 字面量本身** —— 结果是元素里的中文原文被**静默替换成
    `warn.data_source` 这样的原始 key**，页面上直接露出英文字符串。

    这类缺陷的特征是「语法正确、引用存在、DOM id 一致」：
    - `check_static_js.py` 只做 JS 语法 / 未定义调用 / DOM id 校验 → **查不出**；
    - `test_html_pages_have_data_i18n` 只数属性**个数**（≥5）→ **查不出**；
    - 只有真正在浏览器里渲染出来才看得见（V0.75.0 开发期就是这样被 headless 截图抓到的）。

    V0.75.0 实测：全站 13 个页面 627 处引用，zh-CN 字典 739 个 key。
    """
    keys = set(_load_dict(ZH_CN).keys())
    assert keys, "zh-CN 字典为空，无法校验"

    attr = re.compile(r'data-i18n(?:-[a-z]+)?="([^"]+)"')
    dangling: list[str] = []
    refs = 0
    for page in sorted(STATIC_DIR.glob("*.html")):
        html = page.read_text(encoding="utf-8")
        for raw in attr.findall(html):
            key = raw.strip()
            # `data-i18n="html"` 是 i18n.js 约定的特殊值（走 innerHTML 分支），非字典 key
            if not key or key == "html":
                continue
            refs += 1
            if key not in keys:
                dangling.append(f"{page.name}: {key}")

    assert refs > 0, "未扫描到任何 data-i18n 引用，正则或目录可能有问题"
    assert not dangling, (
        "以下 data-i18n key 在 zh-CN 字典中不存在（页面会露出原始 key）：\n  "
        + "\n  ".join(dangling)
    )


# ── 6. fresh.* 13 个 key 在三语都存在 ──


def test_fresh_dict_keys_in_all_3_locales() -> None:
    """13 个 fresh.* key 在 zh-CN / zh-TW / en-US 都必须存在（PR-N+9 新）。"""
    required = {
        "fresh.title",
        "fresh.tip_session",
        "fresh.tip_windows",
        "fresh.tip_next",
        "fresh.tip_data_date",
        "fresh.sep",
        "fresh.refresh_hint",
        "fresh.alert_mock",
        "fresh.alert_cached",
        "fresh.alert_suffix",
        "fresh.alert_icon",
        "fresh.load_failed",
        "fresh.local_time_suffix",
    }
    for lang in (ZH_CN, ZH_TW, EN_US):
        d = _load_dict(lang)
        missing = required - set(d.keys())
        assert not missing, f"{lang} 缺少 fresh.* keys：{sorted(missing)}"


# ── 7. zh-TW 关键 key 无残留英文 ──


def test_zh_tw_no_unintended_english_in_chrome_keys() -> None:
    """zh-TW 字典的 chrome 关键 key 不应含连续 3+ 英文字母（防维护疏漏）。"""
    zh_tw = _load_dict(ZH_TW)
    chrome_keys = [
        "common.save",
        "common.cancel",
        "common.confirm",
        "common.loading",
        "common.refresh",
        "common.close",
        "common.search",
        "common.retry",
        "common.back",
        "common.all",
        "common.yes",
        "common.no",
        "common.none",
        "common.delete",
        "common.edit",
        "time.just_now",
        "time.minutes_ago",
        "time.hours_ago",
        "time.days_ago",
        "theme.light",
        "theme.dark",
        "theme.auto",
        "theme.hc",
        "warn.title",
    ]
    for k in chrome_keys:
        v = zh_tw.get(k, "")
        m = re.search(r"[A-Za-z]{3,}", v)
        assert not m, f"zh-TW[{k}] 残留英文 {v!r}（匹配 {m.group() if m else None}）"


# ── 8. V0.75.1：synthesis-card.js 引用的 syn.* key 三语齐全 ──


def test_syn_card_keys_in_all_3_locales() -> None:
    """结论卡（synthesis-card.js）引用的每个 syn.* key 都必须在三语字典里存在。

    **为什么从 JS 源码反推、而不是像 fresh.* 那样硬编码清单**：结论卡的 key
    会随 UI 演进持续增加，硬编码清单一旦忘记同步就完全失去门禁作用。这里直接扫
    源码里的 `'syn.xxx'` 字面量，漏翻译会立刻失败（新增 key 时自动生效）。

    **失败后果说明**：synthesis-card.js 的 ``T(key, zh)`` 自带中文兜底——字典缺
    key 时回退中文，**绝不把 key 字面量渲染到页面**（V0.75.0 曾因悬空 key 把页脚
    中文静默替换成 ``warn.data_source``）。所以本测试失败不会造成线上事故，但必须修：
    否则该文案会永久停留在中文，en-US / zh-TW 用户看不到翻译。

    （结论卡保留中文兜底是有意的防御设计，与 freshness.js「零硬编码中文」的策略不同：
    freshness 的 key 是固定 13 个且有完整性门禁，而结论卡 key 更多、还承担
    「字典加载失败时页面仍可读」的兜底职责。）
    """
    js = (STATIC_DIR / "synthesis-card.js").read_text(encoding="utf-8")
    referenced = set(re.findall(r"'(syn\.[a-z_0-9]+)'", js))
    assert referenced, "未从 synthesis-card.js 扫到任何 syn.* key，正则或路径可能有问题"

    for lang in (ZH_CN, ZH_TW, EN_US):
        d = _load_dict(lang)
        missing = referenced - set(d.keys())
        assert not missing, f"{lang} 缺少 syn.* keys：{sorted(missing)}"


def test_syn_card_key_sets_identical_across_locales() -> None:
    """三语字典的 syn.* 键集合必须完全一致（防某一语言漏加、造成静默回退）。

    与上一条的区别：上一条以「脚本引用的 key」为准，这条以「三语互相对齐」为准
    ——能抓到「key 加进了 zh-CN 却忘了 zh-TW」这类只影响单一语言的疏漏。
    """
    sets = {
        lang: {k for k in _load_dict(lang) if k.startswith("syn.")}
        for lang in (ZH_CN, ZH_TW, EN_US)
    }
    all_keys = set().union(*sets.values())
    assert all_keys, "三份字典都没有 syn.* key"
    for lang, keys in sets.items():
        assert keys == all_keys, (
            f"{lang} 的 syn.* 键集合与其他语言不一致，差异：{sorted(all_keys ^ keys)}"
        )
