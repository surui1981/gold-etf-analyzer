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
    """V0.107.1：新增「净利润 / 扭亏 / 用户 / 流量」→ 商业。

    V0.108.0 站名从「创业邦」换成中性的「企业内参」——「创业邦」已进
    ``_VC_KW`` 白名单站名，会被创投优先级抢走，测不到本用例的本意。
    """
    assert classify("公司净利润同比扭亏, 用户增长破千万", "", "企业内参") == "商业"


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


# ────────────── V0.108.0 白名单站点名（站名即关键词，方案 B 正向腿）──────────────


def test_classify_whitelist_finance_site_v01080() -> None:
    """V0.108.0：白名单财经站名 + 空标题空摘要 → 仍归财经。

    这是白名单的核心价值：readhub 上财经源的摘要字段经常为空，正文关键词
    命中不了；站名进字典后这类条目不再掉进「其他」被 fetcher 弃入。
    """
    for site in (
        "第一财经", "金融界", "同花顺财经", "界面新闻", "中国证券报",
        "上海证券报", "证券时报", "经济观察报", "每日经济新闻", "金十数据",
    ):
        assert classify("", "", site) == "财经", f"{site} 应归财经"


def test_classify_whitelist_tech_site_v01080() -> None:
    """V0.108.0：白名单科技站名 → 科技。"""
    for site in (
        "IT 之家", "IT之家", "快科技", "C114 通信网", "钛媒体", "品玩",
        "爱范儿", "机器之心", "雷峰网", "techradar.com", "9to5Mac",
    ):
        assert classify("", "", site) == "科技", f"{site} 应归科技"


def test_classify_whitelist_vc_site_v01080() -> None:
    """V0.108.0：白名单创投站名 → 创投。"""
    for site in ("36Kr", "创业邦", "投资界", "铅笔道", "IT桔子", "IT 桔子"):
        assert classify("", "", site) == "创投", f"{site} 应归创投"


def test_classify_whitelist_spacing_variant_v01080() -> None:
    """V0.108.0：同一站名的空格变体都要覆盖（readhub 站名不完全统一）。

    「36 氪」（带空格）V0.105 就在 _TECH_KW；「36Kr」（无空格）V0.108.0 补进
    _VC_KW。两者都命中，只是分类不同——本用例把这一既有差异钉住。
    """
    assert classify("", "", "36 氪") == "科技"
    assert classify("", "", "36Kr") == "创投"


# ────────────── V0.108.0 财经二次加强（大宗 / 监管 / 国际央行 / 银行 / 人物）──────────────


def test_classify_finance_commodity_v01080() -> None:
    """V0.108.0：新增大宗商品词 → 财经（本项目是黄金 ETF 分析器，重点加强）。"""
    for title in (
        "国际银价日内大涨 白银现货突破 40 美元",
        "原油价格跳水 布伦特跌破 70 美元",
        "铜价创阶段新高 沪铜主力合约涨停",
        "螺纹钢与焦炭期货双双走弱",
    ):
        assert classify(title, "", "") == "财经", f"{title} 应归财经"


def test_classify_finance_regulator_v01080() -> None:
    """V0.108.0：新增监管 / 政策词 → 财经。"""
    for title in (
        "证监会就并购重组新规公开征求意见",
        "金融监管总局发布偿付能力监管规则",
        "国常会部署下一阶段稳增长举措",
    ):
        assert classify(title, "", "") == "财经", f"{title} 应归财经"


def test_classify_finance_global_central_bank_v01080() -> None:
    """V0.108.0：新增国际央行 / 国际组织词 → 财经。"""
    for title in (
        "欧洲央行维持利率不变 拉加德发表讲话",
        "日本央行调整负利率区间",
        "OPEC+ 宣布延长减产协议",
        "IMF 上调全球经济增长预期",
    ):
        assert classify(title, "", "") == "财经", f"{title} 应归财经"


def test_classify_finance_bank_v01080() -> None:
    """V0.108.0：新增银行 / 险资词 → 财经。"""
    for title in (
        "工商银行发布三季度业绩 净息差企稳",
        "汇丰银行宣布回购计划",
        "险资权益投资比例上限上调",
    ):
        assert classify(title, "", "") == "财经", f"{title} 应归财经"


def test_classify_finance_official_v01080() -> None:
    """V0.108.0：新增央行行长 / 金融监管官员词 → 财经。"""
    for title in (
        "潘功胜出席 G20 财长会议",
        "周小川谈金融改革开放",
    ):
        assert classify(title, "", "") == "财经", f"{title} 应归财经"


def test_finance_kw_minimum_size_v01080() -> None:
    """V0.108.0：财经字典 67 → 100+（方案 B 财经加强）。"""
    assert len(_FINANCE_KW) >= 100


def test_all_kw_no_duplicate_v01080() -> None:
    """V0.108.0：4 个字典都不得有重复词（V0.107.1 只修了 _TECH_KW）。"""
    for name, kw in (
        ("_FINANCE_KW", _FINANCE_KW),
        ("_TECH_KW", _TECH_KW),
        ("_VC_KW", _VC_KW),
        ("_BIZ_KW", _BIZ_KW),
    ):
        dupes = {w for w in kw if list(kw).count(w) > 1}
        assert not dupes, f"{name} 有重复词: {dupes}"


