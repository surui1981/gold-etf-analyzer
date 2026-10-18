"""新闻关键词分类器单测（V0.105）

覆盖：
- 4 类各 1 例（财经/科技/创投/商业）
- 「其他」兜底（无关键词命中）
- 优先级冲突：财经 > 科技 > 创投 > 商业
- site_name 单独命中（如 "华尔街见闻" → 财经）
- 空字符串 + site_name 兜底
"""

from __future__ import annotations

from app.repositories.news_classifier import CATEGORIES, classify


# ────────────── 4 类各 1 例 ──────────────


def test_classify_finance_keyword_in_title() -> None:
    """「美联储 加息」→ 财经。"""
    assert classify("美联储 11月 暂停加息", "", "华尔街见闻") == "财经"


def test_classify_tech_keyword_in_summary() -> None:
    """摘要含「AI / 芯片」→ 科技。"""
    assert classify("公司新品发布会", "新一代 AI 芯片 性能翻倍", "36氪") == "科技"


def test_classify_vc_keyword_in_text() -> None:
    """「融资 A 轮」→ 创投（设计：摘要不能含财经关键词如「美元」）。"""
    assert classify("某 SaaS 公司完成 B 轮融资", "估值 10 亿", "投资界") == "创投"


def test_classify_business_keyword() -> None:
    """「财报 营收 利润」→ 商业。"""
    assert classify("某公司发布 Q3 财报", "营收同比增长 20%, 利润超预期", "新浪财经") == "商业"


# ────────────── 兜底 / 优先级 ──────────────


def test_classify_other_when_no_keyword_hit() -> None:
    """无任何关键词命中 → 其他。"""
    assert classify("某地发生交通事故", "司机受伤", "地方日报") == "其他"


def test_classify_finance_overrides_vc_when_both_hit() -> None:
    """财经关键词与创投关键词并存 → 财经优先（设计：财经 > 创投）。

    样例：「收购」既可创投可商业，但「美元」是财经，财经胜。
    """
    assert (
        classify("美元基金 收购某创业公司 估值 10 亿", "完成 B 轮融资", "财经网")
        == "财经"
    )


def test_classify_tech_overrides_business() -> None:
    """科技关键词与商业关键词并存 → 科技优先。"""
    assert (
        classify("苹果发布新 iPhone 财报 营收增长", "新品发布会 芯片升级", "虎嗅")
        == "科技"
    )


def test_classify_empty_title_uses_site_name() -> None:
    """title 空但 site_name 是「华尔街见闻」→ 财经（site_name 计入）。"""
    assert classify("", "", "华尔街见闻") == "财经"


def test_classify_all_empty_returns_other() -> None:
    """title/summary/site_name 全空 → 其他。"""
    assert classify("", "", "") == "其他"


def test_classify_categories_constant_is_fixed() -> None:
    """CATEGORIES 常量：5 个固定值，顺序与 UI 渲染一致。"""
    assert CATEGORIES == ("财经", "科技", "创投", "商业", "其他")
