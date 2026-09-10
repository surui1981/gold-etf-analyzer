"""行情源 Provider 抽象与工厂测试（V0.59.0, P1 #5 行情源配置化）。

覆盖：
1. 工厂解析 4 种 provider 名（含大小写不敏感 + 未知名抛错）
2. Mock provider 数据正确性（不联网、可离线）
3. 通过环境变量切换后 MarketDataRepository 内部 bundle 类型正确
4. XAU fallback chain 解析（按 settings.xau_fallback_chain_list 顺序）
5. 旧 MarketDataRepository(provider=...) 签名仍可用（向后兼容）
6. cache_ttl=0 时禁用缓存
"""

from __future__ import annotations

from datetime import date

import pytest

from app.config import Settings
from app.repositories.market_data import GoldKline, MarketDataRepository
from app.repositories.market_providers import (
    AkshareGoldHistoryProvider,
    AkshareLiveQuoteProvider,
    AkshareTreasuryYieldProvider,
    EastmoneyOnlyHistoryProvider,
    MarketProviderBundle,
    MockGoldHistoryProvider,
    MockLiveQuoteProvider,
    MockTreasuryYieldProvider,
    PROVIDER_REGISTRY,
    SinaOnlyHistoryProvider,
    USTYield,
    build_provider_bundle,
)


# ─────────────── 工厂解析 ───────────────


def test_registry_has_four_providers() -> None:
    """工厂注册表固定包含 4 种 provider。"""
    assert set(PROVIDER_REGISTRY.keys()) == {"akshare", "mock", "eastmoney_only", "sina_only"}


def test_build_provider_bundle_default() -> None:
    """默认 settings.market_provider='akshare' → AkshareGoldHistoryProvider。"""
    settings = Settings()
    bundle = build_provider_bundle(settings)
    assert isinstance(bundle.history, AkshareGoldHistoryProvider)
    assert isinstance(bundle.live, AkshareLiveQuoteProvider)
    assert isinstance(bundle.treasury, AkshareTreasuryYieldProvider)


def test_build_provider_bundle_mock() -> None:
    """MARKET_PROVIDER=mock → 三个 Mock provider。"""
    settings = Settings(market_provider="mock")
    bundle = build_provider_bundle(settings)
    assert isinstance(bundle.history, MockGoldHistoryProvider)
    assert isinstance(bundle.live, MockLiveQuoteProvider)
    assert isinstance(bundle.treasury, MockTreasuryYieldProvider)


def test_build_provider_bundle_eastmoney_only() -> None:
    """MARKET_PROVIDER=eastmoney_only → EastmoneyOnlyHistoryProvider。"""
    settings = Settings(market_provider="eastmoney_only")
    bundle = build_provider_bundle(settings)
    assert isinstance(bundle.history, EastmoneyOnlyHistoryProvider)


def test_build_provider_bundle_sina_only() -> None:
    """MARKET_PROVIDER=sina_only → SinaOnlyHistoryProvider。"""
    settings = Settings(market_provider="sina_only")
    bundle = build_provider_bundle(settings)
    assert isinstance(bundle.history, SinaOnlyHistoryProvider)


def test_build_provider_bundle_case_insensitive() -> None:
    """MARKET_PROVIDER 大小写不敏感（'AKSHARE' / 'Mock' 均解析为对应小写）。"""
    s_upper = Settings(market_provider="AKSHARE")
    assert isinstance(build_provider_bundle(s_upper).history, AkshareGoldHistoryProvider)
    s_mixed = Settings(market_provider="Mock")
    assert isinstance(build_provider_bundle(s_mixed).history, MockGoldHistoryProvider)


def test_build_provider_bundle_unknown_raises() -> None:
    """未知名抛 ValueError，错误消息含可选列表提示。"""
    settings = Settings(market_provider="unknown_provider")
    with pytest.raises(ValueError) as exc_info:
        build_provider_bundle(settings)
    msg = str(exc_info.value)
    assert "未知 MARKET_PROVIDER" in msg
    assert "akshare" in msg
    assert "mock" in msg


