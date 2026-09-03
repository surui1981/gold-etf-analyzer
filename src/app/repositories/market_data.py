"""行情数据源：AKShare 免费采集 + 零KEY公开源兜底 + Mock 降级。

设计：
- ``GoldHistoryProvider`` 定义数据源接口（Protocol）
- ``AkshareGoldDataProvider`` 为 AKShare 实现（东方财富/新浪 ETF 历史、英为财情外盘）
- ``MarketDataRepository`` 面向服务层；采集失败时逐级回退：
  1) 零KEY公开 API（gold-api.com 实时 XAU/USD 即期报价）
  2) AKShare 免费源（东方财富/新浪/上海金交所）
  3) 确定性 Mock（可离线演示，标注降级）

重要：本应用**不依赖任何付费 API KEY**，全部为公开免费源：
- gold-api.com：实时 XAU/USD 即期报价（零KEY、无需注册）
- AKShare：东方财富/新浪 ETF 历史、上海金交所 Au99.99、中债美债收益率（免费开源库）
- 美元指数/VIX 等宏观因子由 macro.py 内置静态参考值提供（可平滑替换为实时 provider）
"""

import asyncio
import json
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

from app.utils.logger import get_logger

logger = get_logger(__name__)

# akshare 部分接口（新浪/英为财情）内部使用 py_mini_racer（内嵌 V8）解析加密数据，
# V8 平台在同一进程内初始化可能崩溃（partition_address_space fatal）。
# 因此凡涉及 V8 的抓取统一放进**子进程**执行，崩溃只影响子进程，不拖垮主服务。
_AK_LOCK = threading.Lock()

# 行情结果缓存（TTL）：同一标的/天数在有效期内复用，避免重复网络请求拖慢首屏
QUOTE_CACHE_TTL = 300  # 5 分钟
_CACHE: dict[tuple, tuple[float, list]] = {}
_CACHE_LOCK = threading.Lock()

# 零KEY公开源：实时 XAU/USD 即期报价（无需任何 KEY，返回 {"price": <float>, ...}）
_XAU_API = "https://api.gold-api.com/price/XAU"


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


# --- 子进程隔离抓取模板（避免 V8 崩溃拖垮主服务）---
_SINA_TMPL = """import sys, json
try:
    import akshare as ak
    df = ak.fund_etf_hist_sina(symbol="{symbol}")
    out = [{{"date": str(r["date"])[:10], "open": float(r["open"]), "close": float(r["close"]),
             "high": float(r["high"]), "low": float(r["low"]), "volume": float(r.get("volume", 0) or 0)}}
            for _, r in df.tail({days}).iterrows()]
    print(json.dumps(out))
except Exception as e:
    print("ERR:" + str(e)[:200], file=sys.stderr)
    sys.exit(3)
"""

_US_TMPL = """import sys, json
try:
    import akshare as ak
    df = ak.futures_foreign_hist(symbol="{symbol}")
    out = [{{"date": str(r["date"])[:10], "open": float(r["open"]), "close": float(r["close"]),
             "high": float(r["high"]), "low": float(r["low"]), "volume": float(r.get("volume", 0) or 0)}}
            for _, r in df.tail({days}).iterrows()]
    print(json.dumps(out))
except Exception as e:
    print("ERR:" + str(e)[:200], file=sys.stderr)
    sys.exit(3)
"""


