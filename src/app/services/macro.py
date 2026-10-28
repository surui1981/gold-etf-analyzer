"""宏观参考因子服务：美元指数/美债2Y·10Y·30Y/曲线利差/实际利率/VIX/央行购金 → 黄金友好度评分。

延续 PM-Evaluator 加权评分法：每个宏观因子按与黄金的关系（正/负相关）映射为
0-100 黄金友好度，按典型经验权重加权合成「宏观参考指数」。
权重集中在 ``MACRO_FACTOR_RULES``，可按经验调整。

V0.119.0 因子集（11 个）与权重
----------------------------
=========================  ======  ==========================================
因子                       权重     数据源
=========================  ======  ==========================================
``dxy`` 美元指数            13%    Yahoo ``DX-Y.NYB``（V0.118.0 前是静态常量）
``us2y`` 美债 2Y            5%    美联储 H.15 ``RIFLGFCY02_N.B``
``us10y`` 美债 10Y          7%    美联储 H.15 ``RIFLGFCY10_N.B``
``us30y`` 美债 30Y          5%    美联储 H.15 ``RIFLGFCY30_N.B``
``curve_10y2y`` 10Y-2Y 利差 9%    由上面两个**派生**
``real10y`` 10Y 实际利率     18%    FRED ``DFII10``（10Y TIPS 实际收益率）
``vix`` VIX                 9%    FRED ``VIXCLS``
``cb_gold`` 央行购金        22%    世界黄金协会 GDT 季度数据 / 本地表汇总
``us_gov_debt`` 美国政府债务  5%    FRED ``GFDEGDQ188S``（CBO，季度）
``cn_gov_debt`` 中国政府债务  4%    FRED ``GGGDTACNA188N``（IMF WEO，年度）
``eu_gov_debt`` 欧洲政府债务  3%    Eurostat ``GOV_10Q_GGDEBT``（季度）
=========================  ======  ==========================================

分组看：美元 13% / 名义利率水平 17% / 曲线形态 9% / 实际利率 18% /
风险偏好 9% / 结构性需求 22% / **政府债务 12%**。

V0.119.0 的两个调整
------------------
1. **政府债务组 12%（美 5 / 中 4 / 欧 3）**：旧 8 个因子按 ×0.88 **等比缩放**
   （相对比例完全不动），腾出 12% 给新增的财政轴。组内分配依据是「对黄金的
   相关性 + 传导链长度」：美国是储备货币发行国、债务上限/期限溢价是当前主线；
   中国债务率五年从 59% 冲到 88%（变动最快），且与模型里全是美国口径的
   ``real10y``/``dxy`` 相关性最低，对中国黄金 ETF 的国内需求传导最直接；
   欧洲最稳、黄金 beta 最小（欧央行几乎不购金）。
2. **符号取「债务↑ = 利多黄金」（debasement / 财政货币化口径）**：反向通道
   （债务↑→实际利率↑→金价跌）已由 ``real10y``（18%）承担，再加一遍是重复计权。
   代价是诚实的：三大经济体债务都在历史高位，这一组会给宏观面一个**近乎恒定
   的偏多偏移**（2026-10-26 实测：宏观面 33.6 → 38.9，**+5.3 分**）—— 它是慢锚
   与分散化，不是择时信号。⚠️ 这个偏移量**不是常数**：其余 7 个因子的分值会随
   滚动分位漂移，方向断点（组权重多大时宏观面从 BEARISH 跳到 NEUTRAL）也跟着动。

数据来源
--------
- 美债 2Y/10Y/30Y：美联储 H.15 收益率曲线（官方源，T+1~T+3 滞后）；
  ``fetch_us_treasury_h15`` 拉取，单文件含 11 个期限
- 10Y-2Y 利差：**派生**（10Y − 2Y），不是独立行情源
- 10Y 实际利率：FRED ``DFII10``（零 KEY CSV 端点）
- 美元指数：Yahoo ``DX-Y.NYB``（与 DXY 同尺度，存量手动校准值不失效）
- VIX：FRED ``VIXCLS``（与 VIX 同尺度）
- 央行购金：世界黄金协会 Gold Demand Trends 季度数据（结构性因子，低频更新）；
  采用滚动 12 月（最近 4 个季度合计）作为当前读数
- 政府债务：FRED ``GFDEGDQ188S``（美国，季度）/ ``GGGDTACNA188N``（中国，年度）/
  Eurostat ``GOV_10Q_GGDEBT``（欧盟 27 国，季度）。三者口径均为「一般政府总
  债务 / GDP」；观测日统一归一到**期末**（FRED 用期初日期，Eurostat 用
  ``2026-Q2`` 这种标签，都不是 ISO 日期，前端 ``Date.parse`` 会得到 NaN）

降级与口径
----------
每个因子都有静态兜底（``STATIC_REF``）。**兜底值不是市场读数** ——
``is_persistable_source`` 会把它们挡在 ``daily_macro_factors`` 历史表之外，
否则一次上游故障就会把假常量写进滚动分位窗口，把阈值彻底带偏。

``curve_10y2y`` 的符号约定是本组里**最弱的一档**：倒挂（负利差）= 衰退定价 =
利多黄金，陡峭 = 最不利。2024-2025「牛陡」（2Y 下行带来的陡峭化）伴随黄金大涨
是这一口径的反例 —— 但那次的主因是实际利率下行，已经由 ``real10y`` 单独承担，
不重复计入利差因子。权重 10% 是刻意压低的，用户可自行调低或归零。
"""

