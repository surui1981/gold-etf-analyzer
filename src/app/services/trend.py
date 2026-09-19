"""黄金趋势分析服务：价格序列、均线、趋势参数与市场趋势评估追踪指数。

追踪指数思路（延续 PM-Evaluator 加权评分法）：
对价格趋势的 5 个维度（结构/动量/支撑/动能/回撤）按典型经验赋权，
各自映射为 0-100 评分，加权合成「市场趋势评估指数」，映射为等级。
权重集中在 ``TREND_WEIGHTS``，可按经验直接调整。

每日重算策略
------------
- ``analyze()`` 命中当日缓存时**直接返回 GoldTrendOut**（页面秒级加载）；
- 缓存由 ``services/cache.py`` 提供，key 为 (target, interval, date)，跨日自动失效；
- 消息面评分更新通过 ``invalidate_for_news()`` 主动失效，下次请求全量重算；
- ``scheduler.py`` 在北京时间 07:00 自动预生成（首屏直接命中缓存）。

多时间框架（V0.64.0）
-------------------
- ``analyze()`` 新增 ``interval`` 参数：D=日 K（默认）/ W=周 K / M=月 K；
- 周 K 按 ISO 周界聚合（``(year, week)``），月 K 按 ``(year, month)`` 聚合；
- 聚合后 MA5/MA20/MA40 在新序列上重算（周线 MA5 ≈ 1 交易月，月线 MA5 ≈ 5 交易月）；
- W/M 模式下技术面 indicators 旁路（指标对日 K 序列敏感，聚合后无意义）；
  宏观 + 消息面仍正常合成综合指数。
"""

from datetime import datetime, timezone
from typing import Literal

from app.repositories.market_data import (
    DEFAULT_GOLD_ETF,
    DEFAULT_GOLD_ETF_NAME,
    DEFAULT_GOLD_GRAM,
    DEFAULT_GOLD_GRAM_NAME,
    DEFAULT_NY_GOLD,
    DEFAULT_NY_GOLD_NAME,
    DEFAULT_SILVER_ETF,
    DEFAULT_SILVER_ETF_NAME,
    DEFAULT_SILVER_NY,
    DEFAULT_SILVER_NY_NAME,
    GoldKline,
    MarketDataRepository,
)
from app.schemas.common import DirectionSignal
from app.schemas.market import (
    GoldTrendMetrics,
    GoldTrendOut,
    GoldTrendPoint,
    NewsIndexOut,
    TrendDirection,
    TrendIndexLevel,
    TrendIndexOut,
    TrendIndicatorOut,
)
from app.services import cache as served_cache
from app.services.freshness import build_data_freshness
from app.services.macro import MACRO_WEIGHT, NEWS_WEIGHT, TECH_WEIGHT, MacroFactorService
from app.utils.logger import get_logger

logger = get_logger(__name__)

# V0.64.0：K 线聚合粒度（趋势页 / 趋势接口共用）
KlineInterval = Literal["D", "W", "M"]

# 趋势维度权重（典型经验，合计 1.0）
TREND_WEIGHTS: dict[str, float] = {
    "结构": 0.30,  # 均线排列 + MA20 斜率
    "动量": 0.20,  # 近 20 日涨幅
    "支撑": 0.20,  # 价格相对 MA20/MA40 位置
    "动能": 0.15,  # RSI(14)
    "回撤": 0.15,  # 距区间高点回撤
}

# 各标的计价单位（用于摘要）
_TARGET_UNITS = {
    "etf": "元",
    "gram": "元/克",
    "ny": "美元/盎司",
    "silver_etf": "元",  # V0.71.0：白银 ETF 562800（易方达白银 ETF，元/份）
    "silver_ny": "美元/盎司",  # V0.71.0：纽约白银 COMEX SI（美元/盎司）
}

# 投资指引基准：默认以纽约金（COMEX GC）交易数据为准，
# 因其连续交易、夜盘覆盖国内休市时段，对国内金价具备领先指示意义。
GUIDE_TARGET = "ny"
# 可切换的指引标的（etf=黄金ETF 518880 / gram=上海金 Au99.99 / ny=纽约金 COMEX GC）
GUIDE_TARGETS = ("ny", "etf", "gram")

# 指引标的 → 时效/时段判定的市场 key（上海金在仓储层记为 sge）
_FRESHNESS_KEYS = {
    "ny": "ny",
    "gram": "sge",
    "etf": "etf",
    "silver_ny": "ny",  # V0.71.0：白银 SI 复用 ny 时段判定
    "silver_etf": "etf",  # V0.71.0：白银 ETF 复用 etf 时段判定
}


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


