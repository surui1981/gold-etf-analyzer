"""宏观参考因子服务：美元指数/美债10Y/30Y/VIX/央行购金 → 黄金友好度评分。

延续 PM-Evaluator 加权评分法：每个宏观因子按与黄金的关系（正/负相关）映射为
0-100 黄金友好度，按典型经验权重加权合成「宏观参考指数」。
权重集中在 ``MACRO_FACTOR_RULES``，可按经验调整。

数据来源：
- 美债 10Y/30Y：AKShare ``bond_zh_us_rate``（中债数据，实时）
- 美元指数 / VIX：沙箱网络无可用实时源，采用内置静态参考值（``STATIC_REF``），
  架构上可平滑替换为实时 provider
- 央行购金：世界黄金协会年度数据（结构性因子，低频更新）
"""

import asyncio
import time

from app.repositories.market_data import _AK_LOCK
from app.schemas.common import DirectionSignal
from app.schemas.market import MacroFactorOut, MacroIndexOut
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 宏观因子规则：权重合计 1.0；友好度 100 分位（最利好黄金）与 0 分位（最利空）
MACRO_FACTOR_RULES: list[dict] = [
    {
        "key": "dxy", "name": "美元指数", "unit": "点位", "weight": 0.25,
        "positive": False, "best": 95.0, "worst": 105.0,  # 美元强 → 黄金弱
    },
    {
        "key": "us10y", "name": "美债10Y收益率", "unit": "%", "weight": 0.20,
        "positive": False, "best": 3.5, "worst": 4.5,
    },
    {
        "key": "us30y", "name": "美债30Y收益率", "unit": "%", "weight": 0.15,
        "positive": False, "best": 4.0, "worst": 5.0,
    },
    {
        "key": "vix", "name": "VIX恐慌指数", "unit": "点位", "weight": 0.15,
        "positive": True, "best": 25.0, "worst": 12.0,  # 恐慌上升 → 避险利好黄金
    },
    {
        "key": "cb_gold", "name": "国际央行购金量", "unit": "吨/年", "weight": 0.25,
        "positive": True, "best": 1200.0, "worst": 500.0,  # 央行持续购金 → 结构性利多
    },
]

# 技术面与宏观面合成权重（典型经验，可调）
TECH_WEIGHT = 0.6
MACRO_WEIGHT = 0.4

# 静态参考值（沙箱无实时源的因子；标注数据日期，后续可接实时 provider）
STATIC_REF: dict[str, dict] = {
    "dxy": {"value": 96.5, "date": "2026-08-28", "note": "静态参考值"},
    "vix": {"value": 18.5, "date": "2026-08-28", "note": "静态参考值"},
    "cb_gold": {"value": 1045.0, "date": "2024年度", "note": "世界黄金协会年度数据"},
}

# 美债实时采集超时（秒）与结果缓存时长（秒）
BOND_TIMEOUT = 15
MACRO_CACHE_TTL = 600  # 10 分钟

# 模块级 TTL 缓存：中债接口偶发挂起，缓存避免每个请求都触发
_CACHE: dict = {"ts": 0.0, "result": None}


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _friendly_score(value: float, rule: dict) -> float:
    """将因子值映射为 0-100 黄金友好度（线性 + 截断）。

    公式 (value - worst) / (best - worst) * 100 天然兼容正/负相关：
    正相关（VIX/央行购金）：value=best → 100 分；负相关（美元/美债）：value=best(低位) → 100 分。
    """
    best, worst = rule["best"], rule["worst"]
    if best == worst:
        return 50.0
    return _clamp((value - worst) / (best - worst) * 100, 0, 100)


class MacroFactorService:
    """宏观参考因子采集与评分。"""

    def __init__(self, settings=None) -> None:
        # 延迟导入避免循环依赖（settings 服务引用 repositories）
        from app.services.settings import WeightService

        self._settings: WeightService | None = settings

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
        values: dict[str, tuple[float, str]] = await self._collect()
        weights = (
            await self._settings.macro_weights()
            if self._settings is not None
            else {}
        )

        total = 0.0
        factors: list[MacroFactorOut] = []
        for rule in MACRO_FACTOR_RULES:
            value, data_date = values[rule["key"]]
            weight = weights.get(rule["key"], rule["weight"])
            score = _friendly_score(value, rule)
            contribution = round(score * weight, 2)
            total += contribution
            direction = (
                DirectionSignal.BULLISH if score >= 60
                else DirectionSignal.BEARISH if score <= 40
                else DirectionSignal.NEUTRAL
            )
            factors.append(
                MacroFactorOut(
                    key=rule["key"],
                    name=rule["name"],
                    value=f"{value:g}",
                    unit=rule["unit"],
                    data_date=data_date,
                    score=round(score, 1),
                    direction=direction,
                    weight=weight,
                    contribution=contribution,
                    detail=f"{rule['name']} {value:g} {rule['unit']}，黄金友好度 {score:.0f}/100",
                )
            )

        total = round(total, 1)
        direction = (
            DirectionSignal.BULLISH if total >= 55
            else DirectionSignal.BEARISH if total <= 45
            else DirectionSignal.NEUTRAL
        )
        logger.info("Macro index: %.1f (%s), %d factors", total, direction.value, len(factors))
        return MacroIndexOut(
            score=total,
            direction=direction,
            factors=factors,
            summary=self._summarize(total, direction),
        )

    async def _collect(self) -> dict[str, tuple[float, str]]:
        """采集各因子当前值：(数值, 数据日期)。美债实时，其余静态。"""
        values: dict[str, tuple[float, str]] = {}
        for key, ref in STATIC_REF.items():
            values[key] = (float(ref["value"]), ref["date"])

        # 美债 10Y/30Y 实时采集（失败保持静态默认）
        try:
            import akshare as ak

            def _fetch() -> tuple[float, float, str]:
                df = ak.bond_zh_us_rate(start_date="20260101")
                row = df.iloc[-1]
                return (
                    float(row["美国国债收益率10年"]),
                    float(row["美国国债收益率30年"]),
                    str(row["日期"]),
                )

            with _AK_LOCK:
                us10y, us30y, d = await asyncio.wait_for(
                    asyncio.to_thread(_fetch), timeout=BOND_TIMEOUT,
                )
            values["us10y"] = (us10y, d)
            values["us30y"] = (us30y, d)
        except (TimeoutError, Exception) as exc:  # noqa: BLE001 —— 超时/失败保持静态参考
            logger.warning("US bond rate fetch failed (%s), use static ref", exc)
            values["us10y"] = (4.4, "2026-08-28")
            values["us30y"] = (4.9, "2026-08-28")
        return values

    @staticmethod
    def _summarize(score: float, direction: DirectionSignal) -> str:
        """宏观参考指数摘要。"""
        txt = {
            DirectionSignal.BULLISH: "宏观环境利好黄金",
            DirectionSignal.BEARISH: "宏观环境利空黄金",
            DirectionSignal.NEUTRAL: "宏观环境中性",
        }[direction]
        return f"宏观参考指数 {score:.1f}/100，{txt}（美元指数、美债收益率、VIX、央行购金）"