def _sina_etf_via_subprocess(symbol: str, days: int) -> list | None:
    """子进程隔离调用新浪 ETF 历史，避免 V8 崩溃影响主服务。失败返回 None。"""
    code = _SINA_TMPL.format(symbol=symbol, days=days)
    try:
        res = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=30,
        )
        if res.returncode == 0 and res.stdout.strip():
            return [
                GoldKline(
                    date=_parse_date(r["date"]),
                    open=float(r["open"]),
                    close=float(r["close"]),
                    high=float(r["high"]),
                    low=float(r["low"]),
                    volume=float(r.get("volume", 0) or 0),
                )
                for r in json.loads(res.stdout)
            ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("sina subprocess 异常: %s", exc)
    return None


def _us_gold_via_subprocess(symbol: str, days: int) -> list | None:
    """子进程隔离调用英为财情外盘期货，避免 V8 崩溃。失败返回 None。"""
    code = _US_TMPL.format(symbol=symbol, days=days)
    try:
        res = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=30,
        )
        if res.returncode == 0 and res.stdout.strip():
            return [
                GoldKline(
                    date=_parse_date(r["date"]),
                    open=float(r["open"]),
                    close=float(r["close"]),
                    high=float(r["high"]),
                    low=float(r["low"]),
                    volume=float(r.get("volume", 0) or 0),
                )
                for r in json.loads(res.stdout)
            ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("us gold subprocess 异常: %s", exc)
    return None


def _http_json(url: str, timeout: int = 15):
    """通用 JSON GET（零依赖 urllib）。"""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


async def _fetch_xau_usd_live() -> float | None:
    """零KEY公开源获取实时 XAU/USD 即期报价；失败返回 None。"""
    try:
        raw = await asyncio.to_thread(_http_json, _XAU_API, 15)
        if isinstance(raw, dict) and raw.get("price"):
            return float(raw["price"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("gold-api.com 取数失败: %s", exc)
    return None


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
    """基于 AKShare 的真实行情数据源（全部免费、无 KEY）。

    主源：东方财富 ETF 历史（fund_etf_hist_em，不依赖 V8，跨网络更稳）；
    备源：新浪 ETF 历史（子进程隔离，避免 V8 崩溃）；
    外盘：英为财情期货（同样子进程隔离）。
    """

    async def get_history(self, symbol: str = DEFAULT_GOLD_ETF, days: int = 60) -> list[GoldKline]:
        """获取黄金 ETF 最近日 K。"""
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
            end = datetime.now()
            start = end - timedelta(days=days * 2)  # 留足交易日余量

            # 主源：东方财富（不依赖 V8）
            try:
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

            # 备源：新浪（子进程隔离，避免 V8 崩溃影响主服务）
            try:
                sub = _sina_etf_via_subprocess(f"{prefix}{symbol}", days)
                if sub:
                    return sub
                errors.append("sina subprocess empty")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"sina: {exc}")

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
        """获取黄金克价（上海黄金交易所 Au99.99，元/克）最近日 K。"""
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
        """获取纽约金（COMEX 黄金期货主力 GC，美元/盎司）最近日 K。"""
        try:
            import akshare as ak  # 延迟导入
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("akshare 未安装，请先 pip install akshare") from exc

        def _fetch() -> list[GoldKline]:
            with _AK_LOCK:
                return _fetch_inner()

        def _fetch_inner() -> list[GoldKline]:
            # 英为财情外盘期货依赖 V8，子进程隔离防止崩溃
            sub = _us_gold_via_subprocess(symbol, days)
            if sub:
                return sub
            raise RuntimeError("us gold subprocess empty")

        key = ("ny", symbol, days)
        cached = _cache_get(key)
        if cached is not None:
            return cached
        result = await asyncio.wait_for(asyncio.to_thread(_fetch), timeout=30)
        _cache_set(key, result)
        return result


class MarketDataRepository:
    """行情数据源入口：实时公开源优先，异常自动回退 Mock（降级可感知）。"""

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
        """获取黄金最新报价（零KEY公开源优先，真实可达）。"""
        # 主源：gold-api.com 实时 XAU/USD（零KEY公开）
        price = await _fetch_xau_usd_live()
        if price:
            try:
                change = await self._sge_daily_change()
            except Exception:  # noqa: BLE001
                change = 0.0
            return GoldQuote(
                symbol=symbol,
                price_usd=round(price, 2),
                change_pct=change,
                updated_at=datetime.now(timezone.utc),
            )
        # 兜底：由 ETF 历史推导
        try:
            klines = await self._provider.get_history(DEFAULT_GOLD_ETF, days=3)
            if klines and len(klines) >= 2:
                last, prev = klines[-1], klines[-2]
                change_pct = (last.close - prev.close) / prev.close * 100 if prev.close else 0.0
                return GoldQuote(
                    symbol=symbol,
                    price_usd=round(last.close, 3),
                    change_pct=round(change_pct, 2),
                    updated_at=datetime.combine(last.date, datetime.min.time(), tzinfo=timezone.utc),
                )
        except Exception as exc:  # noqa: BLE001
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

    async def _sge_daily_change(self) -> float:
        """由上海金真实近两日推导涨跌幅（免费公开源）。"""
        try:
            kl = await self.get_gold_gram_history(symbol=DEFAULT_GOLD_GRAM, days=3)
            if len(kl) >= 2 and kl[-2].close:
                return round((kl[-1].close - kl[-2].close) / kl[-2].close * 100, 2)
        except Exception:  # noqa: BLE001
            pass
        return 0.0

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
        # 主源：零KEY公开 XAU/USD 即期报价（与COMEX高度联动）
        price = await _fetch_xau_usd_live()
        if price:
            try:
                change = await self._sge_daily_change()
            except Exception:  # noqa: BLE001
                change = 0.0
            return GoldQuote(
                symbol=symbol,
                price_usd=round(price, 2),
                change_pct=change,
                updated_at=datetime.now(timezone.utc),
            )
        # 兜底：由外盘历史推导
        try:
            klines = await self.get_us_gold_history(symbol=symbol, days=3)
            if klines and len(klines) >= 2:
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
            if day.weekday() >= 5:  # 跳过周末
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