import asyncio
import time

from app.schemas.common import DirectionSignal
from app.schemas.market import MacroFactorOut, MacroIndexOut
from app.schemas.thresholds import DirectionThreshold
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 宏观因子规则：权重合计 1.0；友好度 100 分位（最利好黄金）与 0 分位（最利空）
MACRO_FACTOR_RULES: list[dict] = [
    {
        "key": "dxy",
        "name": "美元指数",
        "unit": "点位",
        "weight": 0.13,
        "positive": False,
        "best": 94.0,
        "worst": 107.0,  # 美元强 → 黄金弱
    },
    {
        "key": "us2y",
        "name": "美债2Y收益率",
        "unit": "%",
        "weight": 0.05,
        "positive": False,
        "best": 3.0,
        "worst": 5.0,  # 短端定价的是美联储政策预期 → 偏高 = 偏鹰 = 黄金弱
    },
    {
        "key": "us10y",
        "name": "美债10Y收益率",
        "unit": "%",
        "weight": 0.07,
        "positive": False,
        "best": 3.8,
        "worst": 5.4,
    },
    {
        "key": "us30y",
        "name": "美债30Y收益率",
        "unit": "%",
        "weight": 0.05,
        "positive": False,
        "best": 4.3,
        "worst": 5.7,
    },
    {
        "key": "curve_10y2y",
        "name": "美债10Y-2Y利差",
        "unit": "%",
        "weight": 0.09,
        # 倒挂（利差为负）= 衰退定价 = 利多黄金 → 与利差数值**负相关**
        "positive": False,
        "best": -0.5,
        "worst": 1.5,
    },
    {
        "key": "real10y",
        "name": "美债10Y实际利率",
        "unit": "%",
        "weight": 0.18,
        "positive": False,
        "best": 0.8,
        "worst": 3.2,  # 实际利率是黄金的定价锚 → 越高越压制金价
    },
    {
        "key": "vix",
        "name": "VIX恐慌指数",
        "unit": "点位",
        "weight": 0.09,
        "positive": True,
        "best": 30.0,
        "worst": 13.0,  # 恐慌上升 → 避险利好黄金
    },
    {
        "key": "cb_gold",
        "name": "国际央行购金量",
        "unit": "吨/年",
        "weight": 0.22,
        "positive": True,
        "best": 1200.0,
        "worst": 500.0,  # 央行持续购金 → 结构性利多
        # V0.119.0：WGC GDT 是**季度**数据 ⇒ 与 3 个政府债务因子同口径。
        # 它的 data_date 是自由文本（"2025Q3–2026Q2 滚动12月"）⇒ 前端解析不出
        # 滞后天数，本来就不会亮滞后 chip；这里给 cadence 只是为了挂上
        # 中性的「季度数据」chip，让用户知道这个日期是**季末**而不是今天。
        "cadence": "quarterly",
        "max_lag_days": 300,
    },
    {
        "key": "us_gov_debt",
        "name": "美国政府债务/GDP",
        "unit": "%",
        "weight": 0.05,
        # V0.119.0：债务↑ = 利多黄金（debasement / 财政货币化口径）。
        # 反向通道（债务↑→实际利率↑→金价跌）已由 real10y(18%) 承担，不再重复计权。
        "positive": True,
        "best": 140.0,
        "worst": 60.0,  # 1990s 约 60%；2020 峰值 132.7
        "cadence": "quarterly",
        "max_lag_days": 300,
    },
    {
        "key": "cn_gov_debt",
        "name": "中国政府债务/GDP",
        "unit": "%",
        "weight": 0.04,
        "positive": True,
        "best": 95.0,
        "worst": 40.0,  # 2013-15 约 40%；2024 创历史新高 88.3
        "cadence": "annual",
        # 1100 天 ≈ 3 年，不是「550 天（1.5 年）」。
        #
        # 实测 2026-10-26：FRED 的 IMF WEO 年度序列（GGGDTACNA188N）最新观测是
        # **2024-12-31**（= 664 天前）—— 年度序列的**观测年本身就落后日历 1~2 年**
        # （FRED 只发实际值，预测值不进这条序列）。拿 550 天当阈值的话，这一行
        # **永远亮红灯** —— 常亮的告警等于没有告警（freshness 降级 UX 纪律）。
        #
        # 3 年的语义 = 「WEO 连续 2 次年更没更新」才算源真的断了。
        "max_lag_days": 1100,
    },
    {
        "key": "eu_gov_debt",
        "name": "欧洲政府债务/GDP",
        "unit": "%",
        "weight": 0.03,
        "positive": True,
        "best": 95.0,
        "worst": 60.0,  # 2000-08 约 60-70%；2020-21 峰值 91.4
        "cadence": "quarterly",
        "max_lag_days": 300,
    },
]

