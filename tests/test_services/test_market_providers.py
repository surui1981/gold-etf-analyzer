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
    PROVIDER_REGISTRY,
    AkshareGoldHistoryProvider,
    AkshareLiveQuoteProvider,
    AkshareTreasuryYieldProvider,
    EastmoneyOnlyHistoryProvider,
    MockGoldHistoryProvider,
    MockLiveQuoteProvider,
    MockTreasuryYieldProvider,
    SinaOnlyHistoryProvider,
    USTYield,
    build_provider_bundle,
)

# ─────────────── 工厂解析 ───────────────


def test_registry_has_six_providers() -> None:
    """工厂注册表固定包含 6 种 provider（V0.71.0 增加 silver_mock / silver_akshare）。"""
    assert set(PROVIDER_REGISTRY.keys()) == {
        "akshare",
        "mock",
        "eastmoney_only",
        "sina_only",
        "silver_mock",
        "silver_akshare",
    }


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


class _StubHistory:
    """最小化历史 provider stub，仅满足 Protocol。"""

    async def get_history(self, symbol="518880", days=60):
        return [
            GoldKline(date=date(2026, 9, 1), open=5.0, close=5.1, high=5.2, low=4.9, volume=100)
        ]

    async def get_gram_history(self, symbol="Au99.99", days=60):
        return [
            GoldKline(
                date=date(2026, 9, 1), open=990.0, close=991.0, high=992.0, low=989.0, volume=0
            )
        ]

    async def get_us_gold_history(self, symbol="GC", days=60):
        return [
            GoldKline(
                date=date(2026, 9, 1), open=4430.0, close=4435.0, high=4440.0, low=4425.0, volume=0
            )
        ]


def test_market_data_repository_backward_compat_provider_kwarg() -> None:
    """旧签名 MarketDataRepository(provider=FakeProvider()) 仍可用。

    历史问题：该用例曾被 ``_StubHistory`` 类定义从中间截断，函数体只剩
    docstring，随后又被同名函数覆盖 → 等价于从未真正断言。此处已合并修正。
    """
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


# ────────────────── V0.60.0：行情缓存启用验证 ──────────────────


async def test_v060_cache_hit_returns_same_list_instance() -> None:
    """V0.60.0：第二次同 days 命中缓存，返回完全相同的 list 实例（不走 provider）。"""
    from unittest.mock import MagicMock

    call_count = MagicMock()

    class CountingProvider:
        async def get_history(self, symbol, days=60):
            call_count()
            return [
                GoldKline(
                    date=date(2026, 9, 1), open=5.0, close=5.1, high=5.2, low=4.9, volume=100.0
                )
            ]

        async def get_gram_history(self, symbol="Au99.99", days=60):
            call_count()
            return []

        async def get_us_gold_history(self, symbol="GC", days=60):
            call_count()
            return []

    repo = MarketDataRepository(provider=CountingProvider())
    h1 = await repo.get_gold_history(days=10)
    h2 = await repo.get_gold_history(days=10)
    assert h1 is h2, "cache hit should return the same list instance"
    assert call_count.call_count == 1, f"provider called {call_count.call_count} times, expected 1"


async def test_v060_cache_disabled_when_ttl_zero() -> None:
    """V0.60.0：cache_ttl=0 时完全禁用缓存，每次调用都走 provider。"""
    from unittest.mock import MagicMock

    call_count = MagicMock()

    class CountingProvider:
        async def get_history(self, symbol, days=60):
            call_count()
            return [
                GoldKline(
                    date=date(2026, 9, 1), open=5.0, close=5.1, high=5.2, low=4.9, volume=100.0
                )
            ]

        async def get_gram_history(self, symbol="Au99.99", days=60):
            return []

        async def get_us_gold_history(self, symbol="GC", days=60):
            return []

    repo = MarketDataRepository(provider=CountingProvider(), cache_ttl=0)
    await repo.get_gold_history(days=10)
    await repo.get_gold_history(days=10)
    assert call_count.call_count == 2, "cache_ttl=0 should bypass cache"


async def test_v060_cache_keys_isolated_by_tuple() -> None:
    """V0.60.0：不同 cache key（days 不同 / etf vs gram）互不干扰。"""

    class SimpleProvider:
        async def get_history(self, symbol, days=60):
            return [
                GoldKline(
                    date=date(2026, 9, 1),
                    open=5.0,
                    close=float(days),
                    high=5.2,
                    low=4.9,
                    volume=100.0,
                )
            ]

        async def get_gram_history(self, symbol="Au99.99", days=60):
            return [
                GoldKline(
                    date=date(2026, 9, 1),
                    open=9.0,
                    close=float(days) + 1000.0,
                    high=9.2,
                    low=8.9,
                    volume=100.0,
                )
            ]

        async def get_us_gold_history(self, symbol="GC", days=60):
            return [
                GoldKline(
                    date=date(2026, 9, 1),
                    open=4.0,
                    close=float(days) + 2000.0,
                    high=4.2,
                    low=3.9,
                    volume=100.0,
                )
            ]

    repo = MarketDataRepository(provider=SimpleProvider())
    etf_10 = await repo.get_gold_history(days=10)
    etf_60 = await repo.get_gold_history(days=60)
    gram_10 = await repo.get_gold_gram_history(days=10)
    ny_10 = await repo.get_us_gold_history(days=10)
    assert etf_10[0].close == 10.0
    assert etf_60[0].close == 60.0
    assert gram_10[0].close == 1010.0
    assert ny_10[0].close == 2010.0


