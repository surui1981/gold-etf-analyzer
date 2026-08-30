"""行情数据源：AKShare 真实数据采集 + Mock 降级。

设计：
- ``GoldHistoryProvider`` 定义数据源接口（Protocol）
- ``AkshareGoldDataProvider`` 为 AKShare 实现（东方财富 ETF 历史行情）
- ``MarketDataRepository`` 面向服务层，采集失败时自动回退 Mock，保证应用可用
"""

import asyncio
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

from app.utils.logger import get_logger

logger = get_logger(__name__)

# akshare 部分接口（新浪/英为财情）内部使用 py_mini_racer（内嵌 V8）解析加密数据，
# V8 平台在同一进程内并发初始化会崩溃（partition_address_space fatal）。
# 因此用全局锁将 akshare 网络调用串行化，任何时刻只有一个采集任务在跑。
_AK_LOCK = threading.Lock()

# 行情结果缓存（TTL）：同一标的/天数在有效期内复用，避免重复网络请求拖慢首屏
QUOTE_CACHE_TTL = 300  # 5 分钟
_CACHE: dict[tuple, tuple[float, list]] = {}
_CACHE_LOCK = threading.Lock()


def _cache_get(key: tuple) -> list | None:
    """读取缓存（未过期返回值，否则 None）。"""
    with _CACHE_LOCK:
        item = _CACHE.get(key)
    if item is not None and time.time() - item[0] < QUOTE_CACHE_TTL:
        return item[1]
    return None


def _cache_set(key: tuple, value: list) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (time.time(), value)

# 默认黄金 ETF：华安黄金ETF（规模最大、流动性最好）
DEFAULT_GOLD_ETF = "518880"
DEFAULT_GOLD_ETF_NAME = "黄金ETF华安"

# 默认黄金克价标的：上海黄金交易所 Au99.99（元/克）
DEFAULT_GOLD_GRAM = "Au99.99"
DEFAULT_GOLD_GRAM_NAME = "上海金Au99.99"

# 默认纽约金标的：COMEX 黄金期货主力 GC（美元/盎司）
DEFAULT_NY_GOLD = "GC"
DEFAULT_NY_GOLD_NAME = "纽约金COMEX"