#: 不参与「近 252 日滚动 90/10 分位」的因子（低频 / 结构性）
#:
#: 季度/年度因子若参与滚动分位：日频落表会把同一个值重复几十次 ⇒
#: P10 == P90 ⇒ 阈值退化（``_friendly_score`` 撞 ``best == worst`` 恒返回 50），
#: 且样本不足会让 ``is_dynamic_active`` 把**整个宏观面**的「滚动分位」标识打掉。
#: ``cb_gold``（季度合计）是同一类问题的先例。
#:
#: 定义放在这里（而不是 ``macro_thresholds``）是因为 ``MacroIndexOut`` 也要用它
#: 算出「可滚动因子清单」给前端 —— 两处各维护一份清单必然腐化。
SKIP_ROLLING_FACTORS: frozenset[str] = frozenset(
    {"cb_gold", "us_gov_debt", "cn_gov_debt", "eu_gov_debt"}
)

#: 日频因子的更新节奏 + 自动源滞后告警阈值（日历日）
#:
#: V0.119.0 引入：低频因子（季度/年度）的 data_date 天然滞后几百天，
#: 用同一个 4 天阈值会**永久亮红灯** —— 常亮的告警等于没有告警。
#: 低频因子改用自己的 ``max_lag_days``，前端另挂「季度/年度」chip 说明口径。
_DAILY_CADENCE = "daily"
_DAILY_MAX_LAG_DAYS = 4

# 统一补齐节奏字段（只在这里定义一次默认，避免散落两处的默认值互相漂移）
for _rule in MACRO_FACTOR_RULES:
    _rule.setdefault("cadence", _DAILY_CADENCE)
    _rule.setdefault("max_lag_days", _DAILY_MAX_LAG_DAYS)

# 技术面/宏观面/消息面/**资金流面**合成权重（默认 25/35/25/15，中短期 ETF 波段操作）
#
# V0.120.0：加入第 4 个面「资金流面」15%，其余三个面各让 5%。
# 为什么是 15%：够分量（不是装饰参数），又不至于让一个**没有历史、无法回测**的
# 新面压过已有的三维。
TECH_WEIGHT = 0.25
MACRO_WEIGHT = 0.35
NEWS_WEIGHT = 0.25
FLOW_WEIGHT = 0.15

# 静态参考值（外部源失败时的兜底；标注数据日期）
# ⚠️ 这些不是市场读数 —— 不得写入 daily_macro_factors 历史表（见 is_persistable_source）
STATIC_REF: dict[str, dict] = {
    "dxy": {"value": 96.5, "date": "2026-08-28", "note": "静态参考值"},
    "vix": {"value": 18.5, "date": "2026-08-28", "note": "静态参考值"},
    "us2y": {"value": 4.65, "date": "2026-08-28", "note": "静态参考值"},
    "us10y": {"value": 4.40, "date": "2026-08-28", "note": "静态参考值"},
    "us30y": {"value": 4.90, "date": "2026-08-28", "note": "静态参考值"},
    "real10y": {"value": 2.40, "date": "2026-08-28", "note": "静态参考值"},
    "cb_gold": {
        # 滚动 12 月：2025 Q3(337) + 2025 Q4(337) + 2026 Q1(56.5, WGC 下修) + 2026 Q2(288.9, 季度纪录)
        "value": 1019.0,
        "date": "2025Q3–2026Q2 滚动12月",
        "note": "世界黄金协会 GDT Q2 2026（季度明细：Q1 56.5 / Q2 288.9）",
    },
    # V0.119.0 政府债务组（日期用**观测期末**，与 live 源的口径一致）
    "us_gov_debt": {"value": 122.59, "date": "2026-03-31", "note": "静态参考值"},
    "eu_gov_debt": {"value": 82.9, "date": "2026-06-30", "note": "静态参考值"},
    "cn_gov_debt": {"value": 88.33, "date": "2024-12-31", "note": "静态参考值"},
}

#: 静态回退的 source 前缀 —— 这些值**不是**市场读数，不得写入历史表
STATIC_SOURCE_PREFIX = "静态"

#: 「上次成功落库的真实读数」的 source 前缀（V0.118.1）
#:
#: 语义：本次没抓到实时读数，用历史表里**最近一条真的观测**顶上。
#: 它是真实市场读数，但属于**过去某一刻**的读数 —— 因此
#: ① 展示时必须能看出它是降级值（前端据此挂琥珀色 chip）；
#: ② **不得**再落进历史表（否则等于把旧读数记成今天的观测，把滚动分位窗口压平）。
LAST_KNOWN_GOOD_PREFIX = "末次落库"

