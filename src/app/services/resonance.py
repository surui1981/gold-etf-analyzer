"""共振信号服务（V0.70.0 P2 #7）。

把宏观、技术、消息面三维度方向打包成 4 类信号（STRONG_UP / STRONG_DOWN /
WEAK_UP / DIVERGENT / NEUTRAL），并基于历史给出 STRONG_UP 命中率。

设计取舍
--------
- **纯函数 ``compute_resonance``**：输入 ``TrendIndexOut.components``
  （dict[维度名 → 0-100 分]），输出 ``ResonanceSignalOut``——便于测试与复用。
- **threshold 统一**：macro / tech / news 均以 ≥55 看多、≤45 看空、其余中性
  （与方向判定 ``DirectionSignal`` 一致；不在此处重新定义阈值）。
- **STRONG_UP 命中统计**：复用 ``ReviewService.journal()`` 的
  ``JournalDayOut``（带 T+H outcome），把 ``usable`` 过滤替换为
  「当日 news.score ≥ 55 且 tech ≥ 55 且 macro ≥ 55」。
- **history(days)**：V0.70.0 MVP 只覆盖「今天」+「近 N 天的消息面方向」；
  宏观/技术历史回放留待后续版本（数据基础尚未沉淀每日宏观/技术快照）。
"""

from datetime import date, timedelta
from typing import TYPE_CHECKING

from app.repositories.news import NewsScoreRepository
from app.schemas.common import DirectionSignal
from app.schemas.resonance import (
    ResonanceHistoryOut,
    ResonanceSignalOut,
    StrengthUpStatsOut,
)
from app.services.news import aggregate_slots, direction_of
from app.utils.logger import get_logger

if TYPE_CHECKING:
    from app.services.trend import TrendService

logger = get_logger(__name__)

# 4 类信号阈值（与 DirectionSignal 一致；55/45 是 BULLISH/BEARISH 的临界分）
_THRESH_UP = 55
_THRESH_DOWN = 45
_MIN_SAMPLES = 20

# 中文信号名
_SIGNAL_LABELS = {
    "strong_up": "强共振看多",
    "strong_down": "强共振看空",
    "weak_up": "弱多信号",
    "divergent": "技术/宏观反向",
    "neutral": "中性震荡",
}


