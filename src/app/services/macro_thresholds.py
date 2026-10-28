"""宏观阈值动态计算器（V0.79.0 Step E）。

把 ``MACRO_FACTOR_RULES`` 的静态 ``best/worst`` 替换成「近 252 个交易日滚动 90/10
分位」，数据不足回退 hardcode 默认。

设计要点
--------
- 缓存范式 B（按 ``(target, date.today().isoformat())`` key 隔离），
  参考 ``central_bank_data.py:97-144``；
- ``cb_gold`` 显式跳过滚动（季度合计 → 252 日 252 个相同值 → percentile 全 50
  → 失去动态意义），始终走 ``MACRO_FACTOR_RULES["cb_gold"].best/worst``；
- 单因子样本 < ``min_samples``（默认 60）→ 该因子回退 hardcode；
- ``is_dynamic_active``：**全部**可滚动因子的阈值 ≠ hardcode 默认 → True
  （V0.118.0 口径：因子从 4 扩到 7，沿用旧的 ``>= 4`` 会把「全动态」松成「过半即算」）。

V0.118.0：因子从 5 个扩到 8 个（7 个可滚动）。此前该机制**从未真正生效** ——
``daily_macro_factors`` 只有 18 天样本（< ``min_samples`` 60），所有因子都被
钉在 2020-2023 的硬编码阈值上，``us10y`` / ``us30y`` 长期输出 0 分（死权重）。
``scripts/backfill_macro_factors.py`` 用 H.15 / FRED / Yahoo 的自带历史回填
252 个交易日后，滚动分位才会接管。

⚠️ 随之暴露的既有缺陷（V0.118.0 一并修掉）：滚动分位的 best/worst 方向此前
**不跟因子的符号约定走**（一律 best=P90）。负相关因子（美元 / 三档美债 /
实际利率 / 利差，共 6 个、占宏观权重 65%）因此整个反向 —— 美元指数创 8 个月
新高会被判成「最利多黄金」给 100 分。该缺陷此前因样本不足而休眠，回填后必现。
"""

import asyncio
import time
from datetime import date

from app.repositories.macro_factor_history import MacroFactorHistoryRepository
from app.services.macro import MACRO_FACTOR_RULES, SKIP_ROLLING_FACTORS
from app.utils.logger import get_logger

logger = get_logger(__name__)

# cb_gold 是季度合计，每日 _collect() 返回同一滚动 12 月合计值，
# 252 日 252 个相同值 → percentile 全 50 → 失去动态意义。
# 因此 calculator 显式跳过 cb_gold，始终走 MACRO_FACTOR_RULES 中的 hardcode。
# V0.119.0：政府债务组（季度/年度）是同一类问题 —— 清单统一在
# ``services/macro.py::SKIP_ROLLING_FACTORS``（前端也要用它算「N/M」分母）。
_SKIP_ROLLING_FACTORS = SKIP_ROLLING_FACTORS


def _percentile(sorted_values: list[float], pct: float) -> float:
    """线性插值 percentile（与 numpy.percentile(method="linear") 一致）。

    ``sorted_values`` 必须已排序。``pct`` 在 [0, 100]。
    """
    n = len(sorted_values)
    if n == 0:
        return 0.0
    if n == 1:
        return float(sorted_values[0])
    rank = (pct / 100.0) * (n - 1)
    lower = int(rank)
    upper = min(lower + 1, n - 1)
    frac = rank - lower
    return float(sorted_values[lower] * (1 - frac) + sorted_values[upper] * frac)