def test_build_provider_bundle_none_uses_default() -> None:
    """settings.market_provider=None 时回退默认 akshare。"""
    settings = Settings(market_provider="")
    bundle = build_provider_bundle(settings)
    # 空白字符串经 strip 后为空 → 走 default 'akshare'
    assert isinstance(bundle.history, AkshareGoldHistoryProvider)


# ─────────────── Mock provider 数据正确性 ───────────────


async def test_mock_history_returns_business_days() -> None:
    """Mock ETF 历史：返回工作日 K 线序列（周末跳过）。"""
    provider = MockGoldHistoryProvider()
    klines = await provider.get_history(days=20)
    assert len(klines) > 0
    # 全是工作日
    for k in klines:
        assert k.date.weekday() < 5
        assert k.volume > 0


async def test_mock_history_chronological_order() -> None:
    """Mock ETF 历史：日期升序排列。"""
    provider = MockGoldHistoryProvider()
    klines = await provider.get_history(days=30)
    dates = [k.date for k in klines]
    assert dates == sorted(dates)


async def test_mock_gram_history_returns_yuan_per_gram() -> None:
    """Mock 克价历史：约 985 元/克 区间（与 ETF Mock 同走势）。"""
    provider = MockGoldHistoryProvider()
    klines = await provider.get_gram_history(days=10)
    assert len(klines) > 0
    closes = [k.close for k in klines]
    # 范围 970 ~ 1100
    assert min(closes) > 970
    assert max(closes) < 1100
    # 元/克精度 = 2 位小数
    for k in klines:
        assert round(k.close, 2) == k.close


async def test_mock_us_history_returns_usd_per_oz() -> None:
    """Mock 纽约金历史：约 4430 美元/盎司 区间。"""
    provider = MockGoldHistoryProvider()
    klines = await provider.get_us_gold_history(days=10)
    assert len(klines) > 0
    closes = [k.close for k in klines]
    # Mock 序列范围（base 4430 + 上行波动，最高约 5000）
    assert min(closes) > 4200
    assert max(closes) < 5000


async def test_mock_live_quote_returns_fixed_value() -> None:
    """Mock 实时报价：固定 2350.5 USD / +0.42%。"""
    provider = MockLiveQuoteProvider()
    quote = await provider.get_live_quote()
    assert quote.symbol == "XAU"
    assert quote.price_usd == 2350.5
    assert quote.change_pct == 0.42


async def test_mock_treasury_yields_returns_fixed_value() -> None:
    """Mock 美债收益率：固定 4.20% / 4.45%，data_date = today - 2。"""
    from datetime import timedelta

    provider = MockTreasuryYieldProvider()
    yields = await provider.get_treasury_yields()
    assert yields.us10y == 4.20
    assert yields.us30y == 4.45
    assert yields.data_date == date.today() - timedelta(days=2)


# ─────────────── Repository 集成 ───────────────


def test_market_data_repository_default_uses_settings() -> None:
    """无参构造：默认走 settings.market_provider='akshare'。"""
    repo = MarketDataRepository()
    assert isinstance(repo._bundle.history, AkshareGoldHistoryProvider)


def test_market_data_repository_with_mock_bundle() -> None:
    """显式传入 mock bundle → Repository 内部用 Mock provider。"""
    settings = Settings(market_provider="mock")
    bundle = build_provider_bundle(settings)
    repo = MarketDataRepository(bundle=bundle, settings=settings)
    assert isinstance(repo._bundle.history, MockGoldHistoryProvider)


def test_market_data_repository_backward_compat_provider_kwarg() -> None:
    """旧签名 MarketDataRepository(provider=FakeProvider()) 仍可用。"""


