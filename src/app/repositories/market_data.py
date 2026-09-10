"""行情数据源：AKShare 免费采集 + 零KEY公开源兜底 + Mock 降级（V0.59.0 重构）。

设计：
- 三个窄接口 + bundle 抽到 ``market_providers.py``（V0.59.0 新增）；
- 本模块保留 ``MarketDataRepository`` 入口 + 降级 Mock + 数据时效元信息；
- 旧 ``provider=`` kwarg 通过 ``MarketDataRepository`` 自动包装为 bundle 向后兼容。

重要：本应用**不依赖任何付费 API KEY**，全部为公开免费源：
- gold-api.com：实时 XAU/USD 即期报价（零KEY、无需注册）
- Federal Reserve H.15：美债10Y/30Y 收益率曲线（零KEY、官方源、T+1~T+3 滞后）
- AKShare：东方财富/新浪 ETF 历史、上海金交所 Au99.99（免费开源库）
- 美元指数/VIX 等宏观因子由 macro.py 内置静态参考值提供（可平滑替换为实时 provider）
"""

import asyncio
import csv
import io
import json
import threading
import time
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Protocol

from app.config import Settings, get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 行情结果缓存（TTL）：同一标的/天数在有效期内复用，避免重复网络请求拖慢首屏
# V0.59.0：默认值仍为 300（5 分钟），实际 TTL 改为按 settings.quote_cache_ttl 读取，
# 此常量仅作向后兼容（外部直接 import QUOTE_CACHE_TTL 的代码仍可用）。
QUOTE_CACHE_TTL = 300  # 5 分钟（默认）
_CACHE: dict[tuple, tuple[float, list]] = {}
_CACHE_LOCK = threading.Lock()


def _cache_get(key: tuple, ttl: int) -> list | None:
    """读取缓存（未过期返回值，否则 None）。ttl<=0 表示禁用缓存。"""
    if ttl <= 0:
        return None
    with _CACHE_LOCK:
        item = _CACHE.get(key)
    if item is not None and time.time() - item[0] < ttl:
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


@dataclass(frozen=True)
class USTYield:
    """美债收益率快照（数据源无关）。

    数据源：美联储 H.15（Selected Interest Rates），T+1~T+3 滞后。
    """

    us10y: float  # 10 年期收益率（%）
    us30y: float  # 30 年期收益率（%）
    data_date: date  # 数据截止日（H.15 最近一个交易日）


# H.15 CSV 前 5 行为元数据（Series Description / Unit / Multiplier / Currency / Unique Identifier），
# 第 6 行为列名（含 RIFLGFCY10_N.B / RIFLGFCY30_N.B）。解析时跳过前 5 行。
_H15_HEADER_SKIP = 5
_H15_COL_DATE = "Time Period"
_H15_COL_10Y = "RIFLGFCY10_N.B"
_H15_COL_30Y = "RIFLGFCY30_N.B"


def _parse_h15_csv(text: str) -> USTYield | None:
    """解析美联储 H.15 CSV 文本，提取最近一行同时含 10Y/30Y 数据的快照。

    CSV 头部有 5 行元数据描述 + 1 行列名，跳过前 5 行后用 csv.DictReader 解析。
    末尾可能若干行 10Y/30Y 列为空（节假日/未公布），从末尾反向找首个双非空行。
    """
    try:
        rows = list(csv.reader(io.StringIO(text)))
        if len(rows) <= _H15_HEADER_SKIP:
            return None
        # 第 6 行（索引 _H15_HEADER_SKIP）为列名
        header = rows[_H15_HEADER_SKIP]
        if _H15_COL_10Y not in header or _H15_COL_30Y not in header:
            return None
        idx_date = header.index(_H15_COL_DATE)
        idx_10y = header.index(_H15_COL_10Y)
        idx_30y = header.index(_H15_COL_30Y)

        # 从末尾反向找首个双非空行
        for row in reversed(rows[_H15_HEADER_SKIP + 1:]):
            if len(row) <= max(idx_date, idx_10y, idx_30y):
                continue
            v10, v30, d = row[idx_10y].strip(), row[idx_30y].strip(), row[idx_date].strip()
            if not v10 or not v30 or not d:
                continue
            return USTYield(
                us10y=float(v10),
                us30y=float(v30),
                data_date=datetime.strptime(d, "%Y-%m-%d").date(),
            )
    except (ValueError, IndexError, csv.Error) as exc:
        logger.warning("H.15 CSV 解析失败: %s", exc)
    return None