class MacroThresholdCalculator:
    """V0.79.0 Step E：滚动百分位动态阈值计算器。

    V0.120.0：这个类不再只服务宏观面 —— 「资金流面」复用它算自己的滚动分位，
    差别通过三个可注入项表达：

    - ``rules``：因子规则清单（资金流面传 ``MONEY_FLOW_FACTOR_RULES``）；
    - ``skip_rolling``：不参与滚动分位的因子集合（宏观面默认低频因子组；
      资金流面传空集 —— 6 个因子全部可滚动）；
    - **每条规则可自带 ``window_days`` / ``min_samples``** 覆盖类级默认值。

    ⚠ 为什么必须有「按因子窗口」：宏观因子是**日频**的（默认 252 天窗口）；
    资金流因子是**周频 / 月频**的 —— 同一个 252 天窗口对周频只装得下 36 个观测，
    对月频只有 8 个。窗口不区分节奏 ⇒ 样本不足 ⇒ 阈值永远退回硬编码。
    资金流面的实际窗口：周频 104 周（728 天）、月频 60 月（1826 天）。
    """

    def __init__(
        self,
        repo: MacroFactorHistoryRepository,
        rules: list[dict] | None = None,
        ttl_seconds: int = 86400,
        min_samples: int = 60,
        window_days: int = 252,
        *,
        skip_rolling: frozenset[str] | None = None,
    ) -> None:
        self._repo = repo
        self._rules = rules or MACRO_FACTOR_RULES
        self._ttl_seconds = ttl_seconds
        self._min_samples = min_samples
        self._window_days = window_days
        self._skip_rolling = skip_rolling if skip_rolling is not None else SKIP_ROLLING_FACTORS
        # 模块级缓存 —— 进程内所有 calculator 实例共享（同一进程内阈值唯一）
        # V0.120.0：缓存值从 2 元组扩成 3 元组，第三个元素是
        # **本轮真正走了滚动分位的因子集合**（见 ``rolling_keys``）。
        self._cache: dict[
            tuple[str, str],
            tuple[float, dict[str, tuple[float, float]], frozenset[str]],
        ] = {}
        self._lock = asyncio.Lock()

    def _rules_hardcode(self) -> dict[str, tuple[float, float]]:
        """全部因子的 hardcode 默认 best/worst（按 factor_key 索引）。"""
        return {r["key"]: (float(r["best"]), float(r["worst"])) for r in self._rules}

    async def get_or_compute(
        self,
        target: str,
        today: date | None = None,
    ) -> dict[str, tuple[float, float]]:
        """返回 ``{factor_key: (best_dynamic, worst_dynamic)}``。

        cache hit → 直接返回；miss → 持锁查 252 日滚动表 + percentile → 写缓存。

        - ``cb_gold`` 始终走 hardcode；
        - 单因子样本 < ``min_samples`` → 该因子回退 hardcode；
        - 缓存 key 用 ``today.isoformat()``：跨日翻页时缓存自然失效。
        """
        day = today or date.today()
        key = (target, day.isoformat())

        # 快速路径：无锁读缓存
        cached = self._cache.get(key)
        if cached is not None and (time.time() - cached[0]) < self._ttl_seconds:
            return cached[1]

        # miss：持锁期间完成计算（避免并发重复 percentile）
        async with self._lock:
            cached = self._cache.get(key)
            if cached is not None and (time.time() - cached[0]) < self._ttl_seconds:
                return cached[1]

            thresholds, rolling = await self._compute_uncached(target, day)
            self._cache[key] = (time.time(), thresholds, rolling)
            logger.debug(
                "Macro threshold computed: target=%s date=%s factors=%d rolling=%d",
                target,
                day.isoformat(),
                len(thresholds),
                len(rolling),
            )
            return thresholds

    async def _compute_uncached(
        self, target: str, today: date
    ) -> tuple[dict[str, tuple[float, float]], frozenset[str]]:
        """持锁期间执行：查表 + percentile。

        返回 ``(thresholds, rolling_keys)`` —— ``rolling_keys`` 是**本轮真的
        用了滚动分位**的因子集合。

        ⚠️ 为什么要显式返回集合，而不是靠「阈值 ≠ hardcode」反推（V0.120.0 修）：
        静态 best/worst 与滚动分位**可能算出同一个数** —— 资金流面
        ``cn_money_gap`` 的静态带就是拿同一段 5 年历史标定的，滚动算出来
        P10=-11.2 / P90=-3.1，与静态带**逐位相同**。用「值不等即动态」判，
        这个因子会被误报成「还在用静态阈值」⇒ badge 说 5/6、
        ``flow_dynamic=False``，而真相是 6/6 都在滚动分位上。
        """
        hardcode = self._rules_hardcode()
        thresholds: dict[str, tuple[float, float]] = {}
        rolling: set[str] = set()

        for rule in self._rules:
            key = rule["key"]
            # 低频因子显式跳过滚动（永远走 hardcode）
            if key in self._skip_rolling:
                thresholds[key] = hardcode[key]
                continue

            # V0.120.0：窗口与样本门槛可按因子覆盖（周频 / 月频节奏不同）
            window_days = int(rule.get("window_days") or self._window_days)
            min_samples = int(rule.get("min_samples") or self._min_samples)
            samples = await self._repo.get_window(
                target=target,
                factor_key=key,
                days=window_days,
                end_date=today,
            )
            if len(samples) < min_samples:
                thresholds[key] = hardcode[key]
                continue

            values = sorted(float(s.value) for s in samples)
            # best/worst 的方向必须与因子的**符号约定**一致。
            #
            #   positive=True  （VIX / 央行购金）→ 值越高越利多黄金：best=P90、worst=P10
            #   positive=False （美元 / 三档美债 / 实际利率 / 10Y-2Y 利差）
            #                 → 值越低越利多黄金：best=P10、worst=P90
            #
            # ⚠️ V0.118.0 修复：此前**所有**因子一律 best=P90，对 6 个负相关因子
            # 方向整个反了（美元指数创 8 个月新高 → 反而给 100 分「最利多黄金」）。
            # 该缺陷在 V0.79.0 之后一直休眠 —— 滚动窗口样本不足，从未真正激活；
            # 一旦按计划回填历史让滚动分位接管，6 个因子（占宏观权重 65%）会集体反向。
            p10 = _percentile(values, 10.0)
            p90 = _percentile(values, 90.0)
            if bool(rule.get("positive", True)):
                thresholds[key] = (p90, p10)
            else:
                thresholds[key] = (p10, p90)
            rolling.add(key)

        return thresholds, frozenset(rolling)

    def rolling_keys(self, target: str, today: date | None = None) -> frozenset[str]:
        """本轮**真的走了滚动分位**的因子集合。

        - 已计算过（缓存命中或刚算完）→ 返回精确集合；
        - 从未计算过 → 空集合（此时应回退到「值 ≠ hardcode」的旧判据）。
        """
        key = (target, (today or date.today()).isoformat())
        cached = self._cache.get(key)
        if cached is None:
            return frozenset()
        return cached[2]

    async def warm_cache(self, target: str, today: date | None = None) -> None:
        """scheduler / 启动预热：主动 ``get_or_compute`` 并写缓存。"""
        await self.get_or_compute(target, today)

    def is_dynamic_active(
        self,
        thresholds: dict[str, tuple[float, float]],
        *,
        target: str | None = None,
        today: date | None = None,
    ) -> bool:
        """**全部**可滚动因子的阈值都来自滚动分位 → True。

        口径说明（V0.118.0）：V0.79.0 当时只有 4 个可滚动因子，阈值写成硬编码
        ``>= 4``，语义其实是「4 个全都动态才算动态」。因子扩到 8 个（7 个可滚动）
        后若照抄 ``>= 4``，语义会从「全动态」松成「过半即算」—— badge 会说
        「使用滚动分位」，但仍有 3 个因子其实还在用 2020-2023 的硬编码阈值。
        因此这里改成**按可滚动因子总数**判定，语义与旧版一致。

        任一因子样本不足（< ``min_samples``）→ 该因子回退 hardcode → 整体判 False，
        与旧版「3/4 → False」的行为对齐。

        ⚠️ V0.120.0：判定依据从「阈值 ≠ hardcode」改成**优先用计算器记录的
        滚动集**（``rolling_keys``）。原因：滚动分位算出来的 best/worst 可能
        **恰好等于**静态带（静态带就是拿同一段历史标定的）⇒ 值比较会把这个
        因子误报成「还在用静态阈值」。传了 ``target`` 就走精确路径；
        没传（老调用方 / 单元测试直接喂字典）则回退到值比较，行为不变。
        """
        hardcode = self._rules_hardcode()
        rolling = [k for k in hardcode if k not in self._skip_rolling]
        if not rolling:
            return False
        if target is not None:
            applied = self.rolling_keys(target, today)
            # 只有当计算器确实为本 (target, day) 算过，才用精确集合判定
            if (
                applied
                or self._cache.get((target, (today or date.today()).isoformat())) is not None
            ):
                return set(rolling).issubset(applied)
        dynamic_count = sum(1 for k in rolling if thresholds.get(k) != hardcode[k])
        return dynamic_count >= len(rolling)