def _parse_date(value: object) -> date:
    """将 AKShare 返回的日期字段（Timestamp/date/str）统一为 date。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


@dataclass(frozen=True)
class GoldQuote:
    """黄金报价（数据源无关）。"""

    symbol: str
    price_usd: float
    change_pct: float
    updated_at: datetime


@dataclass(frozen=True)
class GoldKline:
    """单日 K 线（数据源无关）。"""

    date: date
    open: float
    close: float
    high: float
    low: float
    volume: float


class GoldHistoryProvider(Protocol):
    """历史 K 线数据源接口。"""

    async def get_history(self, symbol: str, days: int) -> list[GoldKline]:
        """获取最近 days 个交易日的日 K。"""


class AkshareGoldDataProvider:
    """基于 AKShare 的真实行情数据源。

    主源：新浪基金 ETF 历史（fund_etf_hist_sina，多数网络环境可达）；
    备源：东方财富 ETF 历史（fund_etf_hist_em，主源失败时切换）。
    """

    async def get_history(self, symbol: str = DEFAULT_GOLD_ETF, days: int = 60) -> list[GoldKline]:
        """获取黄金 ETF 最近日 K。

        Args:
            symbol: ETF 代码（如 518880，自动推断市场前缀）
            days: 需要返回的交易日数量

        Returns:
            按日期升序的 K 线列表

        Raises:
            RuntimeError: AKShare 未安装或全部数据源采集失败
        """
        try:
            import akshare as ak  # 延迟导入：避免无网络环境/测试环境强依赖
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("akshare 未安装，请先 pip install akshare") from exc

        prefix = "sh" if symbol.startswith(("5", "6")) else "sz"

        def _fetch() -> list[GoldKline]:
            with _AK_LOCK:
                return _fetch_inner()

        def _fetch_inner() -> list[GoldKline]:
            errors: list[str] = []
            # 主源：新浪（沙箱/多数网络可达）
            try:
                df = ak.fund_etf_hist_sina(symbol=f"{prefix}{symbol}")
                if df is not None and not df.empty:
                    df = df.tail(days)
                    return [
                        GoldKline(
                            date=_parse_date(row["date"]),
                            open=float(row["open"]),
                            close=float(row["close"]),
                            high=float(row["high"]),
                            low=float(row["low"]),
                            volume=float(row.get("volume", 0) or 0),
                        )
                        for _, row in df.iterrows()
                    ]
                errors.append("sina empty")
            except Exception as exc:  # noqa: BLE001 —— 数据源逐个降级
                errors.append(f"sina: {exc}")

            # 备源：东方财富（需网络可达该域）
            try:
                end = datetime.now()
                start = end - timedelta(days=days * 2)  # 留足交易日余量
                df = ak.fund_etf_hist_em(
                    symbol=symbol,
                    period="daily",
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                    adjust="qfq",  # 前复权，追踪真实价格走势
                )
                if df is not None and not df.empty:
                    df = df.tail(days)
                    return [
                        GoldKline(
                            date=_parse_date(row["日期"]),
                            open=float(row["开盘"]),
                            close=float(row["收盘"]),
                            high=float(row["最高"]),
                            low=float(row["最低"]),
                            volume=float(row.get("成交量", 0) or 0),
                        )
                        for _, row in df.iterrows()
                    ]
                errors.append("em empty")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"em: {exc}")

            raise RuntimeError(f"AKShare 全部数据源失败: {'; '.join(errors)}")

        key = ("etf", symbol, days)
        cached = _cache_get(key)
        if cached is not None:
            return cached
        result = await asyncio.wait_for(asyncio.to_thread(_fetch), timeout=30)
        _cache_set(key, result)
        return result

    async def get_gram_history(
        self,
        symbol: str = DEFAULT_GOLD_GRAM,
        days: int = 60,
    ) -> list[GoldKline]:
        """获取黄金克价（上海黄金交易所 Au99.99，元/克）最近日 K。

        Args:
            symbol: SGE 品种代码，默认 Au99.99
            days: 需要返回的交易日数量

        Returns:
            按日期升序的 K 线列表

        Raises:
            RuntimeError: AKShare 未安装或采集失败
        """
        try:
            import akshare as ak  # 延迟导入
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("akshare 未安装，请先 pip install akshare") from exc

        def _fetch() -> list[GoldKline]:
            with _AK_LOCK:
                return _fetch_inner()

        def _fetch_inner() -> list[GoldKline]:
            df = ak.spot_hist_sge(symbol=symbol)
            if df is None or df.empty:
                raise RuntimeError(f"AKShare 未返回 {symbol} 行情数据")
            df = df.tail(days)
            return [
                GoldKline(
                    date=_parse_date(row["date"]),
                    open=float(row["open"]),
                    close=float(row["close"]),
                    high=float(row.get("high", row["close"])),
                    low=float(row.get("low", row["close"])),
                    volume=float(row.get("volume", 0) or 0),
                )
                for _, row in df.iterrows()
            ]

        key = ("sge", symbol, days)
        cached = _cache_get(key)
        if cached is not None:
            return cached
        result = await asyncio.wait_for(asyncio.to_thread(_fetch), timeout=30)
        _cache_set(key, result)
        return result

    async def get_us_gold_history(
        self,
        symbol: str = DEFAULT_NY_GOLD,
        days: int = 60,
    ) -> list[GoldKline]:
        """获取纽约金（COMEX 黄金期货主力 GC，美元/盎司）最近日 K。

        Args:
            symbol: 外盘期货代码，默认 GC（COMEX 黄金）
            days: 需要返回的交易日数量

        Returns:
            按日期升序的 K 线列表

        Raises:
            RuntimeError: AKShare 未安装或采集失败
        """
        try:
            import akshare as ak  # 延迟导入
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("akshare 未安装，请先 pip install akshare") from exc

        def _fetch() -> list[GoldKline]:
            with _AK_LOCK:
                return _fetch_inner()

        def _fetch_inner() -> list[GoldKline]:
            df = ak.futures_foreign_hist(symbol=symbol)  # 英为财情外盘期货
            if df is None or df.empty:
                raise RuntimeError(f"AKShare 未返回 {symbol} 行情数据")
            df = df.tail(days)
            return [
                GoldKline(
                    date=_parse_date(row["date"]),
                    open=float(row["open"]),
                    close=float(row["close"]),
                    high=float(row.get("high", row["close"])),
                    low=float(row.get("low", row["close"])),
                    volume=float(row.get("volume", 0) or 0),
                )
                for _, row in df.iterrows()
            ]

        key = ("ny", symbol, days)
        cached = _cache_get(key)
        if cached is not None:
            return cached
        result = await asyncio.wait_for(asyncio.to_thread(_fetch), timeout=30)
        _cache_set(key, result)
        return result


class MarketDataRepository:
    """行情数据源入口：真实源优先，异常自动回退 Mock（降级可感知）。"""

    def __init__(self, provider: GoldHistoryProvider | None = None) -> None:
        self._provider = provider or AkshareGoldDataProvider()
        # 数据源状态：key → "live"（真实）/ "mock"（降级演示）
        self._sources: dict[str, str] = {}

    def _mark(self, key: str, ok: bool) -> None:
        """记录数据源取数结果。"""
        self._sources[key] = "live" if ok else "mock"

    def source_status(self) -> dict[str, str]:
        """各数据源状态明细（供接口返回与页面展示）。"""
        return dict(self._sources)

    def is_degraded(self) -> bool:
        """是否存在任一数据源降级为 Mock。"""
        return any(v == "mock" for v in self._sources.values())

    async def get_gold_quote(self, symbol: str = "XAU") -> GoldQuote:
        """获取黄金最新报价（由最近 K 线推导，比固定 Mock 更真实）。"""
        try:
            klines = await self._provider.get_history(DEFAULT_GOLD_ETF, days=3)
            if not klines:
                raise RuntimeError("empty history")
            last, prev = klines[-1], klines[-2]
            change_pct = (last.close - prev.close) / prev.close * 100 if prev.close else 0.0
            return GoldQuote(
                symbol=symbol,
                price_usd=round(last.close, 3),
                change_pct=round(change_pct, 2),
                updated_at=datetime.combine(last.date, datetime.min.time(), tzinfo=timezone.utc),
            )
        except Exception as exc:  # noqa: BLE001 —— 数据源故障时降级 Mock
            logger.warning("quote from AKShare failed (%s), fallback to mock", exc)
            return GoldQuote(
                symbol=symbol,
                price_usd=2350.5,
                change_pct=0.42,
                updated_at=datetime.now(timezone.utc),
            )

    async def get_gold_history(self, days: int = 60) -> list[GoldKline]:
        """获取黄金 ETF 历史日 K；失败时返回确定性 Mock 序列（可离线演示）。"""
        try:
            klines = await self._provider.get_history(DEFAULT_GOLD_ETF, days=days)
            if klines:
                self._mark("etf", True)
                return klines
            raise RuntimeError("empty history")
        except Exception as exc:  # noqa: BLE001
            logger.warning("history from AKShare failed (%s), fallback to mock", exc)
            self._mark("etf", False)
            return self._mock_history(days)

    async def get_gold_gram_quote(self, symbol: str = DEFAULT_GOLD_GRAM) -> GoldQuote:
        """获取黄金克价最新报价（元/克）。"""
        try:
            klines = await self.get_gold_gram_history(symbol=symbol, days=3)
            if len(klines) < 2:
                raise RuntimeError("empty gram history")
            last, prev = klines[-1], klines[-2]
            change_pct = (last.close - prev.close) / prev.close * 100 if prev.close else 0.0
            return GoldQuote(
                symbol=symbol,
                price_usd=round(last.close, 2),
                change_pct=round(change_pct, 2),
                updated_at=datetime.combine(last.date, datetime.min.time(), tzinfo=timezone.utc),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("gram quote failed (%s), fallback to mock", exc)
            return GoldQuote(
                symbol=symbol,
                price_usd=990.5,
                change_pct=0.35,
                updated_at=datetime.now(timezone.utc),
            )

    async def get_gold_gram_history(
        self,
        symbol: str = DEFAULT_GOLD_GRAM,
        days: int = 60,
    ) -> list[GoldKline]:
        """获取黄金克价历史日 K；失败降级 Mock。"""
        try:
            klines = await self._provider.get_gram_history(symbol=symbol, days=days)
            if klines:
                self._mark("sge", True)
                return klines
            raise RuntimeError("empty gram history")
        except Exception as exc:  # noqa: BLE001
            logger.warning("gram history failed (%s), fallback to mock", exc)
            self._mark("sge", False)
            return self._mock_gram_history(days)

    @staticmethod
    def _mock_gram_history(days: int) -> list[GoldKline]:
        """确定性 Mock 克价序列：与 ETF Mock 同走势（克价 ≈990 元）。"""
        base = 985.0  # 上海金约 990 元/克区间
        today = date.today()
        points: list[GoldKline] = []
        for i in range(days, 0, -1):
            day = today - timedelta(days=i)
            if day.weekday() >= 5:
                continue
            progress = (days - i) / days
            wave = 0.06 * (1 - abs(progress - 0.7) / 0.7)
            close = round(base * (1 + 0.085 * progress - 0.025 * (progress**2)) * (1 + wave), 2)
            points.append(
                GoldKline(
                    date=day,
                    open=round(close * 0.995, 2),
                    close=close,
                    high=round(close * 1.01, 2),
                    low=round(close * 0.99, 2),
                    volume=0.0,
                )
            )
        return points

    async def get_us_gold_quote(self, symbol: str = DEFAULT_NY_GOLD) -> GoldQuote:
        """获取纽约金最新报价（美元/盎司）。"""
        try:
            klines = await self.get_us_gold_history(symbol=symbol, days=3)
            if len(klines) < 2:
                raise RuntimeError("empty us gold history")
            last, prev = klines[-1], klines[-2]
            change_pct = (last.close - prev.close) / prev.close * 100 if prev.close else 0.0
            return GoldQuote(
                symbol=symbol,
                price_usd=round(last.close, 2),
                change_pct=round(change_pct, 2),
                updated_at=datetime.combine(last.date, datetime.min.time(), tzinfo=timezone.utc),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("us gold quote failed (%s), fallback to mock", exc)
            return GoldQuote(
                symbol=symbol,
                price_usd=4500.5,
                change_pct=0.3,
                updated_at=datetime.now(timezone.utc),
            )

    async def get_us_gold_history(
        self,
        symbol: str = DEFAULT_NY_GOLD,
        days: int = 60,
    ) -> list[GoldKline]:
        """获取纽约金历史日 K；失败降级 Mock。"""
        try:
            klines = await self._provider.get_us_gold_history(symbol=symbol, days=days)
            if klines:
                self._mark("ny", True)
                return klines
            raise RuntimeError("empty us gold history")
        except Exception as exc:  # noqa: BLE001
            logger.warning("us gold history failed (%s), fallback to mock", exc)
            self._mark("ny", False)
            return self._mock_us_history(days)

    @staticmethod
    def _mock_us_history(days: int) -> list[GoldKline]:
        """确定性 Mock 纽约金序列（约 4500 美元/盎司区间）。"""
        base = 4430.0
        today = date.today()
        points: list[GoldKline] = []
        for i in range(days, 0, -1):
            day = today - timedelta(days=i)
            if day.weekday() >= 5:
                continue
            progress = (days - i) / days
            wave = 0.06 * (1 - abs(progress - 0.7) / 0.7)
            close = round(base * (1 + 0.05 * progress - 0.02 * (progress**2)) * (1 + wave), 2)
            points.append(
                GoldKline(
                    date=day,
                    open=round(close * 0.995, 2),
                    close=close,
                    high=round(close * 1.01, 2),
                    low=round(close * 0.99, 2),
                    volume=0.0,
                )
            )
        return points

    @staticmethod
    def _mock_history(days: int) -> list[GoldKline]:
        """确定性 Mock 序列：近 2 个月黄金上行后回调，便于离线演示。"""
        base = 5.42  # 黄金 ETF 约 5.4 元区间
        today = date.today()
        points: list[GoldKline] = []
        for i in range(days, 0, -1):
            day = today - timedelta(days=i)
            if day.weekday() >= 5:  # 跳过周末
                continue
            progress = (days - i) / days
            wave = 0.06 * (1 - abs(progress - 0.7) / 0.7)  # 前段上行、后段回落
            close = round(base * (1 + 0.09 * progress - 0.03 * (progress**2)) * (1 + wave), 3)
            points.append(
                GoldKline(
                    date=day,
                    open=round(close * 0.995, 3),
                    close=close,
                    high=round(close * 1.01, 3),
                    low=round(close * 0.99, 3),
                    volume=100000.0,
                )
            )
        return points
