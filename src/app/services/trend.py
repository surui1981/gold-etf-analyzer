"""黄金趋势分析服务：价格序列、均线、趋势参数与市场趋势评估追踪指数。

追踪指数思路（延续 PM-Evaluator 加权评分法）：
对价格趋势的 5 个维度（结构/动量/支撑/动能/回撤）按典型经验赋权，
各自映射为 0-100 评分，加权合成「市场趋势评估指数」，映射为等级。
权重集中在 ``TREND_WEIGHTS``，可按经验直接调整。
"""

from app.repositories.market_data import (
    DEFAULT_GOLD_ETF,
    DEFAULT_GOLD_ETF_NAME,
    DEFAULT_GOLD_GRAM,
    DEFAULT_GOLD_GRAM_NAME,
    DEFAULT_NY_GOLD,
    DEFAULT_NY_GOLD_NAME,
    MarketDataRepository,
)
from app.schemas.common import DirectionSignal
from app.schemas.market import (
    GoldTrendMetrics,
    GoldTrendOut,
    GoldTrendPoint,
    TrendDirection,
    TrendIndicatorOut,
    TrendIndexLevel,
    TrendIndexOut,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 趋势维度权重（典型经验，合计 1.0）
TREND_WEIGHTS: dict[str, float] = {
    "结构": 0.30,  # 均线排列 + MA20 斜率
    "动量": 0.20,  # 近 20 日涨幅
    "支撑": 0.20,  # 价格相对 MA20/MA40 位置
    "动能": 0.15,  # RSI(14)
    "回撤": 0.15,  # 距区间高点回撤
}

# 各标的计价单位（用于摘要）
_TARGET_UNITS = {"etf": "元", "gram": "元/克", "ny": "美元/盎司"}


def moving_average(values: list[float], window: int) -> list[float | None]:
    """计算滑动平均，窗口不足时为 None。

    Args:
        values: 按时间升序的价格序列
        window: 均线窗口

    Returns:
        与输入等长的均线序列（前 window-1 个为 None）
    """
    result: list[float | None] = [None] * len(values)
    acc = 0.0
    for i, v in enumerate(values):
        acc += v
        if i >= window:
            acc -= values[i - window]
        if i >= window - 1:
            result[i] = round(acc / window, 3)
    return result


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """数值截断到 [lo, hi]。"""
    return max(lo, min(hi, value))


def _rsi(closes: list[float], period: int = 14) -> float:
    """计算 RSI(period)，数据不足时返回 50（中性）。

    Args:
        closes: 收盘价序列（升序）
        period: RSI 周期

    Returns:
        RSI 值 0-100
    """
    if len(closes) <= period:
        return 50.0
    gains = losses = 0.0
    for i in range(-period - 1, -1):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    if losses == 0:
        return 100.0
    rs = (gains / period) / (losses / period)
    return _clamp(100 - 100 / (1 + rs), 0, 100)


class TrendService:
    """趋势追踪：价格序列 + 均线 + 参数明细 + 追踪指数。"""

    def __init__(self, repo: MarketDataRepository) -> None:
        self._repo = repo

    async def analyze(self, days: int = 60, target: str = "etf") -> GoldTrendOut:
        """分析黄金近 N 个交易日趋势并合成追踪指数。

        Args:
            days: 覆盖的交易日数量
            target: 标的类型，etf（518880）/ gram（上海金克价）/ ny（纽约金COMEX）

        Returns:
            趋势追踪结果（序列 + 指标 + 参数 + 指数）

        Raises:
            ValueError: 历史数据不足（<2 个交易日）
        """
        klines, symbol, name = await self._load_klines(days=days, target=target)
        if len(klines) < 2:
            raise ValueError("历史数据不足，无法进行趋势分析")

        closes = [k.close for k in klines]
        highs = [k.high for k in klines]
        ma5 = moving_average(closes, 5)
        ma20 = moving_average(closes, 20)
        ma40 = moving_average(closes, 40)

        points = [
            GoldTrendPoint(
                date=k.date,
                close=k.close,
                ma5=ma5[i],
                ma20=ma20[i],
                ma40=ma40[i],
            )
            for i, k in enumerate(klines)
        ]

        start_price, end_price = closes[0], closes[-1]
        change_pct = (end_price - start_price) / start_price * 100 if start_price else 0.0
        direction = self._detect_direction(closes, ma20)
        metrics = GoldTrendMetrics(
            start_date=klines[0].date,
            end_date=klines[-1].date,
            trading_days=len(klines),
            start_price=round(start_price, 3),
            end_price=round(end_price, 3),
            change_pct=round(change_pct, 2),
            high=round(max(highs), 3),
            low=round(min(k.low for k in klines), 3),
            ma20=ma20[-1],
            ma40=ma40[-1],
            direction=direction,
            summary=self._summarize(direction, change_pct, end_price, _TARGET_UNITS.get(target, "元")),
        )

        indicators, index = self._build_index(closes, highs, ma20, ma40)
        logger.info(
            "Trend analyzed: %s days, %s (%+.2f%%), index=%.1f",
            len(klines), direction.value, change_pct, index.score,
        )
        return GoldTrendOut(
            symbol=symbol,
            name=name,
            days=len(klines),
            points=points,
            metrics=metrics,
            indicators=indicators,
            index=index,
        )

    async def _load_klines(
        self,
        days: int,
        target: str,
    ) -> tuple[list[object], str, str]:
        """按标的类型加载 K 线并返回 (klines, symbol, name)。"""
        if target == "ny":
            klines = await self._repo.get_us_gold_history(days=days)
            return klines, DEFAULT_NY_GOLD, DEFAULT_NY_GOLD_NAME
        if target == "gram":
            klines = await self._repo.get_gold_gram_history(days=days)
            return klines, DEFAULT_GOLD_GRAM, DEFAULT_GOLD_GRAM_NAME
        klines = await self._repo.get_gold_history(days=days)
        return klines, DEFAULT_GOLD_ETF, DEFAULT_GOLD_ETF_NAME

    # ---------------- 追踪指数 ----------------

    def _build_index(
        self,
        closes: list[float],
        highs: list[float],
        ma20: list[float | None],
        ma40: list[float | None],
    ) -> tuple[list[TrendIndicatorOut], TrendIndexOut]:
        """计算 5 个趋势维度并加权合成追踪指数。"""
        now_close = closes[-1]
        scores: dict[str, tuple[float, str, DirectionSignal, str]] = {}

        # 1) 结构：均线排列 + MA20 斜率
        align_score, align_desc = self._alignment_score(closes, ma20, ma40)
        slope_pct = self._ma_slope_pct(ma20)
        slope_score = _clamp(50 + slope_pct * 100)  # ±0.5%/日 量级
        scores["结构"] = (
            align_score * 0.6 + slope_score * 0.4,
            f"{align_desc}；MA20近5日{'上行' if slope_pct >= 0 else '下行'} {abs(slope_pct):.2f}%",
            self._to_direction(align_score * 0.6 + slope_score * 0.4),
            "均线排列与MA20斜率",
        )

        # 2) 动量：近 20 日涨幅
        if len(closes) >= 21:
            mom20 = (now_close - closes[-21]) / closes[-21] * 100
        else:
            mom20 = change_pct = (now_close - closes[0]) / closes[0] * 100 if closes[0] else 0
        mom_score = _clamp(50 + mom20 * 8)  # +5% → 90，-5% → 10
        scores["动量"] = (
            mom_score,
            f"近20日 {mom20:+.2f}%",
            self._to_direction(mom_score),
            "近20个交易日涨跌幅",
        )

        # 3) 支撑：价格相对 MA20 / MA40
        support_score, support_desc = self._support_score(now_close, ma20, ma40)
        scores["支撑"] = (
            support_score,
            support_desc,
            self._to_direction(support_score),
            "收盘价相对 MA20/MA40 位置",
        )

        # 4) 动能：RSI(14)
        rsi_val = _rsi(closes)
        rsi_score = _clamp(50 + (rsi_val - 50) * 1.5)  # RSI70→80，30→20
        scores["动能"] = (
            rsi_score,
            f"RSI(14) = {rsi_val:.1f}",
            self._to_direction(rsi_score),
            "相对强弱指标",
        )

        # 5) 回撤：距区间最高收盘的回撤
        peak = max(highs)
        drawdown = (peak - now_close) / peak * 100 if peak else 0.0
        dd_score = _clamp(100 - drawdown * 10)  # 回撤 0 → 100，10% → 0
        scores["回撤"] = (
            dd_score,
            f"距区间高点回撤 {drawdown:.2f}%（高点 {peak:.3f}）",
            self._to_direction(dd_score),
            "回撤控制稳健度",
        )

        # 加权合成
        total = 0.0
        indicators: list[TrendIndicatorOut] = []
        for name, (score, value, direction, detail) in scores.items():
            weight = TREND_WEIGHTS[name]
            contribution = round(score * weight, 2)
            total += contribution
            indicators.append(
                TrendIndicatorOut(
                    name=name,
                    value=value,
                    score=round(score, 1),
                    direction=direction,
                    weight=weight,
                    contribution=contribution,
                    detail=detail,
                )
            )

        total = round(total, 1)
        level, level_dir = self._to_level(total)
        return indicators, TrendIndexOut(
            score=total,
            level=level,
            direction=level_dir,
            summary=self._index_summary(total, level, now_close),
        )

    @staticmethod
    def _alignment_score(
        closes: list[float],
        ma20: list[float | None],
        ma40: list[float | None],
    ) -> tuple[float, str]:
        """均线排列评分：多头排列高分、空头排列低分。"""
        if len(closes) < 40 or ma20[-1] is None or ma40[-1] is None:
            return 50.0, "均线数据不足"
        ma5 = moving_average(closes, 5)[-1]
        if ma5 is None:
            return 50.0, "均线数据不足"

        if ma5 > ma20[-1] > ma40[-1]:
            return 100.0, f"多头排列 MA5({ma5:.3f})>MA20({ma20[-1]:.3f})>MA40({ma40[-1]:.3f})"
        if ma5 < ma20[-1] < ma40[-1]:
            return 0.0, f"空头排列 MA5({ma5:.3f})<MA20({ma20[-1]:.3f})<MA40({ma40[-1]:.3f})"
        return 50.0, f"均线交叉整理 MA5={ma5:.3f} MA20={ma20[-1]:.3f} MA40={ma40[-1]:.3f}"

    @staticmethod
    def _ma_slope_pct(ma20: list[float | None]) -> float:
        """MA20 近 5 日斜率（%）。"""
        if len(ma20) < 6 or ma20[-1] is None or ma20[-6] is None or ma20[-6] == 0:
            return 0.0
        return (ma20[-1] - ma20[-6]) / ma20[-6] * 100

    @staticmethod
    def _support_score(
        now_close: float,
        ma20: list[float | None],
        ma40: list[float | None],
    ) -> tuple[float, str]:
        """价格相对均线位置评分。"""
        desc_parts: list[str] = []
        scores: list[float] = []
        if ma20[-1]:
            bias20 = (now_close - ma20[-1]) / ma20[-1] * 100
            scores.append(_clamp(50 + bias20 * 20))  # ±2.5% 达上下限
            desc_parts.append(f"MA20乖离 {bias20:+.2f}%")
        if ma40[-1]:
            bias40 = (now_close - ma40[-1]) / ma40[-1] * 100
            scores.append(_clamp(50 + bias40 * 15))
            desc_parts.append(f"MA40乖离 {bias40:+.2f}%")
        if not scores:
            return 50.0, "均线数据不足"
        return round(sum(scores) / len(scores), 1), "；".join(desc_parts)

    @staticmethod
    def _to_direction(score: float) -> DirectionSignal:
        """分数 → 多空信号（供页面红绿着色）。"""
        if score >= 60:
            return DirectionSignal.BULLISH
        if score <= 40:
            return DirectionSignal.BEARISH
        return DirectionSignal.NEUTRAL

    @staticmethod
    def _to_level(score: float) -> tuple[TrendIndexLevel, DirectionSignal]:
        """指数分数 → 等级与方向。"""
        if score >= 75:
            return TrendIndexLevel.STRONG_UP, DirectionSignal.BULLISH
        if score >= 55:
            return TrendIndexLevel.UP, DirectionSignal.BULLISH
        if score >= 45:
            return TrendIndexLevel.SIDEWAYS, DirectionSignal.NEUTRAL
        if score >= 25:
            return TrendIndexLevel.DOWN, DirectionSignal.BEARISH
        return TrendIndexLevel.STRONG_DOWN, DirectionSignal.BEARISH

    @staticmethod
    def _index_summary(score: float, level: TrendIndexLevel, end_price: float) -> str:
        """生成追踪指数摘要。"""
        labels = {
            TrendIndexLevel.STRONG_UP: "强势上升",
            TrendIndexLevel.UP: "上升",
            TrendIndexLevel.SIDEWAYS: "震荡整理",
            TrendIndexLevel.DOWN: "下降",
            TrendIndexLevel.STRONG_DOWN: "弱势下降",
        }
        emoji = {
            TrendIndexLevel.STRONG_UP: "🚀",
            TrendIndexLevel.UP: "↗",
            TrendIndexLevel.SIDEWAYS: "→",
            TrendIndexLevel.DOWN: "↘",
            TrendIndexLevel.STRONG_DOWN: "📉",
        }
        return (
            f"市场趋势评估指数 {score:.1f}/100，等级【{labels[level]}】{emoji[level]}，"
            f"最新价 {end_price:.3f} 元。"
            f"{'趋势结构健康，多头动能占优' if score >= 55 else '趋势偏弱，注意风险控制' if score <= 45 else '多空胶着，等待方向选择'}"
        )

    # ---------------- 方向与摘要（沿用） ----------------

    @staticmethod
    def _detect_direction(closes: list[float], ma20: list[float | None]) -> TrendDirection:
        """方向判定：价格相对 MA20 的位置 + MA20 自身斜率。"""
        latest_close = closes[-1]
        cur_ma20 = ma20[-1]
        if cur_ma20 is None:
            return TrendDirection.SIDEWAYS

        ref = ma20[-6] if len(ma20) >= 6 and ma20[-6] is not None else cur_ma20
        ma_slope = cur_ma20 - ref

        if latest_close > cur_ma20 and ma_slope >= 0:
            return TrendDirection.UP
        if latest_close < cur_ma20 and ma_slope <= 0:
            return TrendDirection.DOWN
        return TrendDirection.SIDEWAYS

    @staticmethod
    def _summarize(direction: TrendDirection, change_pct: float, end_price: float, unit: str) -> str:
        """生成面向客户的中文趋势摘要。"""
        emoji = {"up": "↗", "down": "↘", "sideways": "→"}[direction.value]
        labels = {
            TrendDirection.UP: "上升趋势",
            TrendDirection.DOWN: "下降趋势",
            TrendDirection.SIDEWAYS: "震荡整理",
        }
        return (
            f"近2个月{labels[direction]} {emoji}，区间涨跌 {change_pct:+.2f}%，"
            f"最新价 {end_price:.3f} {unit}，价格{'位于' if change_pct >= 0 else '低于'}20日均线"
        )
