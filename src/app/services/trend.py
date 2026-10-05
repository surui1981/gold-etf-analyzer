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
from typing import Literal, NamedTuple

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
from app.schemas.thresholds import DirectionThreshold, LevelThreshold
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

# 各维度「最少需要多少根 K 线」—— 低于该值该维度**不可用**，返回 None 而非中性 50
# （V0.78.0 Step D）。门槛由该维度公式自身的输入需求决定：
#   结构 40：均线排列需 MA5/MA20/MA40（40 根），MA20 斜率需 6 个 MA20（25 根）→ 取 40；
#   动量 21：近 20 个交易日涨跌幅必须用完整 20 日窗口 —— 旧版在不足 21 根时静默退化为
#            「与首根比较」却仍标注「近20日」，且与 50 ± 8×涨幅% 的打分标定不匹配；
#   支撑 20：收盘价对 MA20 乖离（MA40 乖离属可选加强项，不单独设门槛）；
#   动能 15：RSI(14) 需 period+1 个收盘价（该门槛由 ``_rsi`` 自身返回 None 实现）；
#   回撤 10：区间高点回撤至少需 10 个交易日才有统计意义。
# 键集合必须与 TREND_WEIGHTS 完全一致（test_trend.py 有断言兜底）。
DIM_MIN_BARS: dict[str, int] = {
    "结构": 40,
    "动量": 21,
    "支撑": 20,
    "动能": 15,
    "回撤": 10,
}

# 综合指数三面中文名（摘要文案用；与 ``components`` 的英文 key 对应）
_FACE_LABELS: dict[str, str] = {
    "tech": "技术面",
    "macro": "宏观参考",
    "news": "消息面",
}