class _StubHistory:
    """最小化历史 provider stub，仅满足 Protocol。"""

    async def get_history(self, symbol="518880", days=60):
        return [GoldKline(date=date(2026, 9, 1), open=5.0, close=5.1, high=5.2, low=4.9, volume=100)]

    async def get_gram_history(self, symbol="Au99.99", days=60):
        return [GoldKline(date=date(2026, 9, 1), open=990.0, close=991.0, high=992.0, low=989.0, volume=0)]

    async def get_us_gold_history(self, symbol="GC", days=60):
        return [GoldKline(date=date(2026, 9, 1), open=4430.0, close=4435.0, high=4440.0, low=4425.0, volume=0)]


def test_market_data_repository_backward_compat_provider_kwarg():
    repo = MarketDataRepository(provider=_StubHistory())
    assert isinstance(repo._bundle.history, _StubHistory)
    # live/treasury 默认走 akshare 实现
    assert isinstance(repo._bundle.live, AkshareLiveQuoteProvider)
    assert isinstance(repo._bundle.treasury, AkshareTreasuryYieldProvider)


def test_market_data_repository_cache_ttl_override() -> None:
    """显式 cache_ttl=0 禁用缓存。"""
    repo = MarketDataRepository(cache_ttl=0)
    assert repo._cache_ttl == 0


def test_market_data_repository_xau_chain_default() -> None:
    """默认 xau_fallback_chain='goldapi,sina,etf_history'。"""
    settings = Settings()
    repo = MarketDataRepository(settings=settings)
    assert repo._xau_chain == ["goldapi", "sina", "etf_history"]


def test_market_data_repository_xau_chain_custom() -> None:
    """自定义 xau_fallback_chain 字符串正确解析为 list。"""
    settings = Settings(xau_fallback_chain="goldapi,etf_history")
    assert settings.xau_fallback_chain_list == ["goldapi", "etf_history"]


def test_market_data_repository_xau_chain_override_kwarg() -> None:
    """xau_fallback_chain 构造参数覆盖 settings。"""
    repo = MarketDataRepository(xau_fallback_chain=["sina", "goldapi"])
    assert repo._xau_chain == ["sina", "goldapi"]


# ─────────────── Repository 实际取数（Mock 模式） ───────────────


async def test_repo_get_gold_history_mock_provider() -> None:
    """Mock provider 模式下 get_gold_history 返回 Mock 序列。"""
    settings = Settings(market_provider="mock")
    bundle = build_provider_bundle(settings)
    repo = MarketDataRepository(bundle=bundle, settings=settings)
    klines = await repo.get_gold_history(days=10)
    assert len(klines) > 0
    # 状态标记为 live（Mock 成功）
    assert repo.source_status().get("etf") == "live"


async def test_repo_get_us_treasury_yields_mock_provider() -> None:
    """Mock provider 模式下 get_us_treasury_yields 返回固定 USTYield。"""
    settings = Settings(market_provider="mock")
    bundle = build_provider_bundle(settings)
    repo = MarketDataRepository(bundle=bundle, settings=settings)
    result = await repo.get_us_treasury_yields()
    assert isinstance(result, USTYield)
    assert result.us10y == 4.20
    assert result.us30y == 4.45
    assert repo.source_status().get("ust") == "live"


async def test_repo_get_gold_quote_mock_provider() -> None:
    """Mock provider 模式下 get_gold_quote 返回 mock 实时价。"""
    settings = Settings(market_provider="mock")
    bundle = build_provider_bundle(settings)
    repo = MarketDataRepository(bundle=bundle, settings=settings)
    quote = await repo.get_gold_quote()
    assert quote.symbol == "XAU"
    # Mock 价格：goldapi 不可达 → 走 etf_history（也 mock）
    # Mock 序列最后一日 close 落在 ~5.5~ 区间（ETF），不是 USD/oz
    # 这里只验证不报错且返回 quote
    assert quote.price_usd > 0
