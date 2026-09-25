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

try:
    import httpx  # V0.73.x+ Yahoo Silver HTTP 客户端（白银数据源）
except ImportError:  # pragma: no cover — 已在 pyproject.toml 声明 httpx；此处仅兜底
    httpx = None  # type: ignore[assignment]
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
        self,
        symbol: str = DEFAULT_GOLD_ETF,
        days: int = 60,
    ) -> list[GoldKline]: ...

    async def get_gram_history(
        self,
        symbol: str = DEFAULT_GOLD_GRAM,
        days: int = 60,
    ) -> list[GoldKline]: ...

    async def get_us_gold_history(
        self,
        symbol: str = DEFAULT_NY_GOLD,
        days: int = 60,
    ) -> list[GoldKline]: ...


class GoldLiveQuoteProvider(Protocol):
    """实时 XAU/USD 即期报价数据源接口。"""

    async def get_live_quote(self) -> GoldQuote | None: ...


class TreasuryYieldProvider(Protocol):
    """美债 10Y/30Y 收益率数据源接口。"""

    async def get_treasury_yields(self) -> USTYield | None: ...


class SilverHistoryProvider(Protocol):
    """白银历史 K 线数据源接口（V0.71.0 新增）。

    数据模型复用 GoldKline（OHLC + volume），调用方在仓储层包装为 SilverKline 输出。
    symbol 默认 ``DEFAULT_SILVER_ETF = "562800"``；传 ``"SI"`` 走纽约白银路径。
    """

    async def get_silver_history(
        self,
        symbol: str = "562800",
        days: int = 60,
    ) -> list[GoldKline]: ...


class SilverLiveQuoteProvider(Protocol):
    """白银实时报价数据源接口（V0.73.0 N+17 新增）。

    返回白银**当前价**（美元/盎司或元/份，由实现决定）。
    实现示例：AkshareSilverLiveProvider（Sina hf_SI 实时）。
    """

    async def get_silver_spot(self, symbol: str = "SI") -> float | None: ...


