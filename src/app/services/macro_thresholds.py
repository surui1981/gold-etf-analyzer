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
- ``is_dynamic_active``：至少 4 个因子阈值 ≠ hardcode 默认 → True。
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
            # best = P90（最利好值），worst = P10（最利空值）
            thresholds[key] = (
                _percentile(values, 90.0),
                _percentile(values, 10.0),
            )

        return thresholds

    async def warm_cache(self, target: str, today: date | None = None) -> None:
        """scheduler / 启动预热：主动 ``get_or_compute`` 并写缓存。"""
        await self.get_or_compute(target, today)

    def is_dynamic_active(self, thresholds: dict[str, tuple[float, float]]) -> bool:
        """5 因子中至少 4 个因子阈值 ≠ hardcode 默认 → True。

        loose 判定：单一因子回退不污染整体语义（4/5 仍算 dynamic）。
        """
        hardcode = self._rules_hardcode()
        dynamic_count = sum(
            1 for k, (b, w) in thresholds.items() if k in hardcode and (b, w) != hardcode[k]
        )
        return dynamic_count >= 4