class GoldHistoryProvider(Protocol):
    """历史 K 线数据源接口（V0.59.0 保留向后兼容；新代码用 bundle）。"""


# ───────────────────── 向后兼容 shim（V0.58 旧测试代码） ─────────────────────
# 旧版 AkshareGoldDataProvider 已被 AkshareGoldHistoryProvider 取代；
# 但部分旧测试可能仍通过 from ... import AkshareGoldDataProvider 引用。
# 这里提供延迟 import 转发以保持 ABI 兼容。
def __getattr__(name: str):  # pragma: no cover
    if name == "AkshareGoldDataProvider":
        from app.repositories.market_providers import AkshareGoldHistoryProvider

        logger.warning(
            "AkshareGoldDataProvider 已弃用，请改用 AkshareGoldHistoryProvider",
        )
        return AkshareGoldHistoryProvider
    if name == "fetch_us_treasury_h15":
        from app.repositories.market_providers import AkshareTreasuryYieldProvider

        async def _shim() -> USTYield | None:
            return await AkshareTreasuryYieldProvider().get_treasury_yields()

        return _shim
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class MarketDataRepository:
    """行情数据源入口：实时公开源优先，异常自动回退 Mock（降级可感知）。

    V0.59.0 重构：
    - 新增 ``bundle`` 参数：注入 ``MarketProviderBundle`` 三件套（推荐）；
    - 旧 ``provider`` 参数：自动包装为 bundle（向后兼容）；
    - 新增 ``settings`` 参数：注入配置（默认走 ``get_settings()``）；
    - 缓存 TTL 改为按 ``settings.quote_cache_ttl`` 读取（默认 300）；
    - XAU fallback chain 按 ``settings.xau_fallback_chain`` 顺序执行；
    - 旧 ``_mock_*`` 静态方法保留（内部 fallback 使用），等价逻辑已迁到 market_providers。
    """

    def __init__(
        self,
        provider: GoldHistoryProvider | None = None,
        *,
        bundle: object | None = None,
        settings: Settings | None = None,
        xau_fallback_chain: list[str] | None = None,
        cache_ttl: int | None = None,
    ) -> None:
        # 懒加载 market_providers 避免循环依赖
        from app.repositories.market_providers import (
            AkshareGoldHistoryProvider,
            build_provider_bundle,
        )

        self._settings = settings or get_settings()
        self._cache_ttl = (
            cache_ttl if cache_ttl is not None else self._settings.quote_cache_ttl
        )
        self._xau_chain = (
            xau_fallback_chain
            if xau_fallback_chain is not None
            else self._settings.xau_fallback_chain_list
        )

        # 三种构造方式优先级：bundle > provider（兼容）> settings 自动解析
        if bundle is not None:
            self._bundle = bundle
        elif provider is not None:
            # 旧签名：把单个 provider 包成 bundle（live/treasury 仍走默认 akshare 实现）
            from app.repositories.market_providers import (
                AkshareLiveQuoteProvider,
                AkshareTreasuryYieldProvider,
                MarketProviderBundle,
            )

            self._bundle = MarketProviderBundle(
                history=provider,
                live=AkshareLiveQuoteProvider(self._settings),
                treasury=AkshareTreasuryYieldProvider(self._settings),
            )
        else:
            # 新签名：按 settings.market_provider 自动解析
            self._bundle = build_provider_bundle(self._settings)

        # 数据源状态：key → "live"（真实）/ "mock"（降级演示）
        self._sources: dict[str, str] = {}
        # 采集元信息（供「数据时效透明」展示）：各源最近一次采集时刻(UTC)与数据截止日
        self._fetched_at: dict[str, datetime] = {}
        self._last_date: dict[str, date] = {}

    def _mark(
        self,
        key: str,
        ok: bool,
        last_date: date | None = None,
    ) -> None:
        """记录数据源取数结果，并登记采集时刻与数据截止日（供数据时效透明展示）。"""
        self._sources[key] = "live" if ok else "mock"
        self._fetched_at[key] = datetime.now(timezone.utc)
        if last_date is not None:
            self._last_date[key] = last_date

    def source_status(self) -> dict[str, str]:
        """各数据源状态明细（供接口返回与页面展示）。"""
        return dict(self._sources)

    def is_degraded(self) -> bool:
        """是否存在任一数据源降级为 Mock。"""
        return any(v == "mock" for v in self._sources.values())

    def source_meta(self) -> dict[str, dict]:
        """各数据源采集元信息（状态 / 采集时刻 UTC / 数据截止日），供数据时效透明展示。

        返回形如 ``{key: {"status": ..., "fetched_at": datetime|None, "last_date": date|None}}``。
        """
        return {
            key: {
                "status": status,
                "fetched_at": self._fetched_at.get(key),
                "last_date": self._last_date.get(key),
            }
            for key, status in self._sources.items()
        }

    async def get_gold_quote(self, symbol: str = "XAU") -> GoldQuote:
        """获取黄金最新报价（按 settings.xau_fallback_chain 顺序逐源尝试）。"""
        change = 0.0
        try:
            change = await self._sge_daily_change()
        except Exception:  # noqa: BLE001
            pass

        for token in self._xau_chain:
            price = await self._fetch_xau_by_token(token)
            if price and price > 0:
                self._mark("xau", True)
                return GoldQuote(
                    symbol=symbol,
                    price_usd=round(price, 2),
                    change_pct=change,
                    updated_at=datetime.now(timezone.utc),
                )

        # 全部 XAU 源失败 → 兜底：ETF 历史推导
        try:
            klines = await self._bundle.history.get_history(DEFAULT_GOLD_ETF, days=3)
            if klines and len(klines) >= 2:
                last, prev = klines[-1], klines[-2]
                change_pct = (last.close - prev.close) / prev.close * 100 if prev.close else 0.0
                self._mark("xau", True)
                return GoldQuote(
                    symbol=symbol,
                    price_usd=round(last.close, 3),
                    change_pct=round(change_pct, 2),
                    updated_at=datetime.combine(last.date, datetime.min.time(), tzinfo=timezone.utc),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("quote from history failed (%s), fallback to mock", exc)
        self._mark("xau", False)
        return GoldQuote(
            symbol=symbol,
            price_usd=2350.5,
            change_pct=0.42,
            updated_at=datetime.now(timezone.utc),
        )

    async def _fetch_xau_by_token(self, token: str) -> float | None:
        """按 token 从对应源取 XAU 实时价。"""
        token = token.strip().lower()
        if token == "goldapi":
            from app.repositories.market_providers import AkshareLiveQuoteProvider

            provider = (
                self._bundle.live
                if isinstance(self._bundle.live, AkshareLiveQuoteProvider)
                else AkshareLiveQuoteProvider(self._settings)
            )
            # 直接走 goldapi（不走 fallback chain）
            url = self._settings.xau_live_api_url

            def _get() -> dict:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "Mozilla/5.0"},
                )
                with urllib.request.urlopen(req, timeout=15) as r:
                    return json.loads(r.read().decode("utf-8", "ignore"))

            try:
                raw = await asyncio.to_thread(_get)
                if isinstance(raw, dict) and raw.get("price"):
                    return float(raw["price"])
            except Exception as exc:  # noqa: BLE001
                logger.warning("goldapi 取数失败: %s", exc)
            return None
        if token == "sina":
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

            try:
                text = await asyncio.to_thread(_get)
                seg = text.split('hf_GC="', 1)[-1].split('"', 1)[0]
                parts = seg.split(",")
                price = float(parts[7])
                if price > 0:
                    return price
            except Exception as exc:  # noqa: BLE001
                logger.warning("sina hf_GC 取数失败: %s", exc)
            return None
        if token == "etf_history":
            try:
                klines = await self._bundle.history.get_history(DEFAULT_GOLD_ETF, days=3)
                if klines and len(klines) >= 2:
                    last, prev = klines[-1], klines[-2]
                    return float(last.close)
            except Exception as exc:  # noqa: BLE001
                logger.warning("etf_history 取数失败: %s", exc)
            return None
        logger.warning("未知 xau_fallback_chain token: %s", token)
        return None

    async def get_gold_history(self, days: int = 60) -> list[GoldKline]:
        """获取黄金 ETF 历史日 K；失败时返回确定性 Mock 序列（可离线演示）。"""
        try:
            klines = await self._bundle.history.get_history(DEFAULT_GOLD_ETF, days=days)
            if klines:
                self._mark("etf", True, last_date=klines[-1].date)
                return klines
            raise RuntimeError("empty history")
        except Exception as exc:  # noqa: BLE001
            logger.warning("history from provider failed (%s), fallback to mock", exc)
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
            klines = await self._bundle.history.get_gram_history(symbol=symbol, days=days)
            if klines:
                self._mark("sge", True, last_date=klines[-1].date)
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
        from app.repositories.market_providers import _mock_gram_history

        return _mock_gram_history(days=days)

    async def get_us_gold_quote(self, symbol: str = DEFAULT_NY_GOLD) -> GoldQuote:
        """获取纽约金最新报价（美元/盎司）。"""
        # 主源：零KEY公开 XAU/USD 即期报价（与COMEX高度联动）
        change = 0.0
        try:
            change = await self._sge_daily_change()
        except Exception:  # noqa: BLE001
            pass

        for token in self._xau_chain:
            price = await self._fetch_xau_by_token(token)
            if price and price > 0:
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
            klines = await self._bundle.history.get_us_gold_history(symbol=symbol, days=days)
            if klines:
                self._mark("ny", True, last_date=klines[-1].date)
                return klines
            raise RuntimeError("empty us gold history")
        except Exception as exc:  # noqa: BLE001
            logger.warning("us gold history failed (%s), fallback to mock", exc)
            self._mark("ny", False)
            return self._mock_us_history(days)

    async def get_us_treasury_yields(self) -> USTYield | None:
        """获取美债 10Y/30Y 收益率（美联储 H.15 官方源）；失败返回 None。

        调用方（macro 服务）应保持内置静态参考值作为降级。
        """
        try:
            result = await self._bundle.treasury.get_treasury_yields()
        except Exception as exc:  # noqa: BLE001
            logger.warning("treasury provider 调用失败: %s", exc)
            result = None
        if result is not None:
            self._mark("ust", True, last_date=result.data_date)
        else:
            self._mark("ust", False)
        return result

    @staticmethod
    def _mock_us_history(days: int) -> list[GoldKline]:
        """确定性 Mock 纽约金序列（约 4500 美元/盎司区间）。"""
        from app.repositories.market_providers import _mock_us_history

        return _mock_us_history(days=days)

    @staticmethod
    def _mock_history(days: int) -> list[GoldKline]:
        """确定性 Mock 序列：近 2 个月黄金上行后回调，便于离线演示。"""
        from app.repositories.market_providers import _mock_history

        return _mock_history(base=5.42, days=days)