def aggregate_klines(
    daily: list[GoldKline],
    interval: KlineInterval,
) -> list[GoldKline]:
    """按 ISO 周（"W"）或 年月（"M"）聚合日 K（V0.64.0 多时间框架核心函数）。

    聚合规则（每桶）：
        - open  = 桶首日 open
        - close = 桶末日 close
        - high  = 桶内 max(high)
        - low   = 桶内 min(low)
        - volume= 桶内 sum(volume)
        - date  = 桶首日

    Args:
        daily: 按日期升序的日 K 序列（>= 0 项）。
        interval: "D" 原样返回；"W" 按 ISO 周界聚合；"M" 按 (year, month) 聚合。

    Returns:
        聚合后的新 K 线序列（保持升序）。

    Note:
        - W：ISO 周严格按 ``(year, ww)`` 分组，不受月份影响（跨月周界仍属同一桶）。
        - M：自然月，与日历一致。
        - 空输入返回 []；单点桶正常输出（OHLC = 自己）。
    """
    if interval == "D":
        return list(daily)
    if not daily:
        return []

    buckets: dict[tuple, list[GoldKline]] = {}
    order: list[tuple] = []  # 保持聚合顺序（按首次出现）

    for k in daily:
        if interval == "W":
            yy, ww, _ = k.date.isocalendar()
            key = (yy, ww)
        else:  # "M"
            key = (k.date.year, k.date.month)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(k)

    out: list[GoldKline] = []
    for key in order:
        group = buckets[key]
        out.append(
            GoldKline(
                date=group[0].date,
                open=group[0].open,
                close=group[-1].close,
                high=max(k.high for k in group),
                low=min(k.low for k in group),
                volume=sum(k.volume for k in group),
            ),
        )
    return out


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
    """趋势追踪：价格序列 + 均线 + 参数明细 + 追踪指数（技术×30% + 宏观×40% + 消息面×30%）。"""

    def __init__(
        self,
        repo: MarketDataRepository,
        macro: MacroFactorService | None = None,
        settings=None,
        news=None,
        central_bank=None,
    ) -> None:
        self._repo = repo
        self._macro = macro or MacroFactorService(settings=settings, central_bank=central_bank)
        # 延迟导入避免循环依赖
        from app.services.settings import WeightService

        self._settings: WeightService | None = settings
        # 消息面评估（客户打分）；未注入时消息面按中性 50 处理
        from app.services.news import NewsScoreService

        self._news: NewsScoreService | None = news

    @staticmethod
    def invalidate_for_news(target: str | None = None) -> int:
        """消息面评分更新后调用：失效 ``served_cache``，下次请求全量重算。

        Returns:
            失效的缓存条目数。
        """
        return served_cache.invalidate(target)

    async def analyze(
        self,
        days: int = 60,
        target: str = GUIDE_TARGET,
        interval: KlineInterval = "D",
    ) -> GoldTrendOut:
        """分析黄金近 N 个交易日趋势并合成追踪指数。

        默认基准为纽约金（``GUIDE_TARGET``），投资指引口径与之一致。

        **每日重算策略**：命中当日缓存时直接返回 GoldTrendOut；
        未命中则全量计算并写入缓存。消息面评分更新会失效缓存。

        **V0.64.0 多时间框架**：新增 ``interval`` 参数。
        - "D"：日 K（默认，原行为不变）
        - "W"：周 K（按 ISO 周界聚合，后台拉更长天数）
        - "M"：月 K（按年月聚合）
        W/M 模式下技术面 5 维度 indicators 旁路（指标对日 K 敏感），
        宏观与消息面仍正常合成综合指数。

        Args:
            days: 覆盖的交易日数量（W/M 模式下需 ≥ 730 才有 24 个月 K）。
            target: 标的类型，ny（纽约金COMEX，默认指引基准）/ etf（518880）/ gram（上海金克价）
            interval: K 线聚合粒度，D / W / M。

        Returns:
            趋势追踪结果（序列 + 指标 + 参数 + 指数）

        Raises:
            ValueError: 历史数据不足（<2 个交易日）
        """
        target = target if target in _TARGET_UNITS else GUIDE_TARGET
        interval = (interval or "D").upper()[:1]
        if interval not in ("D", "W", "M"):
            interval = "D"  # 防御性回退：非法值按日 K 处理

        # 命中当日缓存：直接返回，避免重复 K 线/宏观/合成
        # V0.60.0：按 settings.served_cache_ttl_seconds 派生日内 TTL；
        # V0.64.0：缓存 key 扩展为 (target, interval, date)，W/M 独立缓存。
        from app.config import get_settings

        ttl = get_settings().served_cache_ttl_seconds
        cached = served_cache.get_served(target, max_age_seconds=ttl, interval=interval)
        if cached is not None:
            logger.debug("Trend cache hit: target=%s interval=%s", target, interval)
            return cached

        result = await self._analyze_uncached(days=days, target=target, interval=interval)
        served_cache.set_served(target, result, interval=interval)
        return result

    async def _analyze_uncached(
        self,
        days: int,
        target: str,
        interval: KlineInterval = "D",
    ) -> GoldTrendOut:
        """实际计算：K 线 + 均线 + 技术指数 + 宏观 + 消息面 + 合成（不走缓存）。

        V0.64.0：W/M 模式下，K 线从日聚合到周/月；MA 在聚合后序列上重算；
        技术面 indicators（结构/动量/支撑/动能/回撤）对日 K 敏感，W/M 时旁路。
        """
        klines, symbol, name = await self._load_klines(days=days, target=target)
        if len(klines) < 2:
            raise ValueError("历史数据不足，无法进行趋势分析")

        # V0.64.0：按 interval 聚合（"D" 时返回 list 副本）
        if interval != "D":
            klines = aggregate_klines(klines, interval)
            if len(klines) < 2:
                raise ValueError(f"历史数据不足，无法按 interval={interval} 聚合")

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

        unit = _TARGET_UNITS.get(target, "元")
        start_price, end_price = closes[0], closes[-1]
        change_pct = (end_price - start_price) / start_price * 100 if start_price else 0.0
        change_1d, change_5d = self._recent_changes(closes)
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
            change_pct_1d=change_1d,
            change_pct_5d=change_5d,
            direction=direction,
            unit=unit,
            summary=self._summarize(direction, change_pct, end_price, unit, interval),
        )

        # 权重：用户配置优先（趋势维度 + 技术/宏观/消息面合成比），否则内置默认
        if self._settings is not None:
            tech_weights = await self._settings.trend_weights()
            tech_w, macro_w, news_w = await self._settings.combine_weights()
        else:
            tech_weights = TREND_WEIGHTS
            tech_w, macro_w, news_w = TECH_WEIGHT, MACRO_WEIGHT, NEWS_WEIGHT

        # V0.64.0：W/M 模式 indicators 旁路（指标对日 K 敏感）
        if interval == "D":
            indicators, tech_index = self._build_index(
                closes, highs, ma20, ma40, tech_weights, unit=unit
            )
        else:
            indicators = []
            tech_index = TrendIndexOut(
                score=50.0,
                level=TrendIndexLevel.SIDEWAYS,
                direction=DirectionSignal.NEUTRAL,
                summary=f"聚合后（interval={interval}）技术面 5 维度不适用，已按中性 50 处理",
                components={},
            )
        macro_index = await self._macro.evaluate()

        # 消息面：客户当日打分（未打分 → 中性 50）
        news_score = 50.0
        news_direction = DirectionSignal.NEUTRAL
        news_note, news_scored = "", False
        if self._news is not None:
            news_out = await self._news.get_today()
            news_score = news_out.score
            news_direction = news_out.direction
            news_note = news_out.notes
            news_scored = news_out.scored

        # 综合趋势指数 = 技术×tech_w + 宏观×macro_w + 消息面×news_w
        combined = round(
            tech_index.score * tech_w + macro_index.score * macro_w + news_score * news_w,
            1,
        )
        level, level_dir = self._to_level(combined)
        final_index = TrendIndexOut(
            score=combined,
            level=level,
            direction=level_dir,
            summary=(
                f"综合趋势评估指数 {combined:.1f}/100，等级【{self._level_label(level)}】；"
                f"= 技术面 {tech_index.score:.1f}×{tech_w:.0%} + 宏观参考 {macro_index.score:.1f}×{macro_w:.0%}"
                f" + 消息面 {news_score:.1f}×{news_w:.0%}"
            ),
            components={
                "tech": round(tech_index.score, 1),
                "macro": round(macro_index.score, 1),
                "news": round(news_score, 1),
            },
        )
        news_index = NewsIndexOut(
            score=news_score,
            direction=news_direction,
            note=news_note,
            scored=news_scored,
        )
        logger.info(
            "Trend analyzed: interval=%s %s bars, %s (%+.2f%%), index=%.1f (tech=%.1f×%.0f%%, macro=%.1f×%.0f%%, news=%.1f×%.0f%%)",
            interval,
            len(klines),
            direction.value,
            change_pct,
            combined,
            tech_index.score,
            tech_w * 100,
            macro_index.score,
            macro_w * 100,
            news_score,
            news_w * 100,
        )
        status = getattr(self._repo, "source_status", None)
        sources: dict[str, str] = status() if callable(status) else {}
        degraded = any(v == "mock" for v in sources.values())
        if degraded:
            logger.warning("Data source degraded to mock: %s", sources)

        # 数据时效（UX 6.1）：以最后一根 K 线日期为数据截止日，结合时段判定等级
        clock_key = _FRESHNESS_KEYS.get(target, "ny")
        freshness = build_data_freshness(
            clock_key,
            status=sources.get(clock_key, "-"),
            data_date=klines[-1].date,
            fetched_at=datetime.now(timezone.utc),
        )

        return GoldTrendOut(
            symbol=symbol,
            name=name,
            days=len(klines),
            points=points,
            metrics=metrics,
            indicators=indicators,
            index=final_index,
            macro=macro_index,
            news=news_index,
            data_sources=sources,
            degraded=degraded,
            freshness=freshness,
            interval=interval,
            served_at=datetime.now(),
        )

    @staticmethod
    def _level_label(level: TrendIndexLevel) -> str:
        """指数等级中文名。"""
        labels = {
            TrendIndexLevel.STRONG_UP: "强势上升",
            TrendIndexLevel.UP: "上升",
            TrendIndexLevel.SIDEWAYS: "震荡整理",
            TrendIndexLevel.DOWN: "下降",
            TrendIndexLevel.STRONG_DOWN: "弱势下降",
        }
        return labels[level]

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
        # V0.71.0：白银双市场（ETF 562800 / NY SI）通过 target 字段分派
        if target == "silver_ny":
            klines = await self._repo.get_silver_ny_history(days=days)
            return klines, DEFAULT_SILVER_NY, DEFAULT_SILVER_NY_NAME
        if target == "silver_etf":
            klines = await self._repo.get_silver_etf_history(days=days)
            return klines, DEFAULT_SILVER_ETF, DEFAULT_SILVER_ETF_NAME
        klines = await self._repo.get_gold_history(days=days)
        return klines, DEFAULT_GOLD_ETF, DEFAULT_GOLD_ETF_NAME

    # ---------------- 追踪指数 ----------------

    def _build_index(
        self,
        closes: list[float],
        highs: list[float],
        ma20: list[float | None],
        ma40: list[float | None],
        weights: dict[str, float] | None = None,
        unit: str = "元",
    ) -> tuple[list[TrendIndicatorOut], TrendIndexOut]:
        """计算 5 个趋势维度并加权合成追踪指数（技术面）。"""
        weights = weights or TREND_WEIGHTS
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
            mom20 = (now_close - closes[0]) / closes[0] * 100 if closes[0] else 0
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
            weight = weights.get(name, TREND_WEIGHTS[name])
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
            summary=self._index_summary(total, level, now_close, unit),
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
    def _index_summary(
        score: float, level: TrendIndexLevel, end_price: float, unit: str = "元"
    ) -> str:
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
            f"最新价 {end_price:.3f} {unit}。"
            f"{'趋势结构健康，多头动能占优' if score >= 55 else '趋势偏弱，注意风险控制' if score <= 45 else '多空胶着，等待方向选择'}"
        )

    # ---------------- 方向与摘要（沿用） ----------------

    @staticmethod
    def _recent_changes(closes: list[float]) -> tuple[float, float]:
        """近期涨跌幅：(昨日 1 日涨跌 %, 近 5 个交易日涨跌 %)。"""
        if len(closes) < 2:
            return 0.0, 0.0

        last, prev = closes[-1], closes[-2]
        change_1d = (last - prev) / prev * 100 if prev else 0.0

        # 近 5 个交易日：与 5 根 K 线之前的收盘比较（含当根共 6 个点）
        base_5d = closes[-6] if len(closes) >= 6 else closes[0]
        change_5d = (last - base_5d) / base_5d * 100 if base_5d else 0.0

        return round(change_1d, 2), round(change_5d, 2)

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
    def _summarize(
        direction: TrendDirection,
        change_pct: float,
        end_price: float,
        unit: str,
        interval: KlineInterval = "D",
    ) -> str:
        """生成面向客户的中文趋势摘要。

        V0.64.0：``interval`` 用于调整时间窗描述（D=近 2 个月 / W=近 1 年 / M=近 2 年）。
        """
        emoji = {"up": "↗", "down": "↘", "sideways": "→"}[direction.value]
        labels = {
            TrendDirection.UP: "上升趋势",
            TrendDirection.DOWN: "下降趋势",
            TrendDirection.SIDEWAYS: "震荡整理",
        }
        window_label = {"D": "近 2 个月", "W": "近 1 年", "M": "近 2 年"}.get(interval, "近 2 个月")
        ma_label = {"D": "20 日", "W": "20 周", "M": "20 月"}.get(interval, "20 日")
        return (
            f"{window_label}{labels[direction]} {emoji}，区间涨跌 {change_pct:+.2f}%，"
            f"最新价 {end_price:.3f} {unit}，价格{'位于' if change_pct >= 0 else '低于'}{ma_label}均线"
        )
