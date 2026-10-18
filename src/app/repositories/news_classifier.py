"""新闻关键词分类器（V0.105）

设计要点
--------
- readhub 内部 API ``/news`` 端点**不带类目参数**（``/news/finance`` 只是
  静态 URL，API 不暴露），后端拿到的数据是 5 大主题（财经/科技/创投/商业/其他）
  混在一起的 20 条流。
- 「UI 想按类目筛选」必须自己在入库时给每条打类目标签。
- V0.105 选 rule-based 关键词分类器：4 类命中关键词字典（顺序优先级：
  财经 > 科技 > 创投 > 商业），无任何关键词命中则兜底「其他」。
- 准确率预期 ~70-80%（rule-based 上限）。V0.106+ 引入 LLM 分类（如有反馈再升级）。

字段
----
- ``CATEGORIES``: 5 个固定标签元组
- ``_FINANCE_KW / _TECH_KW / _VC_KW / _BIZ_KW``: 4 个分类的关键词元组
- ``classify(title, summary, site_name) -> str``: 主入口

性能
----
- 纯 Python 字符串扫描，无外部依赖；单条 < 0.1ms
- 仓储批量 backfill ~64378 行 ~ 6-10s（V0.105 启动钩子里跑）
"""

from __future__ import annotations

# ────────────── 5 类标签（顺序固定：列表渲染与下拉 value 都按这个）──────────────
CATEGORIES: tuple[str, ...] = ("财经", "科技", "创投", "商业", "其他")

# ────────────── 4 个分类的关键词字典（顺序重要：财经优先）──────────────
# 设计原则：宁缺毋滥（关键词需是该类的「显著」标志）。
# 站点名也算关键词（华尔街见闻 / 36 氪 默认归类）。
_FINANCE_KW: tuple[str, ...] = (
    "央行", "汇率", "降息", "加息", "美联储", "通胀", "GDP",
    "PMI", "利率", "国债", "美元", "黄金", "油价", "期货",
    "A 股", "港股", "美股", "股市", "基金", "债券", "理财",
    "财联社", "金十数据", "华尔街见闻", "格隆汇", "中证", "上证",
    "深证", "创业板", "科创板", "沪指", "深成指",
)
_TECH_KW: tuple[str, ...] = (
    "AI", "芯片", "半导体", "算法", "模型", "开源", "大模型",
    "GPT", "量子", "区块链", "5G", "6G", "卫星", "火箭",
    "机器学习", "深度学习", "英伟达", "华为",
    "苹果", "微软", "谷歌", "OpenAI", "Anthropic", "英伟达",
    "算力", "GPU", "CPU", "操作系统", "数据库", "云计算",
    "36 氪", "虎嗅", "极客公园", "量子位",
)
_VC_KW: tuple[str, ...] = (
    "融资", "IPO", "估值", "种子轮", "天使轮", "A 轮", "B 轮",
    "C 轮", "D 轮", "收购", "合并", "被收购", "战略投资", "领投", "跟投",
    "红杉", "高瓴", "IDG", "经纬", "源码资本", "真格基金",
    "独角兽", "上市", "敲钟", "招股书", "募资",
)
_BIZ_KW: tuple[str, ...] = (
    "财报", "营收", "利润", "股价", "市值", "业绩", "季报",
    "年报", "股东大会", "高管", "CEO", "CFO", "COO", "CTO",
    "离职", "任命", "战略合作", "签约", "发布", "新品",
    "供应链", "客户", "订单", "裁员", "重组",
)


def _hit(text: str, keywords: tuple[str, ...]) -> bool:
    """text（小写后）是否包含 keywords 任意一个（小写匹配）。

    大小写不敏感；中文不受 case 影响，英文小写化后匹配。
    """
    return any(kw.lower() in text for kw in keywords)


def classify(title: str, summary: str, site_name: str) -> str:
    """按关键词优先级返回 5 类之一。

    Args:
        title: 新闻标题（必填，非空）
        summary: 摘要（可空字符串；为空时退化为只匹配 title + site_name）
        site_name: 来源站名（可空；为空时退化为只匹配 title + summary）

    Returns:
        5 类之一：「财经」/「科技」/「创投」/「商业」/「其他」。

    Note:
        优先级：财经 > 科技 > 创投 > 商业 > 其他
        - 财经优先：readhub 抓的财经站（华尔街见闻、财联社）流量大，
          财经关键词与商业/创投有重叠（如「估值」「收购」），防误分。
        - 其他兜底：所有 readhub item 必有 title + site_name，所以必落入 5 类之一。
    """
    text = f"{title or ''} {summary or ''} {site_name or ''}".lower()
    if not text.strip():
        return "其他"
    if _hit(text, _FINANCE_KW):
        return "财经"
    if _hit(text, _TECH_KW):
        return "科技"
    if _hit(text, _VC_KW):
        return "创投"
    if _hit(text, _BIZ_KW):
        return "商业"
    return "其他"