#: 派生因子的 source 标识
CURVE_SOURCE = "派生 10Y-2Y"


def is_persistable_source(source: str) -> bool:
    """判断某个 source 标识是否代表**本次真的观测到的**市场读数（可写入历史表）。

    ``"静态参考值"`` 是内置常量（dxy/vix 的 2026-08-28 旧值、外部源失败时的兜底），
    写进历史表会污染滚动分位窗口 —— 那样 P10/P90 会被假数据拉偏，
    V0.79.0 Step E 的动态阈值反而比硬编码更糟。

    ``"末次落库·..."``（V0.118.1）是**历史表里的旧读数**顶替本次观测 ——
    值是真的，但它是过去某一刻的读数，写进今天的 snapshot_date 等于谎报观测时间，
    同样会压平滚动分位窗口 ⇒ 也不落表。

    手动输入（``"手动输入"``）是用户从行情终端抄来的真实读数，**可以**写入。
    """
    if source.startswith(STATIC_SOURCE_PREFIX):
        return False
    return not source.startswith(LAST_KNOWN_GOOD_PREFIX)


def source_tier(source: str) -> str:
    """source 标识的取值层级：``"live"`` / ``"lkg"`` / ``"static"``。

    - ``live``：本次真的观测到的读数（自动源 / 手动输入 / 由 live 输入派生的利差）
    - ``lkg``：本次没观测到，用历史表里最近一条真实读数顶上（末次落库）
    - ``static``：内置常量兜底（不是市场读数）

    派生的 ``curve_10y2y`` 取两个输入里**更弱**的一档 —— 一个输入是常量，
    整个利差就不是干净的市场观测。
    """
    if source.startswith(STATIC_SOURCE_PREFIX):
        return "static"
    if source.startswith(LAST_KNOWN_GOOD_PREFIX):
        return "lkg"
    return "live"


#: 层级强度：live > lkg > static（取 min ⇒ 弱的一档胜出）
_TIER_RANK = {"live": 0, "lkg": 1, "static": 2}


# 宏观综合指数结果缓存时长（秒）；底层 fetcher 自带 5min TTL 缓存
MACRO_CACHE_TTL = 600  # 10 分钟

# 模块级 TTL 缓存：中债接口偶发挂起，缓存避免每个请求都触发
_CACHE: dict = {"ts": 0.0, "result": None}


def clear_macro_cache() -> None:
    """失效宏观评分缓存（V0.110.0：保存手动覆盖后必须调用）。

    ``MACRO_CACHE_TTL`` 有 10 分钟，不清的话用户填完覆盖值回到首页看到的仍是旧指数，
    会以为功能没生效 —— 与白银页面 V0.109.2 的「时效不透明」是同一类体验问题。
    """
    global _CACHE
    _CACHE = {"ts": 0.0, "result": None}


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _friendly_score(value: float, rule: dict) -> float:
    """将因子值映射为 0-100 黄金友好度（线性 + 截断）。

    公式 (value - worst) / (best - worst) * 100 天然兼容正/负相关：
    正相关（VIX/央行购金）：value=best → 100 分；负相关（美元/美债/实际利率）：value=best(低位) → 100 分。
    """
    best, worst = rule["best"], rule["worst"]
    if best == worst:
        return 50.0
    return _clamp((value - worst) / (best - worst) * 100, 0, 100)