@dataclass(frozen=True)
class MarketProviderBundle:
    """Provider 五件套打包（V0.73.0 N+17 起含白银实时源），便于按名一次性注入。"""

    history: GoldHistoryProvider
    live: GoldLiveQuoteProvider
    treasury: TreasuryYieldProvider
    silver_history: SilverHistoryProvider | None = None  # V0.71.0 新增
    silver_live: SilverLiveQuoteProvider | None = None  # V0.73.0 N+17 新增


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
            capture_output=True,
            text=True,
            timeout=30,
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
            capture_output=True,
            text=True,
            timeout=30,
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
        self,
        symbol: str = DEFAULT_GOLD_ETF,
        days: int = 60,
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

        return await asyncio.wait_for(asyncio.to_thread(_fetch), timeout=30)

    async def get_us_gold_history(
        self,
        symbol: str = DEFAULT_NY_GOLD,
        days: int = 60,
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
        self,
        symbol: str = DEFAULT_GOLD_ETF,
        days: int = 60,
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
        self,
        symbol: str = DEFAULT_GOLD_GRAM,
        days: int = 60,
    ) -> list[GoldKline]:
        # 克价仍走 AKShare SGE（仅 ETF 历史受 V8 影响）
        return await AkshareGoldHistoryProvider(self._settings).get_gram_history(symbol, days)

    async def get_us_gold_history(
        self,
        symbol: str = DEFAULT_NY_GOLD,
        days: int = 60,
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
        self,
        symbol: str = DEFAULT_GOLD_ETF,
        days: int = 60,
    ) -> list[GoldKline]:
        prefix = "sh" if symbol.startswith(("5", "6")) else "sz"
        sub = await asyncio.to_thread(_sina_etf_via_subprocess, f"{prefix}{symbol}", days)
        if not sub:
            raise RuntimeError("sina empty")
        return sub

    async def get_gram_history(
        self,
        symbol: str = DEFAULT_GOLD_GRAM,
        days: int = 60,
    ) -> list[GoldKline]:
        return await AkshareGoldHistoryProvider(self._settings).get_gram_history(symbol, days)

    async def get_us_gold_history(
        self,
        symbol: str = DEFAULT_NY_GOLD,
        days: int = 60,
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
        self,
        symbol: str = DEFAULT_GOLD_ETF,
        days: int = 60,
    ) -> list[GoldKline]:
        return _mock_history(base=5.42, days=days)

    async def get_gram_history(
        self,
        symbol: str = DEFAULT_GOLD_GRAM,
        days: int = 60,
    ) -> list[GoldKline]:
        return _mock_gram_history(days=days)

    async def get_us_gold_history(
        self,
        symbol: str = DEFAULT_NY_GOLD,
        days: int = 60,
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


# ───────────────────── V0.71.0：白银 Provider ─────────────────────


def _mock_silver_etf_history(days: int) -> list[GoldKline]:
    """确定性 Mock 白银 ETF 序列（约 2.45 元/份）。"""
    base = 2.45
    today = date.today()
    points: list[GoldKline] = []
    for i in range(days, 0, -1):
        day = today - timedelta(days=i)
        if day.weekday() >= 5:
            continue
        progress = (days - i) / days
        wave = 0.06 * (1 - abs(progress - 0.7) / 0.7)
        close = round(base * (1 + 0.07 * progress - 0.025 * (progress**2)) * (1 + wave), 3)
        points.append(
            GoldKline(
                date=day,
                open=round(close * 0.995, 3),
                close=close,
                high=round(close * 1.01, 3),
                low=round(close * 0.99, 3),
                volume=0.0,
            )
        )
    return points


def _mock_silver_ny_history(days: int) -> list[GoldKline]:
    """确定性 Mock 纽约白银序列（锚定当前 SI=F 现实区间 ~64 美元/盎司）。

    V0.73.0 N+15：base 从 31.5 上调到 64.0（2026-09 银价已升至 $60+）；
    若再次严重偏离现实（如 $100+），请同步更新此常量与下列说明。
    """
    base = 64.0
    today = date.today()
    points: list[GoldKline] = []
    for i in range(days, 0, -1):
        day = today - timedelta(days=i)
        if day.weekday() >= 5:
            continue
        progress = (days - i) / days
        wave = 0.06 * (1 - abs(progress - 0.7) / 0.7)
        close = round(base * (1 + 0.05 * progress - 0.02 * (progress**2)) * (1 + wave), 3)
        points.append(
            GoldKline(
                date=day,
                open=round(close * 0.995, 3),
                close=close,
                high=round(close * 1.01, 3),
                low=round(close * 0.99, 3),
                volume=0.0,
            )
        )
    return points


class MockSilverHistoryProvider:
    """纯内存白银历史 Provider：返回确定性 Mock 序列（V0.71.0 silver_mock 模式默认）。

    区分 ETF（562800，约 2.45 元/份）与 NY SI（约 64.0 美元/盎司，V0.73.0 N+15 随现实上调）：
    symbol 以 ``"SI"`` / ``"silver_ny"`` 视作 NY 路径，其余 ETF 路径。

    V0.73.0 N+17：声明 ``_last_was_fallback=True`` 契约，让仓储层 ``_is_silver_data_real()``
    自动识别这是 mock 数据（前端 freshness 角标不会误标为 live）。
    """

    _last_was_fallback: bool = True  # 始终 mock

    async def get_silver_history(
        self,
        symbol: str = "562800",
        days: int = 60,
    ) -> list[GoldKline]:
        if str(symbol).upper() in ("SI", "SILVER_NY", "GC_NY"):
            return _mock_silver_ny_history(days=days)
        return _mock_silver_etf_history(days=days)


class AkshareSilverLiveProvider:
    """白银实时报价（V0.73.0 N+17 新增）：新浪 hf_SI。

    端点：``https://hq.sinajs.cn/list=hf_SI``
    字段顺序（15 字段，0-indexed）：
        0=当前价 | 1=_ | 2=开盘 | 3=最新 | 4=最高 | 5=最低 | 6=时间 |
        7=买价 | 8=卖价 | 9=成交量 | 10=持仓 | 11=日期序号 | 12=日期 | 13=品种名 | 14=市场

    返回：当前 SI 价（美元/盎司，纽约白银期货主力）。

    **与黄金 hf_GC 1:1 对称**：复用现有 ``_fetch_sina_hf_gc`` 模式，无 V8 依赖、
    零 KEY、零依赖 urllib。失败 → 返回 ``None``，由仓储层降级。
    """

    HF_SI_URL = "https://hq.sinajs.cn/list=hf_SI"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def get_silver_spot(self, symbol: str = "SI") -> float | None:
        try:
            url = self.HF_SI_URL

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
            seg = text.split('hf_SI="', 1)[-1].split('"', 1)[0]
            parts = seg.split(",")
            price = float(parts[0])  # 当前价
            if price > 0:
                return price
        except Exception as exc:
            logger.warning("sina hf_SI 取数失败: %s", exc)
        return None


class MockSilverLiveQuoteProvider:
    """Mock 白银实时报价：固定值（与 MockLiveQuoteProvider 对称）。

    NY SI 默认 64.0 美元/盎司（V0.73.0 N+15 现实锚定）；ETF 默认 2.45 元/份。
    """

    NY_MOCK_PRICE = 64.0
    ETF_MOCK_PRICE = 2.45

    async def get_silver_spot(self, symbol: str = "SI") -> float | None:
        if str(symbol).upper() in ("562800", "SILVER_ETF"):
            return self.ETF_MOCK_PRICE
        return self.NY_MOCK_PRICE


class AkshareSilverHistoryProvider:
    """AKShare 白银数据源（V0.73.0 N+17 完整实现，替代 V0.71.0 stub）。

    - ETF（562800）：``fund_etf_hist_em``（与 518880 完全同路径，不依赖 V8，主进程直调）；
    - NY SI：``futures_foreign_hist(symbol="SI")``（与 GC 同路径，可能触发 V8 → 子进程隔离）。

    任一源失败 → 抛 ``RuntimeError``，由仓储层标记 mock 并降级到内置 Mock 序列。
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        # V0.73.0 N+17：与 YahooSilverHistoryProvider 对齐 _last_was_fallback 契约
        # —— 本 provider 失败时由仓储层走 mock 兜底，不在这里静默降级。
        self._last_was_fallback: bool = False

    async def get_silver_history(
        self,
        symbol: str = "562800",
        days: int = 60,
    ) -> list[GoldKline]:
        sym_upper = str(symbol).upper()
        if sym_upper in ("SI", "SILVER_NY", "GC_NY"):
            return await self._fetch_ny_silver(days)
        return await self._fetch_etf_silver(symbol, days)

    async def _fetch_etf_silver(self, symbol: str, days: int) -> list[GoldKline]:
        """ETF 路径：fund_etf_hist_em（与 AkshareGoldHistoryProvider 完全对称）。"""
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
                raise RuntimeError(f"eastmoney empty for {symbol}")
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

    async def _fetch_ny_silver(self, days: int) -> list[GoldKline]:
        """NY 路径：futures_foreign_hist 子进程隔离（与 GC 同路径）。"""
        sub = await asyncio.to_thread(_us_gold_via_subprocess, "SI", days)
        if not sub:
            raise RuntimeError("akshare NY silver subprocess empty")
        return sub


# ───────────────────── V0.73.x+ Yahoo Silver ─────────────────────

# Yahoo Finance symbol 映射：内部 symbol → Yahoo ticker
# 562800（华安白银 ETF）→ 562800.SS（上交所）
# SI / silver_ny → SI=F（NY 银主连期货）
YAHOO_SILVER_SYMBOLS: dict[str, str] = {
    "562800": "562800.SS",
    "silver_etf": "562800.SS",
    "SI": "SI=F",
    "silver_ny": "SI=F",
    "GC_NY": "GC=F",
}


class YahooSilverHistoryProvider:
    """Yahoo Finance 白银数据源（V0.73.x+ 新增）。

    端点：``https://query1.finance.yahoo.com/v8/finance/chart/{symbol}``
    参数：``interval=1d&range={N}d&includeAdjustedClose=true``
    响应：``chart.result[0].timestamp[]`` + ``indicators.quote[0].{open,high,low,close,volume}[]``

    **降级策略**：任何 HTTP/解析错误 → 自动 fallback 到 ``MockSilverHistoryProvider``，
    日志 warning；保证白银页永不因外部源挂掉。设计目标是「有数据 > 没数据」。

    使用：在 ``.env`` 设 ``MARKET_PROVIDER=silver_yahoo`` 即可。
    """

    YAHOO_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
    USER_AGENT = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    TIMEOUT_SECONDS = 10.0
    # Yahoo 偶发 429；429 时退避 1s 再试一次
    RETRY_ON_429 = 1

    def __init__(self) -> None:
        self._fallback = MockSilverHistoryProvider()
        # V0.73.0 N+15：标记上一次 ``get_silver_history()`` 是否走 fallback 到 mock。
        # 仓储层据此判断 ``_mark(ok=True/False)``，避免 mock 数据被错标为 live。
        self._last_was_fallback: bool = False

    @classmethod
    def resolve_yahoo_symbol(cls, symbol: str) -> str:
        """内部 symbol → Yahoo ticker（大小写不敏感）。"""
        sym = (symbol or "").upper()
        # 大小写不敏感匹配（dict key 是小写）
        for key, val in YAHOO_SILVER_SYMBOLS.items():
            if key.upper() == sym:
                return val
        # 默认：原样作为 Yahoo symbol（如用户直接传 562800.SS）
        return symbol

    @staticmethod
    def _parse_yahoo_chart(payload: dict, days: int) -> list[GoldKline]:
        """解析 Yahoo chart v8 响应为 GoldKline 列表（按日期降序截取最后 N 天）。"""
        results = payload.get("chart", {}).get("result") or []
        if not results:
            return []
        r0 = results[0]
        ts_list = r0.get("timestamp") or []
        quote = (r0.get("indicators", {}).get("quote") or [{}])[0]
        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []
        out: list[GoldKline] = []
        for i, ts in enumerate(ts_list):
            close = closes[i] if i < len(closes) else None
            if close is None:
                continue  # Yahoo 偶发 null close（节假日占位）
            d = datetime.fromtimestamp(int(ts), tz=timezone.utc).date()
            out.append(
                GoldKline(
                    date=d,
                    open=opens[i] if i < len(opens) and opens[i] is not None else close,
                    high=highs[i] if i < len(highs) and highs[i] is not None else close,
                    low=lows[i] if i < len(lows) and lows[i] is not None else close,
                    close=float(close),
                    volume=float(volumes[i]) if i < len(volumes) and volumes[i] is not None else 0.0,
                )
            )
        # 升序（旧→新），截取最后 days 天
        out.sort(key=lambda k: k.date, reverse=False)
        return out[-days:] if len(out) > days else out

    async def _fetch_yahoo(self, yahoo_symbol: str, days: int) -> list[GoldKline]:
        if httpx is None:
            raise RuntimeError("httpx 未安装，YahooSilverHistoryProvider 不可用")
        # Yahoo range 至少要大于 days（避免节假日窗口不足）
        range_days = max(days * 2, 60)
        url = f"{self.YAHOO_BASE}/{yahoo_symbol}"
        params = {
            "interval": "1d",
            "range": f"{range_days}d",
            "includeAdjustedClose": "true",
            "events": "history",
        }
        headers = {"User-Agent": self.USER_AGENT, "Accept": "application/json"}
        last_exc: Exception | None = None
        for attempt in range(self.RETRY_ON_429 + 1):
            try:
                async with httpx.AsyncClient(timeout=self.TIMEOUT_SECONDS) as client:
                    resp = await client.get(url, params=params, headers=headers)
                if resp.status_code == 200:
                    return self._parse_yahoo_chart(resp.json(), days)
                if resp.status_code == 429 and attempt < self.RETRY_ON_429:
                    await asyncio.sleep(1.0)
                    continue
                raise RuntimeError(
                    f"Yahoo Finance HTTP {resp.status_code} for {yahoo_symbol}: {resp.text[:200]}"
                )
            except Exception as exc:  # 网络异常 / 解析失败 / HTTP 4xx/5xx
                last_exc = exc
                break
        raise last_exc if last_exc else RuntimeError("Yahoo fetch failed (unknown)")

    async def get_silver_history(
        self,
        symbol: str = "562800",
        days: int = 60,
    ) -> list[GoldKline]:
        yahoo_symbol = self.resolve_yahoo_symbol(symbol)
        try:
            data = await self._fetch_yahoo(yahoo_symbol, days)
            if data:
                self._last_was_fallback = False
                return data
            # Yahoo 返回空（罕见）→ 仍降级
            logger.warning(
                "Yahoo Silver %s 返回空数据，降级到 mock", yahoo_symbol,
            )
        except Exception as exc:
            logger.warning(
                "Yahoo Silver %s 拉取失败（%s），降级到 mock",
                yahoo_symbol, type(exc).__name__,
            )
        # 自动 fallback 到 mock（设计目标：有数据 > 没数据）
        # V0.73.0 N+15：同时设 ``_last_was_fallback=True``，让仓储层知道这是 mock。
        self._last_was_fallback = True
        return await self._fallback.get_silver_history(symbol=symbol, days=days)

    async def get_silver_spot(self, symbol: str = "562800") -> GoldKline | None:
        """拉取白银**当日最新 K 线**（range=2d，确保包含今天）。

        与 ``get_silver_history(days=60)`` 不同：后者请求 60 天会触发 Yahoo 429，
        这里用最小请求 ``range=2d`` 只为拿到今天的 close + date。
        Yahoo 对当日 bar 会**日内增量更新**（SI=F 几乎实时；562800.SS 也跟随
        A 股交易时段更新），所以 ``last_close`` 就是当前价格。

        Returns:
            最新一天的 ``GoldKline``；任意失败（HTTP 429 / 网络 / 解析 / Yahoo
            还没生成今日 bar）均返回 ``None``，由调用方决定降级到 history。
        """
        if httpx is None:
            return None
        yahoo_symbol = self.resolve_yahoo_symbol(symbol)
        url = f"{self.YAHOO_BASE}/{yahoo_symbol}"
        params = {
            "interval": "1d",
            "range": "2d",
            "includeAdjustedClose": "true",
            "events": "history",
        }
        headers = {"User-Agent": self.USER_AGENT, "Accept": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT_SECONDS) as client:
                resp = await client.get(url, params=params, headers=headers)
            if resp.status_code != 200:
                return None
            bars = self._parse_yahoo_chart(resp.json(), days=2)
            if not bars:
                return None
            return bars[-1]  # 最新一天（含今日的 running bar）
        except Exception:
            return None


# ───────────────────── 工厂 ─────────────────────


def _bundle_history(history: GoldHistoryProvider) -> MarketProviderBundle:
    """组合器：用 history provider + 默认 live/treasury 构造 bundle。"""
    return MarketProviderBundle(
        history=history,
        live=AkshareLiveQuoteProvider(),
        treasury=AkshareTreasuryYieldProvider(),
        silver_history=MockSilverHistoryProvider(),  # V0.71.0：默认 silver_mock 兜底
    )


PROVIDER_REGISTRY: dict[str, Callable[[Settings], MarketProviderBundle]] = {
    "akshare": lambda s: MarketProviderBundle(
        history=AkshareGoldHistoryProvider(s),
        live=AkshareLiveQuoteProvider(s),
        treasury=AkshareTreasuryYieldProvider(s),
        silver_history=AkshareSilverHistoryProvider(),  # V0.73.0 N+17：完整实现
        silver_live=AkshareSilverLiveProvider(s),  # V0.73.0 N+17：Sina hf_SI 实时
    ),
    "mock": lambda s: MarketProviderBundle(
        history=MockGoldHistoryProvider(),
        live=MockLiveQuoteProvider(),
        treasury=MockTreasuryYieldProvider(),
        silver_history=MockSilverHistoryProvider(),  # V0.71.0：mock 模式白银 mock
        silver_live=MockSilverLiveQuoteProvider(),  # V0.73.0 N+17
    ),
    "eastmoney_only": lambda s: MarketProviderBundle(
        history=EastmoneyOnlyHistoryProvider(s),
        live=AkshareLiveQuoteProvider(s),
        treasury=AkshareTreasuryYieldProvider(s),
        silver_history=AkshareSilverHistoryProvider(),
        silver_live=AkshareSilverLiveProvider(s),  # V0.73.0 N+17
    ),
    "sina_only": lambda s: MarketProviderBundle(
        history=SinaOnlyHistoryProvider(s),
        live=AkshareLiveQuoteProvider(s),
        treasury=AkshareTreasuryYieldProvider(s),
        silver_history=AkshareSilverHistoryProvider(),
        silver_live=AkshareSilverLiveProvider(s),  # V0.73.0 N+17
    ),
    # V0.71.0：白银专用 provider 名（不影响 gold 行为，仅 silver_history 走对应实现）
    "silver_mock": lambda s: MarketProviderBundle(
        history=AkshareGoldHistoryProvider(s),
        live=AkshareLiveQuoteProvider(s),
        treasury=AkshareTreasuryYieldProvider(s),
        silver_history=MockSilverHistoryProvider(),
        silver_live=MockSilverLiveQuoteProvider(),  # V0.73.0 N+17
    ),
    "silver_akshare": lambda s: MarketProviderBundle(
        history=AkshareGoldHistoryProvider(s),
        live=AkshareLiveQuoteProvider(s),
        treasury=AkshareTreasuryYieldProvider(s),
        silver_history=AkshareSilverHistoryProvider(),
        silver_live=AkshareSilverLiveProvider(s),  # V0.73.0 N+17
    ),
    # V0.73.x+：白银 Yahoo Finance（实时数据 + 自动 fallback mock）
    "silver_yahoo": lambda s: MarketProviderBundle(
        history=AkshareGoldHistoryProvider(s),
        live=AkshareLiveQuoteProvider(s),
        treasury=AkshareTreasuryYieldProvider(s),
        silver_history=YahooSilverHistoryProvider(),
        silver_live=AkshareSilverLiveProvider(s),  # V0.73.0 N+17：Yahoo 失败时 sina 兜底
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
        raise ValueError(f"未知 MARKET_PROVIDER={name!r}，可选：{sorted(PROVIDER_REGISTRY.keys())}")
    return factory(s)
