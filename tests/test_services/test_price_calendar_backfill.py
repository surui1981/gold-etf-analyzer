"""价格日历按需自动回填（V0.79.0 · 任务 #161）。

背景
----
``gold_price_daily`` 原先只有一条写入路径：用户在 ``/review`` 页手工点「价格回填」。
而回测、复盘、校准曲线**都依赖它** ⇒ 未回填时三者静默返回假结果
（已在 ``04b5fd4`` 让回测显式标记 ``usable=False``）。

本文件锁死自动回填的**三条不可退让约束**：

1. **只接受真实数据源** —— ``TrendService`` 取数失败会静默降级为 ``mock``，
   mock 收盘价入库 ⇒ 回测基于**编造的价格**给出看似正常的 Sharpe，比无数据更危险；
2. **失败不抛异常** —— 回填是增强而非前置条件，失败只如实反映在 ``coverage`` 上；
3. **不覆盖已有数据** —— ``force=False`` 时仅在区间完全无数据时才回填。
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest

from app.services.backtest import BacktestService
from app.services.price_source import _TARGET_TO_MARKET_KEY, resolve_price_source
from app.services.price_source import (
    TRUSTED_PRICE_SOURCES as _TRUSTED_PRICE_SOURCES,
)
from app.services.settings import WeightService

# ─────────────── 桩 ───────────────


class _Pt:
    """**行情点**替身（``TrendOut.points`` 的元素）—— 属性是 ``.date``。"""

    __slots__ = ("close", "date")

    def __init__(self, d: date, close: float) -> None:
        self.date = d
        self.close = close


class _PriceRow:
    """**价格日历行**替身（``GoldPriceDaily``）—— ⚠ 属性是 ``.price_date``，不是 ``.date``。

    ⚠⚠ 2026-10-06 第二次踩「桩不同构」：先复用了 ``_Pt``，而
    ``list_range()`` 返回的是 ``GoldPriceDaily``（``.price_date`` / ``.close``），
    与 ``TrendOut.points``（``.date`` / ``.close``）**是两个不同模型**。
    ⇒ 4 个用例报 ``AttributeError: _Pt has no attribute 'price_date'``。
    **教训：桩必须按「被调方法的返回模型」分类型，不能因字段名相近就复用。**
    """

    __slots__ = ("close", "price_date")

    def __init__(self, price_date: date, close: float) -> None:
        self.price_date = price_date
        self.close = close


class _FakeTrendOut:
    def __init__(self, points: list[_Pt], data_sources: dict[str, str]) -> None:
        self.points = points
        self.data_sources = data_sources


class _FakeTrend:
    """TrendService 替身：可编排「取数成功 / 抛异常 / 降级为 mock」三种结局。"""

    def __init__(self, *, source: str = "live", n: int = 30, raise_exc: bool = False) -> None:
        self.source = source
        self.n = n
        self.raise_exc = raise_exc
        self.calls = 0

    async def analyze(self, days: int = 60, target: str = "etf") -> _FakeTrendOut:
        self.calls += 1
        if self.raise_exc:
            raise RuntimeError("provider down")
        last = date(2026, 10, 6)
        pts = [_Pt(last - timedelta(days=i), 10.0 + i * 0.1) for i in range(self.n)]
        return _FakeTrendOut(points=pts, data_sources={target: self.source})


class _FakeGold:
    """GoldPriceRepository 替身：记录写入调用。"""

    def __init__(self, existing: list[tuple[date, float]] | None = None) -> None:
        self._existing = existing or []
        self.upsert_calls: list[dict] = []

    async def list_range(self, target: str, *, start: date, end: date, limit=None):
        # ⚠ 返回 GoldPriceDaily 替身（.price_date），不是行情点（.date）
        return [_PriceRow(d, c) for d, c in self._existing if start <= d <= end]

    async def upsert_many(self, *, target: str, bars, source: str) -> int:
        self.upsert_calls.append({"target": target, "bars": list(bars), "source": source})
        return len(bars)


class _FakeSession:
    async def execute(self, stmt):
        class _Result:
            def scalars(self_inner):
                class _Scalars:
                    def all(self_inner_inner):
                        return []

                return _Scalars()

            def scalar(self_inner):
                return 0

        return _Result()


def _svc(gold: _FakeGold, trend: _FakeTrend | None) -> BacktestService:
    return BacktestService(
        session=_FakeSession(),  # type: ignore[arg-type]
        gold=gold,  # type: ignore[arg-type]
        weights=WeightService(None),  # type: ignore[arg-type]
        trend=trend,  # type: ignore[arg-type]
    )


# ─────────────── 约束 1：绝不写入 mock ───────────────


def test_mock_source_is_never_written() -> None:
    """★ 数据源降级为 mock ⇒ 拒绝写入（防编造价格污染回测）。"""
    gold = _FakeGold()
    trend = _FakeTrend(source="mock")
    svc = _svc(gold, trend)

    ok, why = asyncio.run(svc.ensure_price_calendar("etf"))

    assert ok is False
    assert gold.upsert_calls == [], "mock 数据绝不能进库"
    assert "mock" in why


def test_unknown_source_is_never_written() -> None:
    """数据源标识缺失/未知 ⇒ 同样拒绝。"""
    gold = _FakeGold()
    trend = _FakeTrend(source="")
    svc = _svc(gold, trend)

    ok, _ = asyncio.run(svc.ensure_price_calendar("etf"))

    assert ok is False
    assert gold.upsert_calls == []


def test_trusted_sources_excludes_mock() -> None:
    """白名单本身锁死：``mock`` 不得出现（防后续误加）。"""
    assert "mock" not in _TRUSTED_PRICE_SOURCES
    assert {"live", "stale"} <= _TRUSTED_PRICE_SOURCES


@pytest.mark.parametrize("source", ["live", "stale"])
def test_trusted_sources_are_written(source: str) -> None:
    """真实数据源正常写入。"""
    gold = _FakeGold()
    svc = _svc(gold, _FakeTrend(source=source))

    ok, why = asyncio.run(svc.ensure_price_calendar("etf"))

    assert ok is True
    assert len(gold.upsert_calls) == 1
    assert gold.upsert_calls[0]["source"] == source
    assert "已回填" in why


# ─────────────── 约束 2：失败不抛异常 ───────────────


def test_provider_exception_is_swallowed() -> None:
    """取数抛异常 ⇒ 返回「未写入」而非上抛（增强失败不该让回测 500）。"""
    gold = _FakeGold()
    svc = _svc(gold, _FakeTrend(raise_exc=True))

    ok, why = asyncio.run(svc.ensure_price_calendar("etf"))

    assert ok is False
    assert "取数失败" in why
    assert gold.upsert_calls == []


def test_missing_trend_dependency_is_reported_not_raised() -> None:
    """未注入趋势服务 ⇒ 明确报告，仍不抛异常。"""
    gold = _FakeGold()
    svc = _svc(gold, None)

    ok, why = asyncio.run(svc.ensure_price_calendar("etf"))

    assert ok is False
    assert "未注入" in why


def test_empty_points_is_not_written() -> None:
    """取数返回空 ⇒ 不写入（避免用空批覆盖既有数据）。"""
    gold = _FakeGold()
    trend = _FakeTrend(n=0)
    svc = _svc(gold, trend)

    ok, why = asyncio.run(svc.ensure_price_calendar("etf"))

    assert ok is False
    assert "空" in why
    assert gold.upsert_calls == []


# ─────────────── 约束 3：不覆盖已有数据 ───────────────


def test_existing_calendar_skips_backfill() -> None:
    """★ 已有数据 ⇒ 跳过（不重复打数据源）。"""
    gold = _FakeGold(existing=[(date(2026, 9, 1), 9.9)])
    trend = _FakeTrend()
    svc = _svc(gold, trend)

    ok, why = asyncio.run(svc.ensure_price_calendar("etf"))

    assert ok is False
    assert trend.calls == 0, "已有数据时不应调用趋势服务"
    assert gold.upsert_calls == []
    assert "已有数据" in why


def test_force_backfills_despite_existing() -> None:
    """``force=True`` ⇒ 强制回填（用户显式要求刷新）。"""
    gold = _FakeGold(existing=[(date(2026, 9, 1), 9.9)])
    trend = _FakeTrend()
    svc = _svc(gold, trend)

    ok, _ = asyncio.run(svc.ensure_price_calendar("etf", force=True))

    assert ok is True
    assert trend.calls == 1
    assert len(gold.upsert_calls) == 1


# ─────────────── 幂等 / 边界 ───────────────


def test_backfill_is_idempotent_across_calls() -> None:
    """连续两次：第一次写入，第二次因已有数据而跳过。"""
    gold = _FakeGold()
    svc = _svc(gold, _FakeTrend())

    first_ok, _ = asyncio.run(svc.ensure_price_calendar("etf"))
    # 模拟首次写入已落库
    gold._existing = [(date(2026, 9, 1), 9.9)]
    second_ok, second_why = asyncio.run(svc.ensure_price_calendar("etf"))

    assert first_ok is True
    assert second_ok is False
    assert "已有数据" in second_why


def test_existing_span_reports_bounds() -> None:
    """区间跨度查询返回最早 / 最晚日期。"""
    gold = _FakeGold(existing=[(date(2026, 9, 1), 9.9), (date(2026, 9, 5), 10.1)])
    svc = _svc(gold, None)

    start, end = asyncio.run(svc._existing_calendar_span("etf"))

    assert start == date(2026, 9, 1)
    assert end == date(2026, 9, 5)


def test_empty_calendar_span_is_none() -> None:
    """空表 ⇒ ``(None, None)``。"""
    svc = _svc(_FakeGold(), None)

    assert asyncio.run(svc._existing_calendar_span("etf")) == (None, None)


def test_backtest_service_still_constructs_without_trend() -> None:
    """⚠ 向后兼容：不传 trend 也能构造（老调用方不会 TypeError）。"""
    svc = BacktestService(
        session=_FakeSession(),  # type: ignore[arg-type]
        gold=_FakeGold(),  # type: ignore[arg-type]
        weights=WeightService(None),  # type: ignore[arg-type]
    )
    assert svc is not None


def test_gold_price_repository_accepts_trusted_sources() -> None:
    """⚠⚠ 两个白名单必须**严格相容**：回填层放行的 source，仓储层必须接受。

    2026-10-06 亲踩：回填层放行了 ``stale``，而仓储 ``_VALID_SOURCES`` 不含它
    ⇒ 自动回填必然被仓储拒绝并抛 400，把「增强」变成「回测不可用」。

    ⚠ 断言**不可写成** ``_TRUSTED <= _VALID | {"stale"}`` —— 那样恰好掩盖了本缺陷。
    """
    from app.repositories.review import _VALID_SOURCES

    assert set(_VALID_SOURCES) >= _TRUSTED_PRICE_SOURCES, (
        f"回填白名单 {sorted(_TRUSTED_PRICE_SOURCES)} 有仓储不接受的 source："
        f"{sorted(_TRUSTED_PRICE_SOURCES - set(_VALID_SOURCES))}"
    )
    # 且两者都不含 mock
    assert "mock" not in _VALID_SOURCES


# ─────────────── 来源解析：target ≠ 市场 key（2026-10-06 实测踩坑）───────────────


def test_gram_source_resolved_via_market_key() -> None:
    """★ ``target='gram'`` 的来源在 ``data_sources['sge']``，不在 ``['gram']``。

    实测：直接 ``data_sources.get(target)`` 返回空串 ⇒ 在「数据其实是真的」
    时误判为不可信 ⇒ 自动回填被无谓跳过。
    """
    assert resolve_price_source({"sge": "live"}, "gram") == "live"
    assert resolve_price_source({"etf": "live"}, "etf") == "live"
    assert resolve_price_source({"ny": "stale"}, "ny") == "stale"


def test_resolve_source_returns_empty_not_live_on_missing() -> None:
    """⚠ 缺失时必须返回空串（由白名单拒绝），**不可**兜底成 ``live``。

    ``review.backfill()`` 用的是 ``or 'live'`` —— 方向相反且更危险：
    把「未知来源」标成真实，等于静默宣称数据可信。
    """
    assert resolve_price_source(None, "etf") == ""
    assert resolve_price_source({}, "gram") == ""
    assert resolve_price_source({"sge": "live"}, "etf") == ""


def test_resolve_source_passes_through_mock_for_rejection() -> None:
    """``mock`` 必须被如实读出（好让白名单拒绝它），不得被兜底成 live。"""
    assert resolve_price_source({"sge": "mock"}, "gram") == "mock"
    assert resolve_price_source({"etf": "mock"}, "etf") == "mock"


def test_market_key_mapping_stays_consistent_with_trend() -> None:
    """⚠ 本模块的映射必须覆盖 ``trend._FRESHNESS_KEYS`` 的全部 target。

    两处各自声明（刻意不复用私有名）；若 trend 侧新增标的而此处漏了，
    自动回填会**静默失效** ⇒ 用测试锁住一致性。
    """
    from app.services.trend import _FRESHNESS_KEYS

    missing = set(_FRESHNESS_KEYS) - set(_TARGET_TO_MARKET_KEY)
    assert not missing, f"trend 侧新增了标的但回填映射未覆盖：{sorted(missing)}"
    # 且每个映射的第一候选键应与 trend 侧一致（首个即主市场键）
    for target, market_key in _FRESHNESS_KEYS.items():
        assert _TARGET_TO_MARKET_KEY[target][0] == market_key, (
            f"{target} 的主市场键应与 trend 一致："
            f"{_TARGET_TO_MARKET_KEY[target][0]} != {market_key}"
        )


def test_all_mapping_targets_have_entries() -> None:
    """映射表不得含空元组（否则永远解析不到来源）。"""
    empty = [t for t, keys in _TARGET_TO_MARKET_KEY.items() if not keys]
    assert not empty, f"这些 target 的映射为空元组：{empty}"
