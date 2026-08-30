"""黄金对照服务：ETF（518880） vs 黄金克价（上海金 Au99.99）区间完整指标对照。"""

from app.repositories.market_data import (
    DEFAULT_GOLD_ETF,
    DEFAULT_GOLD_ETF_NAME,
    DEFAULT_GOLD_GRAM,
    DEFAULT_GOLD_GRAM_NAME,
    MarketDataRepository,
)
from app.schemas.market import (
    GoldCompareOut,
    GoldComparePoint,
    GoldCompareSeries,
    TrendDirection,
)
from app.services.trend import moving_average
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _series_metrics(
    symbol: str,
    name: str,
    closes: list[float],
    highs: list[float],
    lows: list[float],
) -> GoldCompareSeries:
    """由价格序列计算完整对照指标（最新价/涨跌/高低/MA/方向）。"""
    start_price, end_price = closes[0], closes[-1]
    change_pct = (end_price - start_price) / start_price * 100 if start_price else 0.0

    ma20 = moving_average(closes, 20)[-1]
    ma40 = moving_average(closes, 40)[-1]

    if change_pct >= 0 and ma20 is not None and end_price > ma20:
        direction = TrendDirection.UP
    elif change_pct < 0 and ma20 is not None and end_price < ma20:
        direction = TrendDirection.DOWN
    else:
        direction = TrendDirection.SIDEWAYS

    return GoldCompareSeries(
        symbol=symbol,
        name=name,
        start_price=round(start_price, 3),
        end_price=round(end_price, 3),
        change_pct=round(change_pct, 2),
        high=round(max(highs), 3),
        low=round(min(lows), 3),
        ma20=ma20,
        ma40=ma40,
        direction=direction,
    )


class GoldCompareService:
    """对照分析：按日期对齐两序列，归一化比较并输出完整指标。"""

    def __init__(self, repo: MarketDataRepository) -> None:
        self._repo = repo

    async def compare(self, days: int = 60) -> GoldCompareOut:
        """生成 ETF 与克价对照（完整指标 + 归一化序列 + 领先判定）。

        Args:
            days: 请求的交易日数量（实际对齐天数以公共日期为准）

        Returns:
            对照结果

        Raises:
            ValueError: 对齐后的公共交易日不足 2 天
        """
        etf_klines = await self._repo.get_gold_history(days=days)
        gram_klines = await self._repo.get_gold_gram_history(days=days)

        etf_map = {k.date: k for k in etf_klines}
        gram_map = {k.date: k for k in gram_klines}
        common_dates = sorted(etf_map.keys() & gram_map.keys())
        if len(common_dates) < 2:
            raise ValueError("ETF 与克价公共交易日不足，无法对照")

        etf_k = [etf_map[d] for d in common_dates]
        gram_k = [gram_map[d] for d in common_dates]
        etf_closes = [k.close for k in etf_k]
        gram_closes = [k.close for k in gram_k]

        # 归一化：区间起点 = 100
        e0, g0 = etf_closes[0], gram_closes[0]
        points = [
            GoldComparePoint(
                date=d,
                etf=round(e / e0 * 100, 2),
                gram=round(g / g0 * 100, 2),
            )
            for d, e, g in zip(common_dates, etf_closes, gram_closes)
        ]

        etf_series = _series_metrics(
            DEFAULT_GOLD_ETF, DEFAULT_GOLD_ETF_NAME,
            etf_closes, [k.high for k in etf_k], [k.low for k in etf_k],
        )
        gram_series = _series_metrics(
            DEFAULT_GOLD_GRAM, DEFAULT_GOLD_GRAM_NAME,
            gram_closes, [k.high for k in gram_k], [k.low for k in gram_k],
        )

        lead_gap = round(abs(etf_series.change_pct - gram_series.change_pct), 2)
        if etf_series.change_pct > gram_series.change_pct:
            leader = "etf"
        elif gram_series.change_pct > etf_series.change_pct:
            leader = "gram"
        else:
            leader = "tie"

        logger.info(
            "Compare: %s days, etf %+.2f%% vs gram %+.2f%%, leader=%s",
            len(common_dates), etf_series.change_pct, gram_series.change_pct, leader,
        )
        return GoldCompareOut(
            days=len(common_dates),
            etf=etf_series,
            gram=gram_series,
            points=points,
            leader=leader,
            lead_gap=lead_gap,
            summary=self._summarize(leader, etf_series.change_pct, gram_series.change_pct, lead_gap),
        )

    @staticmethod
    def _summarize(leader: str, etf_cp: float, gram_cp: float, gap: float) -> str:
        """生成对照摘要（面向客户）。"""
        leader_txt = {
            "etf": f"黄金ETF（{DEFAULT_GOLD_ETF_NAME}）区间表现领先",
            "gram": f"黄金克价（{DEFAULT_GOLD_GRAM_NAME}）区间表现领先",
            "tie": "两者区间表现持平",
        }[leader]
        return (
            f"近2个月对照：ETF {etf_cp:+.2f}% vs 黄金克价 {gram_cp:+.2f}%，"
            f"涨跌幅差 {gap:.2f} 个百分点，{leader_txt}。"
            f"{'（ETF 含管理费与跟踪误差，克价更贴近现货金）' if leader == 'etf' else '（实物金克价更贴近现货，但需考虑买卖价差与保管成本）'}"
        )