async def test_v060_source_status_promotes_to_stale_after_ttl() -> None:
    """V0.60.0：``source_status()`` 按 ``_fetched_at + cache_ttl`` 派生 ``"stale"``。"""
    from datetime import datetime, timedelta, timezone

    class SimpleProvider:
        async def get_history(self, symbol, days=60):
            return [
                GoldKline(
                    date=date(2026, 9, 1), open=5.0, close=5.1, high=5.2, low=4.9, volume=100.0
                )
            ]

        async def get_gram_history(self, symbol="Au99.99", days=60):
            return []

        async def get_us_gold_history(self, symbol="GC", days=60):
            return []

    repo = MarketDataRepository(provider=SimpleProvider(), cache_ttl=600)
    await repo.get_gold_history(days=10)
    assert repo.source_status()["etf"] == "live"

    # 手动把 _fetched_at 倒回 700 秒前（超 TTL=600）
    repo._fetched_at["etf"] = datetime.now(timezone.utc) - timedelta(seconds=700)
    assert repo.source_status()["etf"] == "stale"


async def test_v060_source_status_keeps_mock_label() -> None:
    """V0.60.0：``"mock"`` 永远不会被推导为 ``"stale"``，永远保留原值。"""
    from datetime import datetime, timedelta, timezone

    class FailingProvider:
        async def get_history(self, symbol, days=60):
            raise RuntimeError("fail")

        async def get_gram_history(self, symbol="Au99.99", days=60):
            return []

        async def get_us_gold_history(self, symbol="GC", days=60):
            return []

    repo = MarketDataRepository(provider=FailingProvider(), cache_ttl=600)
    await repo.get_gold_history(days=10)
    assert repo.source_status()["etf"] == "mock"
    repo._fetched_at["etf"] = datetime.now(timezone.utc) - timedelta(seconds=10000)
    assert repo.source_status()["etf"] == "mock", "mock must not be promoted to stale"


# ─────────────── V0.71.0：白银 Provider 测试 ───────────────


async def test_mock_silver_history_etf_returns_deterministic() -> None:
    """MockSilverHistoryProvider(symbol="562800") 返回 60 根 ETF K 线（约 2.45 元/份 起步）。"""
    from app.repositories.market_providers import MockSilverHistoryProvider

    provider = MockSilverHistoryProvider()
    klines = await provider.get_silver_history(symbol="562800", days=60)
    assert 40 <= len(klines) <= 60, f"工作日过滤后应返回 ~40-60 根，实际 {len(klines)}"
    assert all(k.close > 0 for k in klines)
    # 起点价位在 2.4 元附近（base * (1+0) = 2.45）
    assert 2.0 <= klines[0].close <= 3.0


async def test_mock_silver_history_ny_returns_dollar_prices() -> None:
    """MockSilverHistoryProvider(symbol='SI') 返回 60 根 NY K 线（约 31.5 美元/盎司 起步）。"""
    from app.repositories.market_providers import MockSilverHistoryProvider

    provider = MockSilverHistoryProvider()
    klines = await provider.get_silver_history(symbol="SI", days=60)
    assert 40 <= len(klines) <= 60
    assert all(k.close > 0 for k in klines)
    # NY 价位 ~31.5 美元
    assert 28.0 <= klines[0].close <= 36.0


async def test_silver_akshare_provider_raises_not_implemented() -> None:
    """AkshareSilverHistoryProvider 是 V0.71.0 占位 stub：立即抛 NotImplementedError。"""
    from app.repositories.market_providers import AkshareSilverHistoryProvider

    provider = AkshareSilverHistoryProvider()
    with pytest.raises(NotImplementedError) as exc_info:
        await provider.get_silver_history(symbol="562800", days=60)
    assert "V0.72+" in str(exc_info.value)


def test_build_provider_bundle_silver_mock_resolves() -> None:
    """MARKET_PROVIDER=silver_mock → silver_history 为 MockSilverHistoryProvider。"""
    from app.repositories.market_providers import MockSilverHistoryProvider

    settings = Settings(market_provider="silver_mock")
    bundle = build_provider_bundle(settings)
    assert isinstance(bundle.silver_history, MockSilverHistoryProvider)


def test_build_provider_bundle_silver_akshare_resolves() -> None:
    """MARKET_PROVIDER=silver_akshare → silver_history 为 AkshareSilverHistoryProvider。"""
    from app.repositories.market_providers import AkshareSilverHistoryProvider

    settings = Settings(market_provider="silver_akshare")
    bundle = build_provider_bundle(settings)
    assert isinstance(bundle.silver_history, AkshareSilverHistoryProvider)


def test_silver_history_provider_present_in_all_bundles() -> None:
    """所有 6 种 provider 的 bundle 都包含 silver_history（V0.71.0 必填字段）。"""
    from app.repositories.market_providers import (
        AkshareSilverHistoryProvider,
        MockSilverHistoryProvider,
    )

    expected_silver: dict[str, type] = {
        "akshare": AkshareSilverHistoryProvider,
        "eastmoney_only": AkshareSilverHistoryProvider,
        "sina_only": AkshareSilverHistoryProvider,
        "mock": MockSilverHistoryProvider,
        "silver_mock": MockSilverHistoryProvider,
        "silver_akshare": AkshareSilverHistoryProvider,
    }
    for name, expected_cls in expected_silver.items():
        settings = Settings(market_provider=name)
        bundle = build_provider_bundle(settings)
        assert bundle.silver_history is not None, f"{name} 应有 silver_history"
        assert isinstance(bundle.silver_history, expected_cls), (
            f"{name} 应使用 {expected_cls.__name__}，实际 {type(bundle.silver_history).__name__}"
        )
