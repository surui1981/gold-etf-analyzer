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
from app.services.macro import MACRO_FACTOR_RULES
from app.utils.logger import get_logger

logger = get_logger(__name__)

# cb_gold 是季度合计，每日 _collect() 返回同一滚动 12 月合计值，
# 252 日 252 个相同值 → percentile 全 50 → 失去动态意义。
# 因此 calculator 显式跳过 cb_gold，始终走 MACRO_FACTOR_RULES 中的 hardcode。
_SKIP_ROLLING_FACTORS = frozenset({"cb_gold"})


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
    """V0.79.0 Step E：滚动百分位动态阈值计算器。"""

    def __init__(
        self,
        repo: MacroFactorHistoryRepository,
        rules: list[dict] | None = None,
        ttl_seconds: int = 86400,
        min_samples: int = 60,
        window_days: int = 252,
    ) -> None:
        self._repo = repo
        self._rules = rules or MACRO_FACTOR_RULES
        self._ttl_seconds = ttl_seconds
        self._min_samples = min_samples
        self._window_days = window_days
        # 模块级缓存 —— 进程内所有 calculator 实例共享（同一进程内阈值唯一）
        self._cache: dict[tuple[str, str], tuple[float, dict[str, tuple[float, float]]]] = {}
        self._lock = asyncio.Lock()

    def _rules_hardcode(self) -> dict[str, tuple[float, float]]:
        """5 因子的 hardcode 默认 best/worst（按 factor_key 索引）。"""
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

            thresholds = await self._compute_uncached(target, day)
            self._cache[key] = (time.time(), thresholds)
            logger.debug(
                "Macro threshold computed: target=%s date=%s factors=%d",
                target,
                day.isoformat(),
                len(thresholds),
            )
            return thresholds

    async def _compute_uncached(self, target: str, today: date) -> dict[str, tuple[float, float]]:
        """持锁期间执行：查表 + percentile。"""
        hardcode = self._rules_hardcode()
        thresholds: dict[str, tuple[float, float]] = {}

        for rule in self._rules:
            key = rule["key"]
            # cb_gold 显式跳过滚动（永远走 hardcode）
            if key in _SKIP_ROLLING_FACTORS:
                thresholds[key] = hardcode[key]
                continue

            samples = await self._repo.get_window(
                target=target,
                factor_key=key,
                days=self._window_days,
                end_date=today,
            )
            if len(samples) < self._min_samples:
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

        return thresholds

    async def warm_cache(self, target: str, today: date | None = None) -> None:
        """scheduler / 启动预热：主动 ``get_or_compute`` 并写缓存。"""
        await self.get_or_compute(target, today)

    def is_dynamic_active(self, thresholds: dict[str, tuple[float, float]]) -> bool:
        """**全部**可滚动因子的阈值都 ≠ hardcode 默认 → True。

        口径说明（V0.118.0）：V0.79.0 当时只有 4 个可滚动因子，阈值写成硬编码
        ``>= 4``，语义其实是「4 个全都动态才算动态」。因子扩到 8 个（7 个可滚动）
        后若照抄 ``>= 4``，语义会从「全动态」松成「过半即算」—— badge 会说
        「使用滚动分位」，但仍有 3 个因子其实还在用 2020-2023 的硬编码阈值。
        因此这里改成**按可滚动因子总数**判定，语义与旧版一致。

        任一因子样本不足（< ``min_samples``）→ 该因子回退 hardcode → 整体判 False，
        与旧版「3/4 → False」的行为对齐。
        """
        hardcode = self._rules_hardcode()
        rolling = [k for k in hardcode if k not in _SKIP_ROLLING_FACTORS]
        if not rolling:
            return False
        dynamic_count = sum(1 for k in rolling if thresholds.get(k) != hardcode[k])
        return dynamic_count >= len(rolling)
