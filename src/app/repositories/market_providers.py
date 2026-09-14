"""行情数据源 Provider 抽象 + 4 个内置实现 + 工厂（V0.59.0, P1 #5 行情源配置化）。

设计：
- 三个窄接口 ``GoldHistoryProvider`` / ``GoldLiveQuoteProvider`` / ``TreasuryYieldProvider``
  分别对应历史 K 线 / 实时报价 / 美债收益率三类数据；
- ``MarketProviderBundle`` 把三件套打包注入 ``MarketDataRepository``，便于测试与扩展；
- 工厂 ``build_provider_bundle(settings)`` 按 ``MARKET_PROVIDER`` 名称解析；
  内置 4 个 provider：akshare（默认）/ mock / eastmoney_only / sina_only；
- 旧 ``MarketDataRepository(provider=...)`` 签名通过把 ``provider`` 自动包装为
  ``MarketProviderBundle`` 实现向后兼容。

使用示例：

    from app.config import get_settings
    from app.repositories.market_providers import build_provider_bundle
    bundle = build_provider_bundle(get_settings())
    repo = MarketDataRepository(bundle=bundle)
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
import threading
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

from app.config import Settings, get_settings
from app.repositories.market_data import (
    DEFAULT_GOLD_ETF,
    DEFAULT_GOLD_GRAM,
    DEFAULT_NY_GOLD,
    GoldKline,
    GoldQuote,
    USTYield,
    _parse_date,
    _parse_h15_csv,
)

logger = logging.getLogger(__name__)


# ───────────────────── Provider 接口 ─────────────────────


class GoldHistoryProvider(Protocol):
    """黄金历史 K 线数据源接口。"""

    async def get_history(
        self, symbol: str = DEFAULT_GOLD_ETF, days: int = 60,
    ) -> list[GoldKline]: ...

    async def get_gram_history(
        self, symbol: str = DEFAULT_GOLD_GRAM, days: int = 60,
    ) -> list[GoldKline]: ...

    async def get_us_gold_history(
        self, symbol: str = DEFAULT_NY_GOLD, days: int = 60,
    ) -> list[GoldKline]: ...


class GoldLiveQuoteProvider(Protocol):
    """实时 XAU/USD 即期报价数据源接口。"""

    async def get_live_quote(self) -> GoldQuote | None: ...


class TreasuryYieldProvider(Protocol):
    """美债 10Y/30Y 收益率数据源接口。"""

    async def get_treasury_yields(self) -> USTYield | None: ...


@dataclass(frozen=True)
class MarketProviderBundle:
    """Provider 三件套打包，便于按名一次性注入。"""

    history: GoldHistoryProvider
    live: GoldLiveQuoteProvider
    treasury: TreasuryYieldProvider


# ───────────────────── AKShare 子进程隔离模板 ─────────────────────

# akshare 部分接口（新浪/英为财情）内部使用 py_mini_racer（内嵌 V8）解析加密数据，
# V8 平台在同一进程内初始化可能崩溃（partition_address_space fatal）。
# 因此凡涉及 V8 的抓取统一放进**子进程**执行，崩溃只影响子进程，不拖垮主服务。
_AK_LOCK = threading.Lock()

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
    except Exception as exc:
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
    except Exception as exc:
        logger.warning("us gold subprocess 异常: %s", exc)
    return None


# ───────────────────── HTTP 工具 ─────────────────────


def _http_json(url: str, timeout: int = 15, headers: dict | None = None):
    """通用 JSON GET（零依赖 urllib）。"""
    req_headers = {"User-Agent": "Mozilla/5.0"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def _http_text(url: str, timeout: int = 15, headers: dict | None = None) -> str:
    """通用 TEXT GET（零依赖 urllib）。"""
    req_headers = {"User-Agent": "Mozilla/5.0"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


# ───────────────────── Provider 实现 ─────────────────────


class AkshareGoldHistoryProvider:
    """基于 AKShare 的真实行情数据源（全部免费、无 KEY）。

    主源：东方财富 ETF 历史（fund_etf_hist_em，不依赖 V8，跨网络更稳）；
    备源：新浪 ETF 历史（子进程隔离，避免 V8 崩溃）；
    外盘：英为财情期货（同样子进程隔离）。
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def get_history(
        self, symbol: str = DEFAULT_GOLD_ETF, days: int = 60,
    ) -> list[GoldKline]:
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
            start = end - timedelta(days=days * 2)

            # 主源：东方财富（不依赖 V8）
            try:
                df = ak.fund_etf_hist_em(
                    symbol=symbol,
                    period="daily",
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                    adjust="qfq",
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
            except Exception as exc:
                errors.append(f"em: {exc}")

            # 备源：新浪（子进程隔离）
            try:
                sub = _sina_etf_via_subprocess(f"{prefix}{symbol}", days)
                if sub:
                    return sub
                errors.append("sina subprocess empty")
            except Exception as exc:
                errors.append(f"sina: {exc}")

            raise RuntimeError(f"AKShare 全部数据源失败: {'; '.join(errors)}")

        return await asyncio.wait_for(asyncio.to_thread(_fetch), timeout=30)

    async def get_gram_history(
        self, symbol: str = DEFAULT_GOLD_GRAM, days: int = 60,
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

        return await asyncio.wait_for(asyncio.to_thread(_fetch), timeout=30)

    async def get_us_gold_history(
        self, symbol: str = DEFAULT_NY_GOLD, days: int = 60,
    ) -> list[GoldKline]:
        """获取纽约金（COMEX 黄金期货主力 GC，美元/盎司）最近日 K。"""
        # 延迟导入：仅用于探测 akshare 是否可用，纽约金实际走下方 subprocess 抓取
        try:
            import akshare as ak  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("akshare 未安装，请先 pip install akshare") from exc

        def _fetch() -> list[GoldKline]:
            with _AK_LOCK:
                return _fetch_inner()

        def _fetch_inner() -> list[GoldKline]:
            sub = _us_gold_via_subprocess(symbol, days)
            if sub:
                return sub
            raise RuntimeError("us gold subprocess empty")

        return await asyncio.wait_for(asyncio.to_thread(_fetch), timeout=30)


class EastmoneyOnlyHistoryProvider:
    """只走东方财富 ETF 历史（fund_etf_hist_em）。

    剔除 V8 备源（新浪/英为财情），适用于已知东财可用、网络受限的场景，
    省去 sina subprocess 启动开销；东财不可达时立即抛错。
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def get_history(
        self, symbol: str = DEFAULT_GOLD_ETF, days: int = 60,
    ) -> list[GoldKline]:
        try:
            import akshare as ak
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("akshare 未安装") from exc

        def _fetch() -> list[GoldKline]:
            end = datetime.now()
            start = end - timedelta(days=days * 2)
            df = ak.fund_etf_hist_em(
                symbol=symbol,
                period="daily",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust="qfq",
            )
            if df is None or df.empty:
                raise RuntimeError("eastmoney empty")
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

        return await asyncio.wait_for(asyncio.to_thread(_fetch), timeout=30)

    async def get_gram_history(
        self, symbol: str = DEFAULT_GOLD_GRAM, days: int = 60,
    ) -> list[GoldKline]:
        # 克价仍走 AKShare SGE（仅 ETF 历史受 V8 影响）
        return await AkshareGoldHistoryProvider(self._settings).get_gram_history(symbol, days)

    async def get_us_gold_history(
        self, symbol: str = DEFAULT_NY_GOLD, days: int = 60,
    ) -> list[GoldKline]:
        # 纽约金仍走英为财情（V8）
        return await AkshareGoldHistoryProvider(self._settings).get_us_gold_history(symbol, days)


class SinaOnlyHistoryProvider:
    """只走新浪 ETF 历史（fund_etf_hist_sina），子进程隔离。

    适用于东方财富 403 但新浪可用的场景；新浪不可达时立即抛错。
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def get_history(
        self, symbol: str = DEFAULT_GOLD_ETF, days: int = 60,
    ) -> list[GoldKline]:
        prefix = "sh" if symbol.startswith(("5", "6")) else "sz"
        sub = await asyncio.to_thread(_sina_etf_via_subprocess, f"{prefix}{symbol}", days)
        if not sub:
            raise RuntimeError("sina empty")
        return sub

    async def get_gram_history(
        self, symbol: str = DEFAULT_GOLD_GRAM, days: int = 60,
    ) -> list[GoldKline]:
        return await AkshareGoldHistoryProvider(self._settings).get_gram_history(symbol, days)

    async def get_us_gold_history(
        self, symbol: str = DEFAULT_NY_GOLD, days: int = 60,
    ) -> list[GoldKline]:
        return await AkshareGoldHistoryProvider(self._settings).get_us_gold_history(symbol, days)


class AkshareLiveQuoteProvider:
    """实时 XAU/USD 报价：gold-api.com 主源 + 新浪 hf_GC 备源（双源 fallback）。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def get_live_quote(self) -> GoldQuote | None:
        price = await self._fetch_goldapi()
        if price:
            return GoldQuote(
                symbol="XAU",
                price_usd=round(price, 2),
                updated_at=datetime.now(timezone.utc),
                change_pct=0.0,  # 涨幅由调用方补全
            )
        price = await self._fetch_sina_hf_gc()
        if price:
            return GoldQuote(
                symbol="XAU",
                price_usd=round(price, 2),
                updated_at=datetime.now(timezone.utc),
                change_pct=0.0,
            )
        return None

    async def _fetch_goldapi(self) -> float | None:
        try:
            url = self._settings.xau_live_api_url
            raw = await asyncio.to_thread(_http_json, url, 15)
            if isinstance(raw, dict) and raw.get("price"):
                return float(raw["price"])
        except Exception as exc:
            logger.warning("gold-api.com 取数失败: %s", exc)
        return None

    async def _fetch_sina_hf_gc(self) -> float | None:
        try:
            url = self._settings.sina_gc_url

            def _get() -> str:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Referer": "https://finance.sina.com.cn",
                    },
                )
                with urllib.request.urlopen(req, timeout=12) as r:
                    return r.read().decode("utf-8", "ignore")

            text = await asyncio.to_thread(_get)
            seg = text.split('hf_GC="', 1)[-1].split('"', 1)[0]
            parts = seg.split(",")
            price = float(parts[7])
            if price <= 0:
                return None
            return price
        except Exception as exc:
            logger.warning("sina hf_GC 取数失败: %s", exc)
        return None


class AkshareTreasuryYieldProvider:
    """美债 10Y/30Y 收益率：美联储 H.15 官方源（零KEY、T+1~T+3 滞后）。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def get_treasury_yields(self) -> USTYield | None:
        try:
            url = self._settings.h15_csv_url

            def _get_and_parse() -> USTYield | None:
                text = _http_text(url, 15)
                return _parse_h15_csv(text)

            result = await asyncio.wait_for(asyncio.to_thread(_get_and_parse), timeout=20)
            return result
        except Exception as exc:
            logger.warning("H.15 取数失败: %s", exc)
        return None


# ───────────────────── Mock Provider（零网络、零依赖） ─────────────────────


def _mock_history(base: float, days: int, volume: float = 100000.0) -> list[GoldKline]:
    """通用确定性 Mock K 线生成器（用于 ETF）。"""
    today = date.today()
    points: list[GoldKline] = []
    for i in range(days, 0, -1):
        day = today - timedelta(days=i)
        if day.weekday() >= 5:
            continue
        progress = (days - i) / days
        wave = 0.06 * (1 - abs(progress - 0.7) / 0.7)
        close = round(base * (1 + 0.09 * progress - 0.03 * (progress**2)) * (1 + wave), 3)
        points.append(
            GoldKline(
                date=day,
                open=round(close * 0.995, 3),
                close=close,
                high=round(close * 1.01, 3),
                low=round(close * 0.99, 3),
                volume=volume,
            )
        )
    return points


def _mock_gram_history(days: int) -> list[GoldKline]:
    """确定性 Mock 克价序列（约 990 元/克）。"""
    base = 985.0
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


def _mock_us_history(days: int) -> list[GoldKline]:
    """确定性 Mock 纽约金序列（约 4500 美元/盎司）。"""
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


class MockGoldHistoryProvider:
    """纯内存 ETF/克价/纽约金历史 Provider：返回确定性 Mock 序列。

    不依赖 akshare、不联网、可离线演示与测试场景直接复用。
    """

    async def get_history(
        self, symbol: str = DEFAULT_GOLD_ETF, days: int = 60,
    ) -> list[GoldKline]:
        return _mock_history(base=5.42, days=days)

    async def get_gram_history(
        self, symbol: str = DEFAULT_GOLD_GRAM, days: int = 60,
    ) -> list[GoldKline]:
        return _mock_gram_history(days=days)

    async def get_us_gold_history(
        self, symbol: str = DEFAULT_NY_GOLD, days: int = 60,
    ) -> list[GoldKline]:
        return _mock_us_history(days=days)


class MockLiveQuoteProvider:
    """Mock 实时报价：固定值。"""

    async def get_live_quote(self) -> GoldQuote:
        return GoldQuote(
            symbol="XAU",
            price_usd=2350.5,
            change_pct=0.42,
            updated_at=datetime.now(timezone.utc),
        )


class MockTreasuryYieldProvider:
    """Mock 美债收益率：固定值。"""

    async def get_treasury_yields(self) -> USTYield:
        return USTYield(
            us10y=4.20,
            us30y=4.45,
            data_date=date.today() - timedelta(days=2),
        )


# ───────────────────── 工厂 ─────────────────────


def _bundle_history(history: GoldHistoryProvider) -> MarketProviderBundle:
    """组合器：用 history provider + 默认 live/treasury 构造 bundle。"""
    return MarketProviderBundle(
        history=history,
        live=AkshareLiveQuoteProvider(),
        treasury=AkshareTreasuryYieldProvider(),
    )


PROVIDER_REGISTRY: dict[str, Callable[[Settings], MarketProviderBundle]] = {
    "akshare": lambda s: MarketProviderBundle(
        history=AkshareGoldHistoryProvider(s),
        live=AkshareLiveQuoteProvider(s),
        treasury=AkshareTreasuryYieldProvider(s),
    ),
    "mock": lambda s: MarketProviderBundle(
        history=MockGoldHistoryProvider(),
        live=MockLiveQuoteProvider(),
        treasury=MockTreasuryYieldProvider(),
    ),
    "eastmoney_only": lambda s: MarketProviderBundle(
        history=EastmoneyOnlyHistoryProvider(s),
        live=AkshareLiveQuoteProvider(s),
        treasury=AkshareTreasuryYieldProvider(s),
    ),
    "sina_only": lambda s: MarketProviderBundle(
        history=SinaOnlyHistoryProvider(s),
        live=AkshareLiveQuoteProvider(s),
        treasury=AkshareTreasuryYieldProvider(s),
    ),
}


def build_provider_bundle(settings: Settings | None = None) -> MarketProviderBundle:
    """按 settings.market_provider 名称解析 provider bundle。

    未知名抛 ``ValueError``（含可选列表提示）。
    """
    s = settings or get_settings()
    name = (s.market_provider or "akshare").strip().lower()
    factory = PROVIDER_REGISTRY.get(name)
    if factory is None:
        raise ValueError(
            f"未知 MARKET_PROVIDER={name!r}，可选：{sorted(PROVIDER_REGISTRY.keys())}"
        )
    return factory(s)