def _clip(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def compute_resonance(
    components: dict[str, float],
    score_date: date | None = None,
) -> ResonanceSignalOut:
    """由 TrendIndexOut.components 计算单日共振信号。

    Args:
        components: ``{"tech": ..., "macro": ..., "news": ...}`` 三个 0-100 分；
                    缺维度时按 50（中性）兜底。
        score_date: 日期（signal_today 传 None → 服务层自动填今日）

    Returns:
        ResonanceSignalOut
    """
    tech = components.get("tech", 50.0)
    macro = components.get("macro", 50.0)
    news = components.get("news", 50.0)

    # 4 类判定（顺序：强 → 弱 → 背离 → 中性）
    if tech >= _THRESH_UP and macro >= _THRESH_UP and news >= _THRESH_UP:
        # 强共振：置信度 = 平均 × 一致性折扣（标准差越小越确信）
        avg = (tech + macro + news) / 3
        stdev = ((tech - avg) ** 2 + (macro - avg) ** 2 + (news - avg) ** 2) ** 0.5
        confidence = _clip(avg * (1 - stdev / 55))
        signal = "strong_up"
    elif tech <= _THRESH_DOWN and macro <= _THRESH_DOWN and news <= _THRESH_DOWN:
        avg = (tech + macro + news) / 3
        stdev = ((tech - avg) ** 2 + (macro - avg) ** 2 + (news - avg) ** 2) ** 0.5
        confidence = _clip(avg * (1 - stdev / 55))
        signal = "strong_down"
    elif (tech >= _THRESH_UP) + (macro >= _THRESH_UP) + (news >= _THRESH_UP) >= 2:
        confidence = 65.0
        signal = "weak_up"
    elif (
        # 背离：tech 与 macro 反向（典型反转信号——技术领先，宏观滞后）
        (tech >= _THRESH_UP and macro <= _THRESH_DOWN)
        or (tech <= _THRESH_DOWN and macro >= _THRESH_UP)
    ):
        confidence = _clip((max(tech, macro) - min(tech, macro)) * 0.5)
        signal = "divergent"
    else:
        confidence = 50.0
        signal = "neutral"

    label = _SIGNAL_LABELS.get(signal, "中性")
    return ResonanceSignalOut(
        score_date=score_date,
        signal=signal,
        label=label,
        confidence=round(confidence, 1),
        components={"tech": tech, "macro": macro, "news": news},
        direction_summary=_summarize(tech, macro, news),
    )


def _summarize(tech: float, macro: float, news: float) -> str:
    """一句话中文总结 + 方向标识（供前端红绿着色）。"""
    parts: list[str] = []
    for label, score in (("技术", tech), ("宏观", macro), ("消息", news)):
        if score >= _THRESH_UP:
            parts.append(f"{label}看多({score:.0f})")
        elif score <= _THRESH_DOWN:
            parts.append(f"{label}看空({score:.0f})")
        else:
            parts.append(f"{label}中性({score:.0f})")
    return " · ".join(parts)


class ResonanceService:
    """共振信号业务编排：今日信号、历史回放、STRONG_UP 命中统计。"""

    def __init__(
        self,
        trend: "TrendService",
        news: NewsScoreRepository,
    ) -> None:
        self._trend = trend
        self._news = news

    async def signal_today(self) -> ResonanceSignalOut:
        """今日共振信号：调用 TrendService.analyze() 拿最新 components。"""
        trend_out = await self._trend.analyze(days=60, target="etf")
        components = trend_out.index.components or {}
        result = compute_resonance(components, score_date=date.today())
        logger.info(
            "Resonance signal today: %s (conf=%.1f) components=%s",
            result.signal,
            result.confidence,
            result.components,
        )
        return result

    async def history(self, days: int = 30) -> ResonanceHistoryOut:
        """近 N 天共振历史（按日期倒序）。

        V0.70.0 MVP：技术 + 宏观维度仅返回今日；消息面维度按日回放
        （依赖 ``NewsScoreRepository.list_between``）。数据基础沉淀后
        后续版本可补全。
        """
        days = max(1, min(days, 90))
        today = date.today()
        start = today - timedelta(days=days)

        records = await self._news.list_between(start, today)
        # 按日期分组
        grouped: dict[date, list] = {}
        for r in records:
            grouped.setdefault(r.score_date, []).append(r)

        items: list[ResonanceSignalOut] = []
        for score_date in sorted(grouped.keys(), reverse=True):
            rows = grouped[score_date]
            effective, _, _ = aggregate_slots(rows)
            # 历史回放：tech/macro 按中性 50 兜底（占位），仅 news 有值
            components = {"tech": 50.0, "macro": 50.0, "news": effective}
            items.append(compute_resonance(components, score_date=score_date))

        return ResonanceHistoryOut(
            days=days,
            total=len(items),
            items=items,
        )

    async def strength_up(
        self,
        days: int = 90,
        horizon: int = 1,
    ) -> StrengthUpStatsOut:
        """STRONG_UP 命中统计：当日「强共振看多」在 T+H 的命中率。

        复用 ReviewService 的价格日历 + 消息面分日数据，但因 V0.70.0
        MVP 的历史 tech/macro 暂未沉淀，本实现按 **消息面方向 ≥ BULLISH 且
        effective_score ≥ 55** 作为「历史 STRONG_UP」的代理。
        """
        days = max(1, min(days, 365))
        horizon = horizon if horizon in (1, 3, 5) else 1

        today = date.today()
        start = today - timedelta(days=days + 10)  # 多取 10 天缓冲

        records = await self._news.list_between(start, today)
        if not records:
            return StrengthUpStatsOut(
                days=days,
                horizon=horizon,
                total_strong_up=0,
                resolved=0,
                hits=0,
                hit_rate=None,
                sample_warning=True,
                note="窗口内无消息面打分记录",
            )

        # 直接从 trend 的 market repo 拉 ETF 价格序列
        prices = await self._trend._repo.get_gold_history(days=days + 20)
        px_index: dict[date, float] = {p.date: float(p.close) for p in prices}
        px_dates = sorted(px_index.keys())

        from bisect import bisect_right

        # 按日期聚合
        grouped: dict[date, list] = {}
        for r in records:
            grouped.setdefault(r.score_date, []).append(r)

        strong_up_dates: list[date] = []
        for score_date, rows in grouped.items():
            effective, _, _ = aggregate_slots(rows)
            if effective >= 55 and direction_of(effective) is DirectionSignal.BULLISH:
                strong_up_dates.append(score_date)

        # 计算 T+H 命中
        hits = 0
        resolved = 0
        for d in strong_up_dates:
            base_idx = bisect_right(px_dates, d) - 1
            if base_idx < 0 or px_dates[base_idx] != d:
                continue
            target_idx = base_idx + horizon
            if target_idx >= len(px_dates):
                continue
            base_close = px_index[px_dates[base_idx]]
            target_close = px_index[px_dates[target_idx]]
            if base_close <= 0:
                continue
            change_pct = (target_close - base_close) / base_close * 100
            if change_pct > 0:
                hits += 1
            resolved += 1

        hit_rate = round(hits / resolved * 100, 1) if resolved else None
        sample_warning = resolved < _MIN_SAMPLES
        note = f"样本 {resolved} 天（STRONG_UP 信号 {len(strong_up_dates)} 天），" + (
            f"低于 {_MIN_SAMPLES} 天时统计波动较大，仅供参考"
            if sample_warning
            else f"T+{horizon} 命中率 {hit_rate}%"
        )

        return StrengthUpStatsOut(
            days=days,
            horizon=horizon,
            total_strong_up=len(strong_up_dates),
            resolved=resolved,
            hits=hits,
            hit_rate=hit_rate,
            sample_warning=sample_warning,
            note=note,
        )


__all__ = ["ResonanceService", "compute_resonance"]