# 各标的计价单位（用于摘要）
_TARGET_UNITS = {
    "etf": "元",
    "gram": "元/克",
    "ny": "美元/盎司",
    "silver_etf": "元",  # V0.71.0：白银 ETF 562800（易方达白银 ETF，元/份）
    "silver_ny": "美元/盎司",  # V0.71.0：纽约白银 COMEX SI（美元/盎司）
    "silver_gram": "元/克",  # V0.73.0 N+16：白银克价（ETF × 1000 推导）
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
    "silver_gram": "etf",  # V0.73.0 N+16：白银克价复用 ETF 时段判定（同源同步）
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


def _rsi(closes: list[float], period: int = 14) -> float | None:
    """计算 RSI(period)；收盘价不足 ``period + 2`` 个时返回 ``None``。

    V0.78.0 Step D：原实现在数据不足时返回 50（中性），页面于是显示
    「RSI(14) = 50.0」，与「RSI 真的是 50（多空平衡）」无法区分。现返回
    ``None``，由动能维度标记为「数据不足、未计入」。

    ⚠ 为何门槛是 ``period + 2`` 而不是直觉上的 ``period + 1``：下方循环里 i 最小取到
    ``-(period + 1)``，还要再读一次 ``closes[i - 1]`` ⇒ 最低索引 ``-(period + 2)``。
    原守卫写的是 ``len(closes) <= period``（即允许 period+1 = 15 根），**少算一根**：
    恰好 15 根时直接 IndexError 冒泡成 HTTP 500（V0.78.0 Step D 由新增测试实测发现）。

    ⚠ 已知偏差（本版**只记录不修改**）：``range(-period - 1, -1)`` 到 -2 为止、**不含 -1**，
    故**最新一根的涨跌不参与计算** —— RSI 实际是「截至前一根」的值（滞后一根），
    经实测比对确认（末根改成暴涨/暴跌，返回值不变）。正确写法应为 ``range(-period, 0)``，
    但那会改变所有 RSI 值并传导至动能分、综合指数、决策与历史快照，属口径变更，
    须先按 ``parameter-evaluation.md`` §6.2 做三维（Sharpe + 最大回撤 + 命中率）交叉验证。
    现状由 ``test_rsi_ignores_latest_bar_is_known_not_accidental`` 锁死。

    Args:
        closes: 收盘价序列（升序）
        period: RSI 周期

    Returns:
        RSI 值 0-100；数据不足时为 ``None``
    """
    if len(closes) < period + 2:
        return None
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


class _DimScore(NamedTuple):
    """单个趋势维度的计算结果（V0.78.0 Step D 引入）。

    ``score is None`` 表示该维度**数据不足、未参与加权合成**：此时 ``reason``
    必填，``value`` 为占位符「—」，``direction`` 固定中性（前端据此显示灰色
    「— 未计入」，而不是画一条 0 分或中间值的红/绿条）。
    """

    score: float | None
    value: str
    direction: DirectionSignal
    detail: str
    reason: str | None = None

    @staticmethod
    def insufficient(name: str, bars: int) -> "_DimScore":
        """构造「数据不足」的维度结果。"""
        need = DIM_MIN_BARS[name]
        return _DimScore(
            score=None,
            value="—",
            direction=DirectionSignal.NEUTRAL,
            detail=f"{name}：数据不足，本次未计入技术面指数",
            reason=f"数据不足：需要 ≥{need} 个交易日，当前仅 {bars} 个",
        )


def _fmt_score(score: float | None, digits: int = 1) -> str:
    """分数格式化（``None`` → 「—」），供日志与文案复用（V0.78.0 Step D）。

    直接对 ``None`` 用 ``%.1f`` 会让日志在格式化阶段抛 TypeError —— logging
    会把它吞成 "--- Logging error ---"，不易发现 —— 故统一走本函数。
    """
    return "—" if score is None else f"{score:.{digits}f}"


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
        # ``tech_note``：技术面「不可用 / 不适用」对**外**的披露（None = 技术面正常参与）。
        # ⚠ 不能只写在 ``tech_index.summary`` 上 —— ``tech_index`` 只被读取 ``.score``，
        # 其 summary 从不进入响应（V0.78.0 Step D 实测确认）⇒ 写在那里等于没有披露。
        tech_note: str | None = None
        if interval == "D":
            indicators, tech_index = self._build_index(
                closes, highs, ma20, ma40, tech_weights, unit=unit
            )
        else:
            # W/M 模式技术面旁路：5 维度的打分标定按「日 K 的 ±5% 量级」设计，聚合到
            # 周/月 K 后量纲不匹配。此处**保留**中性 50 而非 Step D 的 None，理由有二：
            # ① 「口径不适用」与「数据不足」不是同一类问题，后者才是本步的对象；
            # ② 整面剔除会让 52W/24M 的指数相对 60D 出现**结构性**（非市场）落差，
            #    破坏跨周期可比性。故数值仍按 50 计，但改为**在综合指数文案里显式披露**
            #    —— 把「沉默的 50」变成「说明过的 50」。
            indicators = []
            tech_note = f"技术面 5 维度对 {interval} K 不适用，已按中性 50 计入，非「数据不足」"
            tech_index = TrendIndexOut(
                score=50.0,
                level=TrendIndexLevel.SIDEWAYS,
                direction=DirectionSignal.NEUTRAL,
                summary=tech_note,
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
        # V0.78.0 Step D：任一面不可用（技术面 5 维度全部数据不足）时**剔除该面**，
        # 剩余面权重按 Σ有效权重 归一化，而不是让缺失面以中性 50 稀释结论。
        # 三面全有效时 Σ有效权重 恰为 1.0 → 与旧实现逐位相同。
        # 宏观与消息面结构上恒有值（宏观有静态参考兜底、消息面未打分为 50），故
        # combined 在可达路径上恒为数值；None 分支属防御性保留。
        faces: tuple[tuple[str, float | None, float], ...] = (
            ("tech", tech_index.score, tech_w),
            ("macro", macro_index.score, macro_w),
            ("news", news_score, news_w),
        )
        valid_faces: list[tuple[str, float, float]] = [
            (k, float(v), w) for k, v, w in faces if v is not None and w > 0.0
        ]
        face_w = sum(w for _, _, w in valid_faces)
        dropped = [k for k, v, _ in faces if v is None]
        combined: float | None = (
            round(sum(v * w / face_w for _, v, w in valid_faces), 1) if face_w > 0.0 else None
        )
        if combined is None:  # pragma: no cover - 防御分支：宏观/消息面恒有值
            logger.error("Combined index unavailable: no face carries a valid score")
            level, level_dir = TrendIndexLevel.SIDEWAYS, DirectionSignal.NEUTRAL
            index_summary = "综合趋势评估指数不可用：技术面、宏观参考、消息面均无有效分值"
            components: dict[str, float] = {}
        else:
            level, level_dir = self._to_level(combined)
            formula = " + ".join(
                f"{_FACE_LABELS[k]} {v:.1f}×{w / face_w:.0%}" for k, v, w in valid_faces
            )
            notes: list[str] = []
            missing_dims = [i.name for i in indicators if i.score is None]
            if dropped:
                notes.append(
                    f"{'、'.join(_FACE_LABELS[k] for k in dropped)} 不可用，"
                    "已剔除并按剩余面权重归一化"
                )
            elif missing_dims:
                notes.append(f"技术面 {'、'.join(missing_dims)} 数据不足，已按有效权重归一化")
            if tech_note:  # W/M 旁路：数值保留 50，但必须让客户看见这是一句说明
                notes.append(tech_note)
            note = f"（{'；'.join(notes)}）" if notes else ""
            index_summary = (
                f"综合趋势评估指数 {combined:.1f}/100，等级【{self._level_label(level)}】；"
                f"= {formula}{note}"
            )
            components = {k: round(v, 1) for k, v, _ in valid_faces}
        final_index = TrendIndexOut(
            score=combined,
            level=level,
            direction=level_dir,
            summary=index_summary,
            components=components,
        )
        news_index = NewsIndexOut(
            score=news_score,
            direction=news_direction,
            note=news_note,
            scored=news_scored,
        )
        logger.info(
            "Trend analyzed: interval=%s %s bars, %s (%+.2f%%), index=%s"
            " (tech=%s×%.0f%%, macro=%.1f×%.0f%%, news=%.1f×%.0f%%)",
            interval,
            len(klines),
            direction.value,
            change_pct,
            _fmt_score(combined),
            _fmt_score(tech_index.score),
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
        # V0.73.0 N+16：白银克价（silver_gram）走 ETF 同源推导
        if target == "silver_gram":
            klines = await self._repo.get_silver_gram_history(days=days)
            return klines, "Ag", "白银克价"
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
        """计算 5 个趋势维度并加权合成追踪指数（技术面）。

        V0.78.0 Step D「兜底差异化」：每个维度先按 ``DIM_MIN_BARS`` 判定输入是否
        足够；不足的维度 ``score=None``（页面显示「—」）且**不参与合成**，其余维度
        的权重按 ``Σ有效权重`` 归一化，保证 ``Σcontribution == 技术面指数``。
        5 个维度全部不足时技术面指数为 ``None``（而非中性 50），由综合指数剔除该面。

        为什么不用中性 50 兜底：50 是一个**判断**（多空平衡），会被当作真实算出来的
        分数计入加权，并进一步喂给共振信号与决策引擎；而「数据不足」本质是**置信度**
        问题。两者对客户的含义完全不同，混用会让「没数据」看起来像「有结论」。
        """
        weights = weights or TREND_WEIGHTS
        now_close = closes[-1]
        bars = len(closes)
        dims: dict[str, _DimScore] = {}

        # 1) 结构：均线排列 + MA20 斜率
        if bars < DIM_MIN_BARS["结构"]:
            dims["结构"] = _DimScore.insufficient("结构", bars)
        else:
            align_score, align_desc = self._alignment_score(closes, ma20, ma40)
            if align_score is None:  # 防御：MA 序列与收盘价长度不一致
                dims["结构"] = _DimScore.insufficient("结构", bars)
            else:
                slope_pct = self._ma_slope_pct(ma20)
                slope_score = _clamp(50 + slope_pct * 100)  # ±0.5%/日 量级
                struct_score = align_score * 0.6 + slope_score * 0.4
                dims["结构"] = _DimScore(
                    score=struct_score,
                    value=(
                        f"{align_desc}；MA20近5日"
                        f"{'上行' if slope_pct >= 0 else '下行'} {abs(slope_pct):.2f}%"
                    ),
                    direction=self._to_direction(struct_score),
                    detail="均线排列与MA20斜率",
                )

        # 2) 动量：近 20 日涨幅（窗口必须完整，见 DIM_MIN_BARS 注释）
        if bars < DIM_MIN_BARS["动量"]:
            dims["动量"] = _DimScore.insufficient("动量", bars)
        else:
            mom20 = (now_close - closes[-21]) / closes[-21] * 100
            mom_score = _clamp(50 + mom20 * 8)  # +5% → 90，-5% → 10
            dims["动量"] = _DimScore(
                score=mom_score,
                value=f"近20日 {mom20:+.2f}%",
                direction=self._to_direction(mom_score),
                detail="近20个交易日涨跌幅",
            )

        # 3) 支撑：价格相对 MA20 / MA40
        if bars < DIM_MIN_BARS["支撑"]:
            dims["支撑"] = _DimScore.insufficient("支撑", bars)
        else:
            support_score, support_desc = self._support_score(now_close, ma20, ma40)
            if support_score is None:
                dims["支撑"] = _DimScore.insufficient("支撑", bars)
            else:
                dims["支撑"] = _DimScore(
                    score=support_score,
                    value=support_desc,
                    direction=self._to_direction(support_score),
                    detail="收盘价相对 MA20/MA40 位置",
                )

        # 4) 动能：RSI(14) —— 门槛由 ``_rsi`` 自身实现（不足 period+1 根返回 None），
        #    避免同一条件在「常量表」与「函数」两处各写一遍而漂移
        rsi_val = _rsi(closes)
        if rsi_val is None:
            dims["动能"] = _DimScore.insufficient("动能", bars)
        else:
            rsi_score = _clamp(50 + (rsi_val - 50) * 1.5)  # RSI70→80，30→20
            dims["动能"] = _DimScore(
                score=rsi_score,
                value=f"RSI(14) = {rsi_val:.1f}",
                direction=self._to_direction(rsi_score),
                detail="相对强弱指标",
            )

        # 5) 回撤：距区间最高收盘的回撤（至少 10 个交易日才有统计意义）
        if bars < DIM_MIN_BARS["回撤"]:
            dims["回撤"] = _DimScore.insufficient("回撤", bars)
        else:
            peak = max(highs)
            drawdown = (peak - now_close) / peak * 100 if peak else 0.0
            dd_score = _clamp(100 - drawdown * 10)  # 回撤 0 → 100，10% → 0
            dims["回撤"] = _DimScore(
                score=dd_score,
                value=f"距区间高点回撤 {drawdown:.2f}%（高点 {peak:.3f}）",
                direction=self._to_direction(dd_score),
                detail="回撤控制稳健度",
            )

        # 加权合成：仅有效维度参与，权重按 Σ有效权重 归一化
        # （全维度有效时 Σ有效权重 恰为 1.0 → 与旧实现逐位相同，测试有回归断言）
        valid_w = sum(
            weights.get(name, TREND_WEIGHTS[name])
            for name, d in dims.items()
            if d.score is not None
        )
        indicators: list[TrendIndicatorOut] = []
        total: float | None = 0.0 if valid_w > 0 else None
        for name, d in dims.items():
            weight = weights.get(name, TREND_WEIGHTS[name])
            if d.score is None or total is None:
                contribution, score_out = None, None
            else:
                contribution = round(d.score * weight / valid_w, 2)
                total += contribution
                score_out = round(d.score, 1)
            indicators.append(
                TrendIndicatorOut(
                    name=name,
                    value=d.value,
                    score=score_out,
                    direction=d.direction,
                    weight=weight,
                    contribution=contribution,
                    detail=d.detail,
                    reason=d.reason,
                )
            )

        if total is None:
            # 5 个维度全部数据不足 → 技术面指数不可用（不伪装成中性 50）
            logger.warning("Tech index unavailable: all dims insufficient (bars=%d)", bars)
            return indicators, TrendIndexOut(
                score=None,
                level=TrendIndexLevel.SIDEWAYS,
                direction=DirectionSignal.NEUTRAL,
                summary=(
                    f"技术面 {len(dims)} 个维度均因数据不足未参与合成"
                    f"（当前仅 {bars} 个交易日，单项最少需 {max(DIM_MIN_BARS.values())} 个）"
                    "→ 技术面指数不可用，综合指数已剔除技术面并按剩余面权重归一化"
                ),
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
    ) -> tuple[float | None, str]:
        """均线排列评分：多头排列高分、空头排列低分；输入不足时返回 ``None``。

        V0.78.0 Step D：原实现在均线不足时返回 50，与「均线交叉整理」的 **真实**
        50 分完全同形，无法区分「算出来是中性的」与「根本没算」。现返回 ``None``，
        由调用方标记为未参与合成。
        """
        if len(closes) < 40 or ma20[-1] is None or ma40[-1] is None:
            return None, "均线数据不足"
        ma5 = moving_average(closes, 5)[-1]
        if ma5 is None:
            return None, "均线数据不足"

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
    ) -> tuple[float | None, str]:
        """价格相对均线位置评分；两条均线都不可用时返回 ``None``（V0.78.0 Step D）。"""
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
            return None, "均线数据不足"
        return round(sum(scores) / len(scores), 1), "；".join(desc_parts)

    @staticmethod
    def _to_direction(score: float) -> DirectionSignal:
        """分数 → 多空信号（供页面红绿着色）。

        V0.78.0：阈值改读 DirectionThreshold.NEUTRAL_HIGH/LOW（行为零变化——60/40 含端点）。
        """
        if score >= int(DirectionThreshold.NEUTRAL_HIGH):
            return DirectionSignal.BULLISH
        if score <= int(DirectionThreshold.NEUTRAL_LOW):
            return DirectionSignal.BEARISH
        return DirectionSignal.NEUTRAL

    @staticmethod
    def _to_level(score: float) -> tuple[TrendIndexLevel, DirectionSignal]:
        """指数分数 → 等级与方向。

        V0.78.0：阈值改读 LevelThreshold（行为零变化——75/55/45/25 含端点）。
        """
        if score >= int(LevelThreshold.STRONG_UP):
            return TrendIndexLevel.STRONG_UP, DirectionSignal.BULLISH
        if score >= int(LevelThreshold.UP):
            return TrendIndexLevel.UP, DirectionSignal.BULLISH
        if score >= int(LevelThreshold.SIDEWAYS):
            return TrendIndexLevel.SIDEWAYS, DirectionSignal.NEUTRAL
        if score >= int(LevelThreshold.DOWN):
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
            f"{'趋势结构健康，多头动能占优' if score >= int(LevelThreshold.UP) else '趋势偏弱，注意风险控制' if score <= int(LevelThreshold.SIDEWAYS) else '多空胶着，等待方向选择'}"
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
