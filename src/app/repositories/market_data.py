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
import contextlib
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

# V0.71.0：白银双市场（ETF 562800 易方达白银 ETF + NY SI COMEX 白银期货主力）
DEFAULT_SILVER_ETF = "562800"
DEFAULT_SILVER_ETF_NAME = "白银ETF易方达"
DEFAULT_SILVER_NY = "SI"
DEFAULT_SILVER_NY_NAME = "纽约白银COMEX"


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
class SilverQuote:
    """白银报价（数据源无关；与 GoldQuote 同结构）。"""

    symbol: str
    price_usd: float
    change_pct: float
    updated_at: datetime


@dataclass(frozen=True)
class SilverKline:
    """白银单日 K 线（数据源无关；与 GoldKline 同结构）。"""

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
        for row in reversed(rows[_H15_HEADER_SKIP + 1 :]):
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
            build_provider_bundle,
        )

        self._settings = settings or get_settings()
        self._cache_ttl = cache_ttl if cache_ttl is not None else self._settings.quote_cache_ttl
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
                AkshareSilverHistoryProvider,
                AkshareTreasuryYieldProvider,
                MarketProviderBundle,
            )

            self._bundle = MarketProviderBundle(
                history=provider,
                live=AkshareLiveQuoteProvider(self._settings),
                treasury=AkshareTreasuryYieldProvider(self._settings),
                silver_history=AkshareSilverHistoryProvider(),  # V0.71.0：旧路径占位
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

    async def _try_silver_spot(self, symbol: str) -> GoldKline | None:
        """尝试白银 spot 报价（Yahoo 最小请求 ``range=2d``）。

        仅 ``YahooSilverHistoryProvider`` 支持；其他 provider 返回 ``None``。
        失败（HTTP 429 / 网络 / 解析 / 今日 bar 尚未生成）一律返回 ``None``。
        """
        spot_getter = getattr(self._bundle.silver_history, "get_silver_spot", None)
        if spot_getter is None:
            return None
        try:
            return await spot_getter(symbol=symbol)
        except Exception:
            return None

    def _is_silver_data_real(self, provider: object) -> bool:
        """判断白银 provider 这次返回的数据是否为真实数据（V0.73.0 N+17）。

        真实数据 = live / realtime；mock / fallback 一律视为演示数据（status=mock）。

        **契约**（V0.73.0 N+17 统一）：
        - provider 有 ``_last_was_fallback`` 属性 → 依其值判断（True=mock，False=live）；
        - 否则视为默认真数据（向后兼容未知 provider）。

        实现方责任：
        - ``YahooSilverHistoryProvider``：成功时 ``_last_was_fallback=False``，fallback 时 ``True``；
        - ``MockSilverHistoryProvider``：始终 ``_last_was_fallback=True``（兜底标记）；
        - ``AkshareSilverHistoryProvider``：默认 ``_last_was_fallback=False``（失败抛错由仓储层走 mock）。
        """
        # 统一契约：依 _last_was_fallback 标志位（V0.73.0 N+17 替代 N+15 的 class 名单）
        last_fallback = getattr(provider, "_last_was_fallback", None)
        if last_fallback is True:
            return False
        if last_fallback is False:
            return True
        # 向后兼容：未声明契约的 provider 默认视为真数据
        return True

    def source_status(self) -> dict[str, str]:
        """各数据源状态明细（供接口返回与页面展示）。

        V0.60.0：派生 ``"stale"`` 状态。若 ``_fetched_at`` 距今超过 ``_cache_ttl``，
        将原始 ``"live"`` 推导为 ``"stale"``（前端 freshness 角标据此点亮"缓存过期"分支）。
        ``"mock"`` 永远保持原值；``_cache_ttl<=0`` 视同禁用 TTL 派生（始终返回原状态）。
        """
        if self._cache_ttl <= 0:
            return dict(self._sources)
        now = datetime.now(timezone.utc)
        out: dict[str, str] = {}
        for key, raw in self._sources.items():
            if raw == "mock":
                out[key] = "mock"
                continue
            fetched = self._fetched_at.get(key)
            if fetched is not None and (now - fetched).total_seconds() > self._cache_ttl:
                out[key] = "stale"
            else:
                out[key] = raw
        return out

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
        """获取黄金最新报价（按 settings.xau_fallback_chain 顺序逐源尝试）。

        V0.60.0：启用 ``_cache_get/_cache_set``。cache hit 时直接返回缓存值，
        不重写 ``_fetched_at``，使 ``source_status()`` 的 staleness 推导自然生效。
        """
        cache_key = ("quote_xau",)
        cached = _cache_get(cache_key, ttl=self._cache_ttl)
        if cached is not None:
            return cached
        change = 0.0
        with contextlib.suppress(Exception):
            change = await self._sge_daily_change()

        for token in self._xau_chain:
            price = await self._fetch_xau_by_token(token)
            if price and price > 0:
                self._mark("xau", True)
                quote = GoldQuote(
                    symbol=symbol,
                    price_usd=round(price, 2),
                    change_pct=change,
                    updated_at=datetime.now(timezone.utc),
                )
                _cache_set(cache_key, quote)
                return quote

        # 全部 XAU 源失败 → 兜底：ETF 历史推导
        try:
            klines = await self._bundle.history.get_history(DEFAULT_GOLD_ETF, days=3)
            if klines and len(klines) >= 2:
                last, prev = klines[-1], klines[-2]
                change_pct = (last.close - prev.close) / prev.close * 100 if prev.close else 0.0
                self._mark("xau", True)
                quote = GoldQuote(
                    symbol=symbol,
                    price_usd=round(last.close, 3),
                    change_pct=round(change_pct, 2),
                    updated_at=datetime.combine(
                        last.date, datetime.min.time(), tzinfo=timezone.utc
                    ),
                )
                _cache_set(cache_key, quote)
                return quote
        except Exception as exc:
            logger.warning("quote from history failed (%s), fallback to mock", exc)
        self._mark("xau", False)
        return GoldQuote(
            symbol=symbol,
            price_usd=2350.5,
            change_pct=0.42,
            updated_at=datetime.now(timezone.utc),
        )

    async def get_gold_etf_quote(self, symbol: str = DEFAULT_GOLD_ETF) -> GoldQuote:
        """黄金 ETF（518880）最新价（人民币元/份）——**持仓估值与交易专用**。

        与 :meth:`get_gold_quote` 的区别：后者返回 XAU/USD 国际金价（美元/盎司，
        用于纽约金投资指引）；本方法返回国内 ETF 成交价（元/份），是持仓盈亏、
        开仓/加减仓预填价、清仓价唯一正确的价格源。

        V0.61.0 修复：此前持仓估值误用 XAU/USD（约 4349 美元/盎司）导致
        收益率高达数万个百分点，此处提供口径一致的正确价格。

        Args:
            symbol: ETF 代码，默认 518880 华安黄金ETF。

        Returns:
            GoldQuote，其中 ``price_usd`` 字段承载 **元/份**（沿用统一结构，
            调用方需按 ETF 语义解读，勿与美元金价混用）。

        Note:
            取 ETF 日 K 最后一根收盘价，与 ``get_gold_history`` 同源，
            保证估值与收益曲线口径一致；失败时降级为确定性 Mock。
        """
        cache_key = ("quote_etf", symbol)
        cached = _cache_get(cache_key, ttl=self._cache_ttl)
        if cached is not None:
            return cached

        try:
            klines = await self.get_gold_history(days=3)
            if klines:
                last = klines[-1]
                prev = klines[-2] if len(klines) >= 2 else last
                change_pct = (last.close - prev.close) / prev.close * 100 if prev.close else 0.0
                self._mark("etf", True)
                quote = GoldQuote(
                    symbol=symbol,
                    price_usd=round(last.close, 3),
                    change_pct=round(change_pct, 2),
                    updated_at=datetime.combine(
                        last.date,
                        datetime.min.time(),
                        tzinfo=timezone.utc,
                    ),
                )
                _cache_set(cache_key, quote)
                return quote
        except Exception as exc:
            logger.warning("ETF 报价取数失败: %s", exc)

        self._mark("etf", False)
        logger.warning("ETF 报价全部失败，降级 Mock")
        return GoldQuote(
            symbol=symbol,
            price_usd=9.6,
            change_pct=0.0,
            updated_at=datetime.now(timezone.utc),
        )

    async def _fetch_xau_by_token(self, token: str) -> float | None:
        """按 token 从对应源取 XAU 实时价。"""
        token = token.strip().lower()
        if token == "goldapi":
            # 直接走 goldapi（不走 fallback chain）
            url = self._settings.xau_live_api_url

            def _get() -> dict:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                with urllib.request.urlopen(req, timeout=15) as r:
                    return json.loads(r.read().decode("utf-8", "ignore"))

            try:
                raw = await asyncio.to_thread(_get)
                if isinstance(raw, dict) and raw.get("price"):
                    return float(raw["price"])
            except Exception as exc:
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
            except Exception as exc:
                logger.warning("sina hf_GC 取数失败: %s", exc)
            return None
        if token == "etf_history":
            try:
                klines = await self._bundle.history.get_history(DEFAULT_GOLD_ETF, days=3)
                if klines and len(klines) >= 2:
                    return float(klines[-1].close)
            except Exception as exc:
                logger.warning("etf_history 取数失败: %s", exc)
            return None
        logger.warning("未知 xau_fallback_chain token: %s", token)
        return None

    async def get_gold_history(self, days: int = 60) -> list[GoldKline]:
        """获取黄金 ETF 历史日 K；失败时返回确定性 Mock 序列（可离线演示）。

        V0.60.0：启用 ``_cache_get/_cache_set``。cache hit 时直接返回缓存值，
        不重写 ``_fetched_at``，使 ``source_status()`` 的 staleness 推导自然生效。
        """
        cache_key = ("etf", days)
        cached = _cache_get(cache_key, ttl=self._cache_ttl)
        if cached is not None:
            return cached
        try:
            klines = await self._bundle.history.get_history(DEFAULT_GOLD_ETF, days=days)
            if klines:
                _cache_set(cache_key, klines)
                self._mark("etf", True, last_date=klines[-1].date)
                return klines
            raise RuntimeError("empty history")
        except Exception as exc:
            logger.warning("history from provider failed (%s), fallback to mock", exc)
            self._mark("etf", False)
            return self._mock_history(days)

    async def get_gold_gram_quote(self, symbol: str = DEFAULT_GOLD_GRAM) -> GoldQuote:
        """获取黄金克价最新报价（元/克）。

        V0.60.0：启用 ``_cache_get/_cache_set``。gram quote 由日 K 推导，
        缓存 hit 时直接返回，不重写 ``_fetched_at``。
        """
        cache_key = ("quote_gram", symbol)
        cached = _cache_get(cache_key, ttl=self._cache_ttl)
        if cached is not None:
            return cached
        try:
            klines = await self.get_gold_gram_history(symbol=symbol, days=3)
            if len(klines) < 2:
                raise RuntimeError("empty gram history")
            last, prev = klines[-1], klines[-2]
            change_pct = (last.close - prev.close) / prev.close * 100 if prev.close else 0.0
            quote = GoldQuote(
                symbol=symbol,
                price_usd=round(last.close, 2),
                change_pct=round(change_pct, 2),
                updated_at=datetime.combine(last.date, datetime.min.time(), tzinfo=timezone.utc),
            )
            _cache_set(cache_key, quote)
            return quote
        except Exception as exc:
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
        """获取黄金克价历史日 K；失败降级 Mock。

        V0.60.0：启用 ``_cache_get/_cache_set``。
        """
        cache_key = ("gram", symbol, days)
        cached = _cache_get(cache_key, ttl=self._cache_ttl)
        if cached is not None:
            return cached
        try:
            klines = await self._bundle.history.get_gram_history(symbol=symbol, days=days)
            if klines:
                _cache_set(cache_key, klines)
                self._mark("sge", True, last_date=klines[-1].date)
                return klines
            raise RuntimeError("empty gram history")
        except Exception as exc:
            logger.warning("gram history failed (%s), fallback to mock", exc)
            self._mark("sge", False)
            return self._mock_gram_history(days)

    async def _sge_daily_change(self) -> float:
        """由上海金真实近两日推导涨跌幅（免费公开源）。"""
        try:
            kl = await self.get_gold_gram_history(symbol=DEFAULT_GOLD_GRAM, days=3)
            if len(kl) >= 2 and kl[-2].close:
                return round((kl[-1].close - kl[-2].close) / kl[-2].close * 100, 2)
        except Exception:
            pass
        return 0.0

    @staticmethod
    def _mock_gram_history(days: int) -> list[GoldKline]:
        """确定性 Mock 克价序列：与 ETF Mock 同走势（克价 ≈990 元）。"""
        from app.repositories.market_providers import _mock_gram_history

        return _mock_gram_history(days=days)

    async def get_us_gold_quote(self, symbol: str = DEFAULT_NY_GOLD) -> GoldQuote:
        """获取纽约金最新报价（美元/盎司）。

        V0.60.0：启用 ``_cache_get/_cache_set``。
        """
        cache_key = ("quote_ny", symbol)
        cached = _cache_get(cache_key, ttl=self._cache_ttl)
        if cached is not None:
            return cached
        # 主源：零KEY公开 XAU/USD 即期报价（与COMEX高度联动）
        change = 0.0
        with contextlib.suppress(Exception):
            change = await self._sge_daily_change()

        for token in self._xau_chain:
            price = await self._fetch_xau_by_token(token)
            if price and price > 0:
                quote = GoldQuote(
                    symbol=symbol,
                    price_usd=round(price, 2),
                    change_pct=change,
                    updated_at=datetime.now(timezone.utc),
                )
                _cache_set(cache_key, quote)
                return quote

        # 兜底：由外盘历史推导
        try:
            klines = await self.get_us_gold_history(symbol=symbol, days=3)
            if klines and len(klines) >= 2:
                last, prev = klines[-1], klines[-2]
                change_pct = (last.close - prev.close) / prev.close * 100 if prev.close else 0.0
                quote = GoldQuote(
                    symbol=symbol,
                    price_usd=round(last.close, 2),
                    change_pct=round(change_pct, 2),
                    updated_at=datetime.combine(
                        last.date, datetime.min.time(), tzinfo=timezone.utc
                    ),
                )
                _cache_set(cache_key, quote)
                return quote
        except Exception as exc:
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
        """获取纽约金历史日 K；失败降级 Mock。

        V0.60.0：启用 ``_cache_get/_cache_set``。
        """
        cache_key = ("ny", symbol, days)
        cached = _cache_get(cache_key, ttl=self._cache_ttl)
        if cached is not None:
            return cached
        try:
            klines = await self._bundle.history.get_us_gold_history(symbol=symbol, days=days)
            if klines:
                _cache_set(cache_key, klines)
                self._mark("ny", True, last_date=klines[-1].date)
                return klines
            raise RuntimeError("empty us gold history")
        except Exception as exc:
            logger.warning("us gold history failed (%s), fallback to mock", exc)
            self._mark("ny", False)
            return self._mock_us_history(days)

    async def get_us_treasury_yields(self) -> USTYield | None:
        """获取美债 10Y/30Y 收益率（美联储 H.15 官方源）；失败返回 None。

        调用方（macro 服务）应保持内置静态参考值作为降级。
        """
        try:
            result = await self._bundle.treasury.get_treasury_yields()
        except Exception as exc:
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

    # ───────────────────── V0.71.0：白银 5 个方法 ─────────────────────

    async def get_silver_etf_quote(self, symbol: str = DEFAULT_SILVER_ETF) -> SilverQuote:
        """白银 ETF（562800）最新价（人民币元/份）。

        V0.73.x+：优先尝试 ``YahooSilverHistoryProvider.get_silver_spot()``
        （最小请求 ``range=2d``，拿到今天日内增量 bar），失败再走 history 兜底。
        这样即使当日 K 线 Yahoo 已生成（盘中有 tick 更新），``updated_at`` 就是今天。
        """
        cache_key = ("quote_silver_etf", symbol)
        cached = _cache_get(cache_key, ttl=self._cache_ttl)
        if cached is not None:
            return cached
        try:
            spot = await self._try_silver_spot(symbol)
            if spot is not None:
                self._mark("silver_etf", True, last_date=spot.date)
                quote = SilverQuote(
                    symbol=symbol,
                    price_usd=round(spot.close, 3),
                    change_pct=0.0,
                    updated_at=datetime.combine(
                        spot.date, datetime.min.time(), tzinfo=timezone.utc
                    ),
                )
                _cache_set(cache_key, quote)
                return quote
            # spot 不可用 → 回退到 history（last bar 的 date 作为 updated_at）
            klines = await self.get_silver_etf_history(days=3)
            if klines:
                last = klines[-1]
                prev = klines[-2] if len(klines) >= 2 else last
                change_pct = (last.close - prev.close) / prev.close * 100 if prev.close else 0.0
                self._mark("silver_etf", True)
                quote = SilverQuote(
                    symbol=symbol,
                    price_usd=round(last.close, 3),
                    change_pct=round(change_pct, 2),
                    updated_at=datetime.combine(
                        last.date, datetime.min.time(), tzinfo=timezone.utc
                    ),
                )
                _cache_set(cache_key, quote)
                return quote
        except Exception as exc:
            logger.warning("silver ETF 报价取数失败: %s", exc)

        self._mark("silver_etf", False)
        return SilverQuote(
            symbol=symbol,
            price_usd=2.45,
            change_pct=0.0,
            updated_at=datetime.now(timezone.utc),
        )

    async def get_silver_etf_history(
        self,
        symbol: str = DEFAULT_SILVER_ETF,
        days: int = 60,
    ) -> list[SilverKline]:
        """白银 ETF（562800）历史日 K；失败时返回确定性 Mock 序列。"""
        cache_key = ("silver_etf", symbol, days)
        cached = _cache_get(cache_key, ttl=self._cache_ttl)
        if cached is not None:
            return cached
        try:
            klines = await self._bundle.silver_history.get_silver_history(symbol=symbol, days=days)
            if klines:
                silver_klines = [
                    SilverKline(
                        date=k.date,
                        open=k.open,
                        close=k.close,
                        high=k.high,
                        low=k.low,
                        volume=k.volume,
                    )
                    for k in klines
                ]
                _cache_set(cache_key, silver_klines)
                # V0.73.0 N+15：只有真实数据才标 live；mock / fallback 一律标 mock。
                ok = self._is_silver_data_real(self._bundle.silver_history)
                self._mark("silver_etf", ok, last_date=silver_klines[-1].date)
                return silver_klines
            raise RuntimeError("empty silver ETF history")
        except Exception as exc:
            logger.warning("silver ETF history failed (%s), fallback to mock", exc)
            self._mark("silver_etf", False)
            return self._mock_silver_etf_history(days=days)

    async def get_silver_ny_quote(self, symbol: str = DEFAULT_SILVER_NY) -> SilverQuote:
        """纽约白银（COMEX SI 期货主力，美元/盎司）最新报价。

        V0.73.0 N+17：按 ``settings.silver_fallback_chain`` 顺序逐源尝试：
            - ``sina_si`` → Sina hf_SI 实时（与 gold hf_GC 1:1 对称）
            - ``yahoo_spot`` → Yahoo Finance SI=F 当日 running bar（仅 Yahoo 模式有效）
            - 全部失败 → 历史 K 线最后一根（隐式兜底）
            - 最后 → Mock

        设计目标：默认 ``MARKET_PROVIDER=akshare`` 下 NY 银即可拿到实时报价
        （不再依赖 ``silver_yahoo`` 配置项）。
        """
        cache_key = ("quote_silver_ny", symbol)
        cached = _cache_get(cache_key, ttl=self._cache_ttl)
        if cached is not None:
            return cached

        # 第一段：silver_fallback_chain 逐源尝试（实时优先）
        chain = self._settings.silver_fallback_chain_list
        for token in chain:
            price = await self._fetch_silver_ny_by_token(token, symbol)
            if price and price > 0:
                self._mark("silver_ny", True)
                quote = SilverQuote(
                    symbol=symbol,
                    price_usd=round(price, 3),
                    change_pct=0.0,
                    updated_at=datetime.now(timezone.utc),
                )
                _cache_set(cache_key, quote)
                return quote

        # 第二段：历史 K 线最后一根（隐式兜底，所有 silver_history 实现都适用）
        try:
            klines = await self.get_silver_ny_history(days=3)
            if klines:
                last = klines[-1]
                prev = klines[-2] if len(klines) >= 2 else last
                change_pct = (last.close - prev.close) / prev.close * 100 if prev.close else 0.0
                self._mark("silver_ny", True, last_date=last.date)
                quote = SilverQuote(
                    symbol=symbol,
                    price_usd=round(last.close, 3),
                    change_pct=round(change_pct, 2),
                    updated_at=datetime.combine(
                        last.date, datetime.min.time(), tzinfo=timezone.utc
                    ),
                )
                _cache_set(cache_key, quote)
                return quote
        except Exception as exc:
            logger.warning("silver NY 报价历史兜底失败: %s", exc)

        # 第三段：Mock 演示兜底
        self._mark("silver_ny", False)
        return SilverQuote(
            symbol=symbol,
            price_usd=64.0,
            change_pct=0.0,
            updated_at=datetime.now(timezone.utc),
        )

    async def _fetch_silver_ny_by_token(self, token: str, symbol: str) -> float | None:
        """按 token 从对应源取白银实时价（V0.73.0 N+17 silver_fallback_chain）。

        Token:
            - ``sina_si``: Sina hf_SI 实时（通过 bundle.silver_live，akshare/mock 共用）
            - ``yahoo_spot``: Yahoo Finance SI=F 当日 running bar（仅 silver_yahoo 模式有效）
            - 其它 token / 未知 → 跳过（避免拼写错误导致静默失败）
        """
        token = token.strip().lower()
        if token == "sina_si":
            silver_live = getattr(self._bundle, "silver_live", None)
            if silver_live is None:
                logger.warning("silver_live provider 未配置，跳过 sina_si token")
                return None
            try:
                return await silver_live.get_silver_spot(symbol=symbol)
            except Exception as exc:
                logger.warning("sina_si 取数失败: %s", exc)
                return None
        if token == "yahoo_spot":
            spot = await self._try_silver_spot(symbol)
            return spot.close if spot is not None else None
        if token == "history":
            # 直接从 silver_history 拿最后一根（不走缓存层，避免递归）
            try:
                klines = await self._bundle.silver_history.get_silver_history(
                    symbol=symbol, days=3
                )
                if klines:
                    return float(klines[-1].close)
            except Exception as exc:
                logger.warning("history 取数失败: %s", exc)
            return None
        logger.warning("未知 silver_fallback_chain token: %s", token)
        return None

    async def get_silver_ny_history(
        self,
        symbol: str = DEFAULT_SILVER_NY,
        days: int = 60,
    ) -> list[SilverKline]:
        """纽约白银（COMEX SI）历史日 K；失败时返回确定性 Mock 序列。"""
        cache_key = ("silver_ny", symbol, days)
        cached = _cache_get(cache_key, ttl=self._cache_ttl)
        if cached is not None:
            return cached
        try:
            klines = await self._bundle.silver_history.get_silver_history(symbol=symbol, days=days)
            if klines:
                silver_klines = [
                    SilverKline(
                        date=k.date,
                        open=k.open,
                        close=k.close,
                        high=k.high,
                        low=k.low,
                        volume=k.volume,
                    )
                    for k in klines
                ]
                _cache_set(cache_key, silver_klines)
                # V0.73.0 N+15：只有真实数据才标 live；mock / fallback 一律标 mock。
                ok = self._is_silver_data_real(self._bundle.silver_history)
                self._mark("silver_ny", ok, last_date=silver_klines[-1].date)
                return silver_klines
            raise RuntimeError("empty silver NY history")
        except Exception as exc:
            logger.warning("silver NY history failed (%s), fallback to mock", exc)
            self._mark("silver_ny", False)
            return self._mock_silver_ny_history(days=days)

    # ───────────────────── V0.73.0 N+16：白银克价接口 ─────────────────────

    # 562800 易方达白银 ETF 单位 ≈ 1000 克白银现货（公开口径，含 0.5% 管理费）
    # → 白银克价 (CNY/g) = 562800 现价 × 1000
    # 这是国内零售白银克价最贴近的公开源，避免引入新外部数据源
    # （SGE 无 Ag99.99 标准化合约；上海有色/华通/长江白银报价均无免费 API）。
    # 偏差约 ±0.5%（ETF 申赎溢价 + 管理费），零售场景可接受。
    _SILVER_GRAM_PER_ETF_SHARE = 1000.0

    async def get_silver_gram_quote(self) -> SilverQuote | None:
        """白银克价最新报价（人民币 元/克，V0.73.0 N+16 上线）。

        计算口径：
            ``gram_price = etf_price × 1000``
        数据源：复用 ``get_silver_etf_quote()``，与白银 ETF 同数据源同时间戳，
        保证 ETF 持仓估值与克价口径严格一致。

        Returns:
            SilverQuote（symbol="Ag"，price_usd 字段承载 元/克，结构沿用统一口径）。
            任何异常降级 Mock（基于 ETF mock × 1000）。
        """
        cache_key = ("quote_silver_gram",)
        cached = _cache_get(cache_key, ttl=self._cache_ttl)
        if cached is not None:
            return cached
        try:
            etf_quote = await self.get_silver_etf_quote()
            if etf_quote is None or etf_quote.price_usd <= 0:
                raise RuntimeError("silver ETF quote unavailable")
            gram_price = round(etf_quote.price_usd * self._SILVER_GRAM_PER_ETF_SHARE, 2)
            self._mark("silver_gram", True, last_date=etf_quote.updated_at.date())
            quote = SilverQuote(
                symbol="Ag",
                price_usd=gram_price,
                change_pct=etf_quote.change_pct,
                updated_at=etf_quote.updated_at,
            )
            _cache_set(cache_key, quote)
            return quote
        except Exception as exc:
            logger.warning("silver gram quote failed (%s), fallback to mock", exc)
        self._mark("silver_gram", False)
        return SilverQuote(
            symbol="Ag",
            price_usd=2.45 * self._SILVER_GRAM_PER_ETF_SHARE,  # 2450 元/克 演示
            change_pct=0.0,
            updated_at=datetime.now(timezone.utc),
        )

    async def get_silver_gram_history(
        self,
        symbol: str = "Ag",
        days: int = 60,
    ) -> list[SilverKline]:
        """白银克价历史日 K（人民币 元/克，V0.73.0 N+16 上线）。

        计算口径：
            ``gram_kline[i] = etf_kline[i] × 1000``（按日反推）
        数据源：复用 ``get_silver_etf_history()``，与 ETF 历史同源同步。

        Args:
            symbol: 仅作语义标识（统一 SilverKline 接口），实际不影响数据源。
            days: 历史天数。

        Returns:
            list[SilverKline]（close/open/high/low 均为 元/克）。
        """
        cache_key = ("silver_gram", symbol, days)
        cached = _cache_get(cache_key, ttl=self._cache_ttl)
        if cached is not None:
            return cached
        try:
            etf_klines = await self.get_silver_etf_history(days=days)
            if not etf_klines:
                raise RuntimeError("empty silver ETF history")
            mul = self._SILVER_GRAM_PER_ETF_SHARE
            gram_klines = [
                SilverKline(
                    date=k.date,
                    open=round(k.open * mul, 2),
                    close=round(k.close * mul, 2),
                    high=round(k.high * mul, 2),
                    low=round(k.low * mul, 2),
                    volume=k.volume,
                )
                for k in etf_klines
            ]
            _cache_set(cache_key, gram_klines)
            # 继承 ETF freshness：ETF 真 → gram 真；ETF mock → gram mock
            ok = self._sources.get("silver_etf") == "live"
            self._mark("silver_gram", ok, last_date=gram_klines[-1].date)
            return gram_klines
        except Exception as exc:
            logger.warning("silver gram history failed (%s), fallback to mock", exc)
        self._mark("silver_gram", False)
        return self._mock_silver_gram_history(days=days)

    @staticmethod
    def _mock_silver_gram_history(days: int) -> list[SilverKline]:
        """确定性 Mock 白银克价序列（继承 ETF mock × 1000，约 2450 元/克）。"""
        from app.repositories.market_providers import _mock_silver_etf_history

        mul = MarketDataRepository._SILVER_GRAM_PER_ETF_SHARE
        return [
            SilverKline(
                date=k.date,
                open=round(k.open * mul, 2),
                close=round(k.close * mul, 2),
                high=round(k.high * mul, 2),
                low=round(k.low * mul, 2),
                volume=k.volume,
            )
            for k in _mock_silver_etf_history(days=days)
        ]

    @staticmethod
    def _mock_silver_etf_history(days: int) -> list[SilverKline]:
        """确定性 Mock 白银 ETF 序列（约 2.45 元/份）。"""
        from app.repositories.market_providers import _mock_silver_etf_history

        return _mock_silver_etf_history(days=days)

    @staticmethod
    def _mock_silver_ny_history(days: int) -> list[SilverKline]:
        """确定性 Mock 纽约白银序列（约 64.0 美元/盎司，V0.73.0 N+15 随现实上调）。"""
        from app.repositories.market_providers import _mock_silver_ny_history

        return _mock_silver_ny_history(days=days)