class MacroFactorService:
    """宏观参考因子采集与评分。"""

    def __init__(
        self,
        settings=None,
        central_bank=None,
        threshold_calculator=None,
        history_repo=None,
    ) -> None:
        # 延迟导入避免循环依赖（settings 服务引用 repositories）
        from app.services.settings import WeightService

        self._settings: WeightService | None = settings
        # 央行购金服务（可选）：注入后 cb_gold 因子从 central_bank_purchases 表自动计算；
        # 未注入时（单测/降级）回退到 STATIC_REF 硬编码值。
        self._central_bank = central_bank
        # V0.79.0 Step E：动态阈值计算器（可选）。未注入时 evaluate 走 hardcode 默认；
        # 注入后逐因子用近 252 日滚动 90/10 分位替换 rule.best/worst。
        self._threshold_calculator = threshold_calculator
        # V0.118.1：宏观因子历史仓储（可选）。注入后，上游源抓不到读数时用
        # 「上次成功落库的真实读数」顶上，而不是 2026-08-28 的内置常量。
        self._history_repo = history_repo

    def _resolve_macro_target(self) -> str:
        """V0.79.0 Step E：标的维度归一。

        8 个宏观因子都是单一全市场源（H.15 / FRED / Yahoo / WGC / 派生），
        不同 target（ny/etf/gram）同日的 factor value 完全一致 → 共享同一份阈值缓存。

        返回 ``"default"``；若后续发现多标的需要差异化（如白银因子阈值需要偏移），
        重写此函数即可，API 不变。
        """
        return "default"

    async def evaluate(self) -> MacroIndexOut:
        """采集宏观因子并合成宏观参考指数（0-100）。

        权重优先级：用户配置（WeightService）> 内置默认（MACRO_FACTOR_RULES）。
        结果 TTL 缓存（``MACRO_CACHE_TTL``），避免中债接口挂起拖垮接口。
        """
        global _CACHE
        if _CACHE["result"] is not None and time.time() - _CACHE["ts"] < MACRO_CACHE_TTL:
            return _CACHE["result"]

        result = await self._evaluate_uncached()
        _CACHE = {"ts": time.time(), "result": result}
        return result

    async def _evaluate_uncached(self) -> MacroIndexOut:
        values: dict[str, tuple[float, str, str]] = await self._collect()
        weights = await self._settings.macro_weights() if self._settings is not None else {}

        # V0.79.0 Step E：每请求只算一次动态阈值（calculator 注入时）。
        # 未注入 → 全 hardcode；注入 → 滚动因子切到 252 日 90/10 分位，cb_gold 永远 hardcode。
        if self._threshold_calculator is not None:
            macro_target = self._resolve_macro_target()
            thresholds = await self._threshold_calculator.get_or_compute(macro_target)
            macro_dynamic = self._threshold_calculator.is_dynamic_active(
                thresholds, target=macro_target
            )
        else:
            macro_target = self._resolve_macro_target()
            thresholds = {
                r["key"]: (float(r["best"]), float(r["worst"])) for r in MACRO_FACTOR_RULES
            }
            macro_dynamic = False

        # V0.118.0：逐因子「是否用滚动分位」明细。
        # macro_dynamic 是「全部可滚动因子都动态」的布尔摘要 —— 只有一个因子样本
        # 不足，它就变 False，但其余因子其实已经在用滚动分位。前端拿这个列表
        # 显示「N/M 个因子使用滚动分位」，比笼统的「数据不足」准确。
        #
        # V0.120.0：改用计算器**记录**的滚动集，而不是「阈值 ≠ hardcode」反推 ——
        # 滚动分位算出的 best/worst 可能恰好等于静态带（静态带就是拿同一段历史
        # 标定的），值比较会把这样的因子误报成「还在用静态阈值」。
        hardcode = {r["key"]: (float(r["best"]), float(r["worst"])) for r in MACRO_FACTOR_RULES}
        applied = (
            self._threshold_calculator.rolling_keys(macro_target)
            if self._threshold_calculator is not None
            else frozenset()
        )
        if applied:
            dynamic_factors = sorted(applied)
        else:
            dynamic_factors = [k for k, v in thresholds.items() if hardcode.get(k) != v]

        total = 0.0
        total_weight = 0.0
        factors: list[MacroFactorOut] = []
        for rule in MACRO_FACTOR_RULES:
            raw = values.get(rule["key"])
            if raw is None:
                # 兜底：绝不让单个因子缺失把整个宏观面打挂（V0.118.0 加固）
                logger.warning("宏观因子 %s 无读数，本轮剔除", rule["key"])
                continue
            value, data_date, source = raw
            weight = weights.get(rule["key"], rule["weight"])
            # 用 dynamic best/worst 替换 rule 副本（_friendly_score 函数体不动）
            rule_eff = dict(rule)
            rule_eff["best"], rule_eff["worst"] = thresholds[rule["key"]]
            score = _friendly_score(value, rule_eff)
            total += score * weight
            total_weight += weight
            direction = (
                DirectionSignal.BULLISH
                if score >= int(DirectionThreshold.NEUTRAL_HIGH)
                else DirectionSignal.BEARISH
                if score <= int(DirectionThreshold.NEUTRAL_LOW)
                else DirectionSignal.NEUTRAL
            )
            factors.append(
                MacroFactorOut(
                    key=rule["key"],
                    name=rule["name"],
                    value=f"{value:g}",
                    unit=rule["unit"],
                    data_date=data_date,
                    source=source,
                    tier=source_tier(source),
                    cadence=rule.get("cadence", _DAILY_CADENCE),
                    max_lag_days=int(rule.get("max_lag_days", _DAILY_MAX_LAG_DAYS)),
                    score=round(score, 1),
                    direction=direction,
                    weight=weight,
                    contribution=0.0,  # 归一化后回填（见下方）
                    detail=f"{rule['name']} {value:g} {rule['unit']}，黄金友好度 {score:.0f}/100",
                )
            )

        # V0.118.0：因子缺失时按「剩余因子权重归一化」计分（与前端预览口径一致：
        # 前端 renderPreview 对缺失面也是按剩余权重归一，而不是用 0 充当分值）。
        # 正常情况下 11 个因子齐全、total_weight == 1.0，该分支不改变任何结果。
        if total_weight > 0 and abs(total_weight - 1.0) > 1e-9:
            logger.warning("宏观因子权重合计 %.4f ≠ 1，按剩余权重归一化", total_weight)
            total = total / total_weight
        for f in factors:
            f.contribution = round(f.score * f.weight / total_weight, 2) if total_weight else 0.0

        total = round(total, 1)
        # V0.78.0：宏观总分方向阈值统一引用 DirectionThreshold
        direction = (
            DirectionSignal.BULLISH
            if total >= int(DirectionThreshold.BULLISH)
            else DirectionSignal.BEARISH
            if total <= int(DirectionThreshold.BEARISH)
            else DirectionSignal.NEUTRAL
        )
        logger.info("Macro index: %.1f (%s), %d factors", total, direction.value, len(factors))
        return MacroIndexOut(
            score=total,
            direction=direction,
            factors=factors,
            summary=self._summarize(total, direction),
            # V0.79.0 Step E：commit 2 内部组装，commit 4 才升 schema 透传到 API
            # 旧 MacroIndexOut 没此字段，Pydantic 默认 extra="ignore" 自动忽略
            macro_dynamic=macro_dynamic,
            dynamic_factors=dynamic_factors,
            # V0.119.0：有资格参与滚动分位的因子清单（前端「N/M」的分母）
            rolling_factors=[
                r["key"] for r in MACRO_FACTOR_RULES if r["key"] not in SKIP_ROLLING_FACTORS
            ],
        )

    async def _collect(self) -> dict[str, tuple[float, str, str]]:
        """采集各因子当前值：(数值, 数据日期, 数据源标识)。

        **优先级链（V0.118.1）**：用户手动覆盖 > 自动数据源（央行购金表 / 美联储
        H.15 / FRED / Yahoo）> **上次成功落库的真实读数** > ``STATIC_REF`` 内置静态参考值。

        覆盖优先级最高的设计理由：自动源随时可能挂掉并静默回退到过期常量；
        用户从行情终端抄进来的当日读数在任何情况下都比它们新，所以只要设了就用。
        覆盖的 ``as_of`` 日期会原样写进 ``data_date``，滞后提示交给前端 ——
        服务端不做静默过期，避免"我明明填了却没生效"的困惑。

        V0.118.0：4 个外部源（H.15 / FRED×2 / Yahoo）**并发**拉取 ——
        串行会让宏观面接口的最坏耗时变成 4×20s。

        V0.118.1：新增「上次成功落库的真实读数」这一层。原先自动源一挂就直接落到
        2026-08-28 的内置常量（dxy 96.5），而历史表里明明存着前几轮抓到的真值
        （dxy 101.81）—— 用户在「宏观因子手动校准」页看到的「当前生效」列因此
        停在两个半月前，且与真实市场差 5 个点。降级必须**可辨认**：
        该层的 source 带 ``末次落库`` 前缀（前端据此挂琥珀色 chip），
        且**不再落表**（旧读数不能被记成今天的观测）。
        """
        values: dict[str, tuple[float, str, str]] = {}
        for key, ref in STATIC_REF.items():
            values[key] = (float(ref["value"]), ref["date"], ref["note"])  # 静态参考值自带 note

        # V0.118.1：先铺「上次成功落库的真实读数」—— 自动源挂掉时的兜底层。
        lkg = await self._collect_last_known_good()
        values.update(lkg)

        # 并发拉取 5 组外部源；任一失败只影响自己的因子
        results = await asyncio.gather(
            self._collect_treasury(),
            self._collect_fred(),
            self._collect_yahoo(),
            self._collect_central_bank(),
            self._collect_eurostat(),
            return_exceptions=True,
        )
        live: dict[str, tuple[float, str, str]] = {}
        for res in results:
            if isinstance(res, BaseException):
                logger.warning("宏观数据源失败（已回退末次落库/静态参考值）: %s", res)
                continue
            live.update(res)
        values.update(live)

        # V0.110.0：用户手动校准值覆盖前几步的一切结果（静态参考 / 自动源 / 末次落库）。
        overrides = await self._apply_manual_overrides()
        values.update(overrides)

        # 派生因子：10Y-2Y 利差。用**生效后**的 10Y/2Y 计算 —— 手动覆盖了 2Y
        # 而没覆盖利差时，利差跟着一起变（口径自洽）。
        if "curve_10y2y" not in overrides:
            v10, d10, s10 = values["us10y"]
            v2y, d2y, s2y = values["us2y"]
            # V0.118.1：派生结果取两个输入里**更弱**的一档 ——
            #   live + live  → 干净的市场观测（可落表）
            #   掺了末次落库 → 混了不同日期的读数（不可落表，标「末次落库·派生」）
            #   掺了静态常量 → 不是市场读数（不可落表，标「静态参考值」）
            tier = max(
                (source_tier(s10), source_tier(s2y)),
                key=lambda t: _TIER_RANK[t],
            )
            # 已经有一份「末次落库」的利差时，别用更弱的静态派生值把它盖掉
            # （历史表可能只有利差没有 10Y/2Y —— 罕见，但降级方向不能反着来）
            existing = values.get("curve_10y2y")
            keep_existing = (
                tier == "static" and existing is not None and source_tier(existing[2]) == "lkg"
            )
            if not keep_existing:
                # 两个输入的 data_date 都是 ISO 日期（YYYY-MM-DD），字典序即时间序 →
                # 取较早的那个：利差的有效期只到它最旧的那个输入为止
                values["curve_10y2y"] = (
                    round(v10 - v2y, 3),
                    min(d10, d2y),
                    {
                        "live": CURVE_SOURCE,
                        "lkg": LAST_KNOWN_GOOD_PREFIX + "·" + CURVE_SOURCE,
                        "static": STATIC_SOURCE_PREFIX + "参考值",
                    }[tier],
                )
        return values

    async def _collect_last_known_good(self) -> dict[str, tuple[float, str, str]]:
        """「上次成功落库的真实读数」兜底层（V0.118.1）。

        取历史表里每个因子最近一条记录。source 加 ``末次落库`` 前缀 ——
        ① 前端据此挂降级 chip；② ``is_persistable_source`` 据此把它挡在历史表外。

        读历史表失败**绝不能**让宏观面挂掉 —— 与覆盖读取同款兜底：记日志、返回空。
        """
        if self._history_repo is None:
            return {}
        try:
            rows = await self._history_repo.get_latest_per_factor(self._resolve_macro_target())
        except Exception as exc:
            logger.warning("末次落库读数不可用（回退静态参考值）: %s", exc)
            return {}
        if not rows:
            return {}
        out: dict[str, tuple[float, str, str]] = {}
        known_keys = {r["key"] for r in MACRO_FACTOR_RULES}
        for key, row in rows.items():
            if key not in known_keys:
                continue
            # 源标识里已经带了「静态参考值」「末次落库」的行理论上不该存在
            # （落表时被挡住了），但历史表可能被手改过 ——
            # 遇到就跳过，别把常量/旧读数当成「末次真值」再降级一次。
            if is_persistable_source(row.source) is False:
                continue
            out[key] = (
                float(row.value),
                row.data_date,
                LAST_KNOWN_GOOD_PREFIX + "·" + row.source,
            )
        if out:
            logger.info(
                "宏观因子降级到末次落库读数: %s",
                sorted(out),
            )
        return out

    # ───────────────────── 各数据源采集 ─────────────────────

    async def _collect_treasury(self) -> dict[str, tuple[float, str, str]]:
        """美联储 H.15：2Y / 10Y / 30Y（同一份 CSV 的三个列）。"""
        from app.repositories.market_data import fetch_us_treasury_h15

        try:
            result = await fetch_us_treasury_h15()
        except Exception as exc:
            logger.warning("US bond rate fetch failed (%s), use static ref", exc)
            return {}
        if result is None:
            logger.warning("H.15 returned None, use static ref")
            return {}
        out: dict[str, tuple[float, str, str]] = {
            "us10y": (result.us10y, result.data_date.isoformat(), "美联储 H.15"),
            "us30y": (result.us30y, result.data_date.isoformat(), "美联储 H.15"),
        }
        # 2Y 是可选列：缺失时保留静态兜底，不牵连 10Y/30Y
        if result.us2y is not None:
            out["us2y"] = (result.us2y, result.data_date.isoformat(), "美联储 H.15")
        else:
            logger.warning("H.15 无 2Y 列数据，us2y 回退静态参考值")
        return out

    async def _collect_fred(self) -> dict[str, tuple[float, str, str]]:
        """FRED：``DFII10``（10Y 实际利率）+ ``VIXCLS``（VIX）。

        V0.119.0 追加**低频**序列（``FRED_PERIODIC_SERIES``）：季度/年度序列
        走单独的 ``fetch_fred_periodic_latest`` —— 它按序列给足回看天数
        （默认 30 天窗口对低频序列一条都取不到），并把观测日归一到**期末**。
        """
        from app.config import get_settings
        from app.repositories.macro_sources import (
            FRED_PERIODIC_SERIES,
            FRED_SERIES,
            fetch_fred_latest,
            fetch_fred_periodic_latest,
        )

        cfg = get_settings()
        out: dict[str, tuple[float, str, str]] = {}
        for series_id, factor_key in FRED_SERIES.items():
            try:
                latest = await fetch_fred_latest(series_id, base_url=cfg.fred_csv_url)
            except Exception as exc:
                logger.warning("FRED %s 取数失败 (%s)，用静态参考值", series_id, exc)
                continue
            if latest is None:
                logger.warning("FRED %s 无数据，用静态参考值", series_id)
                continue
            value, d = latest
            out[factor_key] = (value, d.isoformat(), f"FRED {series_id}")

        for series_id, (factor_key, lookback_days, period) in FRED_PERIODIC_SERIES.items():
            try:
                latest = await fetch_fred_periodic_latest(
                    series_id,
                    base_url=cfg.fred_csv_url,
                    lookback_days=lookback_days,
                    period=period,
                )
            except Exception as exc:
                logger.warning("FRED %s 取数失败 (%s)，用静态参考值", series_id, exc)
                continue
            if latest is None:
                logger.warning("FRED %s 无数据，用静态参考值", series_id)
                continue
            value, d = latest
            out[factor_key] = (value, d.isoformat(), f"FRED {series_id}")
        return out

    async def _collect_eurostat(self) -> dict[str, tuple[float, str, str]]:
        """Eurostat 季度一般政府债务/GDP（欧盟 27 国）。

        官方一手源（马斯特里赫特口径：一般政府总债务 / GDP）。
        实测 2026-10-26：数据集 ``GOV_10Q_GGDEBT``、``geo=EU27_2020`` →
        2026-Q2 = 82.9（EA20 口径同源可得 89.3）。
        """
        from app.config import get_settings
        from app.repositories.macro_sources import (
            EUROSTAT_GOV_DEBT_DATASET,
            fetch_eurostat_gov_debt,
        )

        cfg = get_settings()
        try:
            latest = await fetch_eurostat_gov_debt(base_url=cfg.eurostat_stats_url)
        except Exception as exc:
            logger.warning("Eurostat 取数失败 (%s)，用静态参考值", exc)
            return {}
        if latest is None:
            logger.warning("Eurostat 无数据，用静态参考值")
            return {}
        value, d = latest
        return {"eu_gov_debt": (value, d.isoformat(), f"Eurostat {EUROSTAT_GOV_DEBT_DATASET}")}

    async def _collect_yahoo(self) -> dict[str, tuple[float, str, str]]:
        """Yahoo：``DX-Y.NYB``（美元指数 DXY）。"""
        from app.config import get_settings
        from app.repositories.macro_sources import YAHOO_SYMBOLS, fetch_yahoo_latest

        cfg = get_settings()
        out: dict[str, tuple[float, str, str]] = {}
        for symbol, factor_key in YAHOO_SYMBOLS.items():
            try:
                latest = await fetch_yahoo_latest(symbol, base_url=cfg.yahoo_chart_url)
            except Exception as exc:
                logger.warning("Yahoo %s 取数失败 (%s)，用静态参考值", symbol, exc)
                continue
            if latest is None:
                logger.warning("Yahoo %s 无数据，用静态参考值", symbol)
                continue
            value, d = latest
            out[factor_key] = (value, d.isoformat(), f"Yahoo {symbol}")
        return out

    async def _collect_central_bank(self) -> dict[str, tuple[float, str, str]]:
        """央行购金：优先读 central_bank_purchases 表（注入 central_bank 时）；
        表无数据时回退 STATIC_REF 硬编码值（保证系统永远有值）。"""
        if self._central_bank is None:
            return {}
        try:
            summary = await self._central_bank.summary()
        except Exception as exc:
            logger.warning("central_bank summary failed (%s), use static ref", exc)
            return {}
        if summary.country_count <= 0:
            return {}
        logger.debug(
            "cb_gold from central_bank_purchases: t12m=%.1f (%s)",
            summary.t12m_total,
            summary.t12m_window,
        )
        return {
            "cb_gold": (
                summary.t12m_total,
                summary.t12m_window,
                "央行购金表自动汇总",
            )
        }

    async def _apply_manual_overrides(self) -> dict[str, tuple[float, str, str]]:
        """读取用户手动校准并转成 ``_collect`` 同构的 (值, 日期, 源标识) 三元组。"""
        if self._settings is None:
            return {}
        try:
            active = (await self._settings.macro_overrides()).active()
        except Exception as exc:
            # 覆盖读取失败绝不能让宏观面整体挂掉 —— 回落到自动源 / 静态参考即可
            logger.warning("macro overrides unavailable (%s), keep auto values", exc)
            return {}
        if not active:
            return {}
        out: dict[str, tuple[float, str, str]] = {}
        for key, ov in active.items():
            out[key] = (float(ov.value), ov.as_of.isoformat(), "手动输入")
        logger.info("macro factors overridden by user: %s", sorted(out))
        return out

    @staticmethod
    def _summarize(score: float, direction: DirectionSignal) -> str:
        """宏观参考指数摘要。"""
        txt = {
            DirectionSignal.BULLISH: "宏观环境利好黄金",
            DirectionSignal.BEARISH: "宏观环境利空黄金",
            DirectionSignal.NEUTRAL: "宏观环境中性",
        }[direction]
        return (
            f"宏观参考指数 {score:.1f}/100，{txt}"
            "（美元指数、美债2Y·10Y·30Y、10Y-2Y利差、10Y实际利率、VIX、央行购金、"
            "美/中/欧政府债务）"
        )
