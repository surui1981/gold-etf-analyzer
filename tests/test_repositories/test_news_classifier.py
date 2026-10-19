"""新闻关键词分类器单测（V0.105 / V0.107.1 字典扩充）

V0.105 覆盖：
- 4 类各 1 例（财经/科技/创投/商业）
- 「其他」兜底（无关键词命中）
- 优先级冲突：财经 > 科技 > 创投 > 商业
- site_name 单独命中（如 "华尔街见闻" → 财经）
- 空字符串 + site_name 兜底

V0.107.1 新增：
- 4 类字典规模下限测试
- 4 类新关键词命中测试（行情/硬件公司/风投BP/电商直播等）
- 去重测试（TECH_KW 不再有重复「英伟达」）
"""

from __future__ import annotations

from app.repositories.news_classifier import (
    CATEGORIES,
    _BIZ_KW,
    _FINANCE_KW,
    _TECH_KW,
    _VC_KW,
    classify,
)


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


# ────────────── V0.107.1 字典规模 ──────────────


def test_finance_kw_minimum_size_v01071() -> None:
    """V0.107.1：财经关键词 ≥ 60（原 32 → 60+）。"""
    assert len(_FINANCE_KW) >= 60


def test_tech_kw_minimum_size_v01071() -> None:
    """V0.107.1：科技关键词 ≥ 50（原 33 → 50+）。"""
    assert len(_TECH_KW) >= 50


def test_vc_kw_minimum_size_v01071() -> None:
    """V0.107.1：创投关键词 ≥ 35（原 23 → 35+）。"""
    assert len(_VC_KW) >= 35


def test_biz_kw_minimum_size_v01071() -> None:
    """V0.107.1：商业关键词 ≥ 30（原 22 → 30+）。"""
    assert len(_BIZ_KW) >= 30


def test_tech_kw_no_duplicate_v01071() -> None:
    """V0.107.1：科技字典无重复词（修 L44 旧版「英伟达」bug）。"""
    assert len(_TECH_KW) == len(set(_TECH_KW))


# ────────────── V0.107.1 新关键词命中测试 ──────────────


def test_classify_finance_new_keyword_btc_v01071() -> None:
    """V0.107.1：新增「BTC / ETH」→ 财经。"""
    assert classify("BTC 突破历史新高", "", "币世界") == "财经"


def test_classify_finance_new_keyword_etf_v01071() -> None:
    """V0.107.1：新增「黄金 ETF」→ 财经。"""
    assert classify("黄金 ETF 资金大幅净流入", "", "华尔街见闻") == "财经"


def test_classify_finance_new_keyword_powell_v01071() -> None:
    """V0.107.1：新增「鲍威尔」人物 → 财经（用户人物词）。"""
    assert classify("鲍威尔释放鸽派信号", "", "金十数据") == "财经"


def test_classify_finance_new_keyword_blackrock_v01071() -> None:
    """V0.107.1：新增「贝莱德」机构 → 财经。"""
    assert classify("贝莱德增持黄金资产", "", "") == "财经"


def test_classify_tech_new_keyword_byd_v01071() -> None:
    """V0.107.1：新增「比亚迪」硬件公司 → 科技。"""
    assert classify("比亚迪发布新一代电池", "", "36氪") == "科技"


def test_classify_tech_new_keyword_tsmc_v01071() -> None:
    """V0.107.1：新增「台积电 / 3nm」→ 科技。"""
    assert classify("台积电 3nm 良率突破", "", "TechWeb") == "科技"


def test_classify_tech_new_keyword_robot_v01071() -> None:
    """V0.107.1：新增「机器人 / 脑机接口」前沿 → 科技。"""
    assert classify("国内首条卫星互联网 + 脑机接口", "", "极客公园") == "科技"


def test_classify_vc_new_keyword_vc_fa_v01071() -> None:
    """V0.107.1：新增「FA / 路演 / BP / 财顾」→ 创投。"""
    assert classify("财顾 + FA 主导 本轮 BP 已递交", "", "投资界") == "创投"


def test_classify_vc_new_keyword_gp_lp_v01071() -> None:
    """V0.107.1：新增「GP / LP」身份 → 创投。"""
    assert classify("老牌 GP 募集新 LP 资金", "", "IT桔子") == "创投"


def test_classify_vc_new_keyword_buyback_v01071() -> None:
    """V0.107.1：新增「增发 / 回购 / 借壳」→ 创投。"""
    assert classify("公司宣布借壳上市", "", "") == "创投"


def test_classify_biz_new_keyword_douyin_v01071() -> None:
    """V0.107.1：新增「抖音 / 直播带货 / 跨境」→ 商业。"""
    assert classify("抖音电商 GMV 同比 +30%, 直播带货火热", "", "联商网") == "商业"


def test_classify_biz_new_keyword_going_global_v01071() -> None:
    """V0.107.1：新增「出海 / 国际化」→ 商业。"""
    assert classify("公司宣布出海 加速国际化", "", "") == "商业"


def test_classify_biz_new_keyword_revenue_v01071() -> None:
    """V0.107.1：新增「净利润 / 扭亏 / 用户 / 流量」→ 商业。"""
    assert classify("公司净利润同比扭亏, 用户增长破千万", "", "创业邦") == "商业"


# ────────────── V0.107.1 优先级回归（边界词「估值」/「收购」并存时财经优先）──────────────


def test_classify_finance_overrides_vc_new_v01071() -> None:
    """V0.107.1：财经关键词「贝莱德」与创投「收购」并存 → 财经胜。"""
    assert (
        classify("贝莱德收购某基金", "", "华尔街见闻")
        == "财经"
    )


def test_classify_finance_overrides_tech_new_v01071() -> None:
    """V0.107.1：财经「比特币」与科技「苹果」并存 → 财经胜。"""
    assert classify("苹果公司接受比特币支付", "", "") == "财经"