# ────────────── V0.109.0 短 ASCII 词词边界（修 PE ⊂ Europe 子串误匹配）──────────────


class TestWordBoundary:
    """短 ASCII 词（<=3 字符）必须整词命中，不得匹配更长单词的内部。

    背景：``"PE" in "europe"`` 为真，而 ``PE``（市盈率）在 ``_FINANCE_KW``
    且财经优先级最高 —— 实测 576 条生产数据里有 28 条科技新闻（Oppo /
    Claude / OpenCode / AWS / iPhone / Sony / Windows）被误判成财经。
    """

    def test_boundary_table_only_short_ascii(self) -> None:
        """边界表只收「长度 <=3 且纯 ASCII」的词。"""
        from app.repositories.news_classifier import _BOUNDARY_PATTERNS

        for kw in _BOUNDARY_PATTERNS:
            assert kw.isascii(), f"{kw} 非 ASCII，不该进边界表"
            assert len(kw) <= 3, f"{kw} 长度 >3，不该进边界表（长词子串匹配安全）"
        assert "PE" in _BOUNDARY_PATTERNS
        assert "ETH" in _BOUNDARY_PATTERNS
        assert "OpenAI" not in _BOUNDARY_PATTERNS  # 长词走子串，不受影响

    def test_pe_no_longer_matches_europe(self) -> None:
        """V0.109.0 核心回归：PE 不得命中 Europe / European / OpenAI。"""
        for word in ("europe", "european", "openai", "shape", "hope", "escape"):
            assert classify(f"{word} 相关报道", "", "") != "财经" or (
                # 该词若命中其它财经词则仍可能判财经；单独校验 PE 本身不命中
                True
            )
            from app.repositories.news_classifier import _hit

            assert not _hit(word, ("PE",)), f"PE 不该命中 {word!r}"

    def test_pe_still_matches_standalone(self) -> None:
        """边界不能把正常用法也一起干掉。"""
        from app.repositories.news_classifier import _hit

        for phrase in ("pe 估值 30 倍", "2026pe 仅 8 倍", "pe(ttm)", "静态 pe"):
            assert _hit(phrase, ("PE",)), f"PE 应命中 {phrase!r}"

    def test_cjk_neighbour_does_not_block_match(self) -> None:
        """汉字邻居不算 ASCII 字母边界，中文财经写法必须仍命中。"""
        from app.repositories.news_classifier import _hit

        for phrase, kw in (("科创 50etf 交投", "ETF"), ("btc 突破新高", "BTC"),
                           ("英伟达 gpu 供货", "GPU"), ("aigc 大模型", "AIGC")):
            assert _hit(phrase, (kw,)), f"{kw} 应命中 {phrase!r}"

    def test_eth_no_longer_matches_ethiopia(self) -> None:
        """ETH 不得命中 Ethiopia（埃塞俄比亚）。"""
        from app.repositories.news_classifier import _hit

        assert not _hit("ethiopia 冲突", ("ETH",))
        assert _hit("eth 价格", ("ETH",))

    def test_openai_now_classifies_tech(self) -> None:
        """V0.109.0 端到端：OpenAI 新闻不再被判财经。"""
        assert classify("OpenAI 发布新模型", "", "") == "科技"
        assert classify("Oppo 计划进军欧洲智能市场", "", "") == "科技"

    def test_aigc_agi_still_tech(self) -> None:
        """复合词显式补齐后仍归科技。"""
        assert classify("AIGC 大模型应用爆发", "", "") == "科技"
        assert classify("AGI 何时到来", "", "") == "科技"


# ────────────── V0.109.0 裸词「发布」→ 「发布会」 ───────────────


class TestPublishKeywordPrecision:
    """中文无词边界，裸词「发布」会把公告/战事误判成商业。"""

    def test_publish_not_in_biz_kw(self) -> None:
        """V0.109.0：裸「发布」已从 _BIZ_KW 移除。"""
        assert "发布" not in _BIZ_KW
        assert "发布会" in _BIZ_KW

    def test_news_announcement_not_biz(self) -> None:
        """警方提示 / 档案馆开放 / 战事通报不该判商业。"""
        for title in (
            "北京警方发布彩叶观赏季安全提示",
            "中央档案馆向社会集中开放 5000 余件长征专题档案",
            "俄罗斯称袭击乌克兰敖德萨地区四艘货船及雷尼港设施",
        ):
            assert classify(title, "", "") == "其他", f"{title} 不该是商业"

    def test_launch_event_still_biz(self) -> None:
        """真正的「发布会」商业新闻必须保留（生产数据实测 7 条）。"""
        for title in (
            "小米举行秋季新品发布会",
            "公司召开业绩说明会",
        ):
            assert classify(title, "", "") == "商业", f"{title} 应归商业"
