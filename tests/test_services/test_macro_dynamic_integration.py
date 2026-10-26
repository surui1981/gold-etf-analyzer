"""V0.79.0 Step E · Commit 2：MacroFactorService 注入 calculator 集成测试。

覆盖：
- 不注入 calculator → 全 hardcode（向后兼容，test_macro_service.py 已覆盖）
- 注入 calculator + 种 252 日 dxy/us10y/us30y/vix → 阈值切到 percentile
- cb_gold 即使种 252 日 → 仍走 hardcode
- 数据不足场景（< 60 样本）→ 单因子回退
- 注入 calculator 但表完全空 → 整体回退 hardcode，macro_dynamic=False
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.repositories.db import async_session_factory
from app.repositories.macro_factor_history import MacroFactorHistoryRepository
from app.services.macro import MacroFactorService
from app.services.macro_thresholds import MacroThresholdCalculator

# V0.118.0：8 因子后 hardcode 兜底值全部改了
HARDCODE_DXY = (94.0, 107.0)
HARDCODE_US2Y = (3.0, 5.0)
HARDCODE_US10Y = (3.8, 5.4)
HARDCODE_US30Y = (4.3, 5.7)
HARDCODE_CURVE = (-0.5, 1.5)
HARDCODE_REAL10Y = (0.8, 3.2)
HARDCODE_VIX = (30.0, 13.0)
HARDCODE_CB_GOLD = (1200.0, 500.0)

#: 7 个可滚动因子（cb_gold 是季度合计，显式跳过滚动）
ROLLING_KEYS = ("dxy", "us2y", "us10y", "us30y", "curve_10y2y", "real10y", "vix")


@pytest.fixture(autouse=True)
def _stub_macro_sources(monkeypatch):
    """打桩 5 个外部源 —— V0.118.0 起 7 个因子来自外部源，漏打桩=单测真联网。

    V0.119.0 又加了 2 个源（低频 FRED 序列 / Eurostat），同样必须打桩。
    """
    from datetime import date as _date

    from app.repositories.market_data import USTYield

    async def fake_ust():
        return USTYield(us2y=4.05, us10y=4.05, us30y=4.88, data_date=_date(2026, 10, 21))

    async def fake_fred(series_id, **kwargs):
        return None

    async def fake_yahoo(symbol, **kwargs):
        return None

    async def fake_fred_periodic(series_id, **kwargs):
        return None

    async def fake_eurostat(**kwargs):
        return None

    monkeypatch.setattr("app.repositories.market_data.fetch_us_treasury_h15", fake_ust)
    monkeypatch.setattr("app.repositories.macro_sources.fetch_fred_latest", fake_fred)
    monkeypatch.setattr("app.repositories.macro_sources.fetch_yahoo_latest", fake_yahoo)
    monkeypatch.setattr(
        "app.repositories.macro_sources.fetch_fred_periodic_latest", fake_fred_periodic
    )
    monkeypatch.setattr("app.repositories.macro_sources.fetch_eurostat_gov_debt", fake_eurostat)


@pytest.fixture
async def repo() -> MacroFactorHistoryRepository:
    async with async_session_factory() as session:
        yield MacroFactorHistoryRepository(session)


async def _seed_one_factor(
    repo: MacroFactorHistoryRepository,
    factor_key: str,
    values: list[float],
    end_date: date | None = None,
    target: str = "default",
    source: str = "美联储 H.15",
    data_date: str = "2026-08-28",
) -> None:
    """种入 N 条每日不同 snapshot_date 的历史。"""
    end = end_date or date.today()
    for i, v in enumerate(values):
        snap = end - timedelta(days=i)
        await repo.upsert_batch(
            target=target,
            snapshot_date=snap,
            factors=[(factor_key, float(v), data_date, source)],
        )


class TestMacroFactorServiceDynamic:
    """MacroFactorService 注入 calculator 后的行为。"""

    async def test_no_calculator_injection_still_works(
        self, repo: MacroFactorHistoryRepository
    ) -> None:
        """不注入 calculator → 走 hardcode 默认（向后兼容）。"""
        svc = MacroFactorService(settings=None, central_bank=None)
        result = await svc.evaluate()
        # 旧测试期望的 hardcode 行为：score 用 hardcode 算
        assert result.score > 0
        # commit 2 内部组装 macro_dynamic，未注入时必为 False
        assert getattr(result, "macro_dynamic", False) is False

    async def test_calculator_with_empty_table_falls_back(
        self, repo: MacroFactorHistoryRepository
    ) -> None:
        """注入 calculator 但表完全空 → 全 hardcode，macro_dynamic=False。"""
        calc = MacroThresholdCalculator(repo=repo, min_samples=60)
        svc = MacroFactorService(settings=None, central_bank=None, threshold_calculator=calc)
        result = await svc.evaluate()
        assert result.macro_dynamic is False
        # 阈值全 hardcode → score 与无 calculator 场景一致
        baseline = MacroFactorService(settings=None, central_bank=None)
        baseline_result = await baseline.evaluate()
        assert result.score == baseline_result.score

    async def test_252_samples_dxy_uses_percentile(
        self, repo: MacroFactorHistoryRepository
    ) -> None:
        """dxy 种 252 日 → 阈值切到 percentile。"""
        # dxy 历史上 90-110 之间波动
        await _seed_one_factor(
            repo,
            "dxy",
            [90.0 + i * 0.08 for i in range(252)],  # 90.0 ~ 110.08
        )
        # ⚠ MacroFactorService._CACHE 是模块级 dict，跨 evaluate 实例共享。
        # 这里**两次 evaluate 在同一测试**内，必须手动清缓存避免 baseline 命中 dynamic 结果。
        from app.services import macro as macro_mod

        macro_mod._CACHE = {"ts": 0.0, "result": None}

        calc = MacroThresholdCalculator(repo=repo, min_samples=60)
        svc_dynamic = MacroFactorService(
            settings=None, central_bank=None, threshold_calculator=calc
        )
        result_dynamic = await svc_dynamic.evaluate()
        # dxy 单因子 score 切到 percentile
        macro_mod._CACHE = {"ts": 0.0, "result": None}  # 第二次清缓存
        baseline = MacroFactorService(settings=None, central_bank=None)
        result_baseline = await baseline.evaluate()

        # 这里只种了 dxy，其余 6 个滚动因子都回退 hardcode → 严格口径 → macro_dynamic=False
        assert result_dynamic.macro_dynamic is False
        assert result_dynamic.dynamic_factors == ["dxy"]
        # dxy 单因子 score 切到 percentile（hardcode→(95,105) vs percentile→P90/P10）
        dxy_dynamic = next(f for f in result_dynamic.factors if f.key == "dxy")
        dxy_baseline = next(f for f in result_baseline.factors if f.key == "dxy")
        assert dxy_dynamic.score != dxy_baseline.score

    async def test_all_rolling_factors_dynamic_marks_active(
        self, repo: MacroFactorHistoryRepository
    ) -> None:
        """7 个滚动因子全 dynamic → macro_dynamic=True。"""
        for k in ROLLING_KEYS:
            await _seed_one_factor(repo, k, [96.0 + i * 0.1 for i in range(252)])

        calc = MacroThresholdCalculator(repo=repo, min_samples=60)
        svc = MacroFactorService(settings=None, central_bank=None, threshold_calculator=calc)
        result = await svc.evaluate()
        assert result.macro_dynamic is True
        # V0.118.0：逐因子明细也要全 —— 前端角标文案按它派生
        assert set(result.dynamic_factors) == set(ROLLING_KEYS)

    async def test_cb_gold_even_with_252_samples_hardcode(
        self, repo: MacroFactorHistoryRepository
    ) -> None:
        """cb_gold 即使种 252 日也走 hardcode（季度合计失去动态意义）。"""
        await _seed_one_factor(
            repo,
            "cb_gold",
            [1000.0] * 252,  # 252 个相同值 → percentile 全 50
            source="央行购金表自动汇总",
            data_date="2025Q3–2026Q2",
        )
        for k in ROLLING_KEYS:
            await _seed_one_factor(repo, k, [96.0 + i * 0.1 for i in range(252)])

        calc = MacroThresholdCalculator(repo=repo, min_samples=60)
        svc = MacroFactorService(settings=None, central_bank=None, threshold_calculator=calc)
        result = await svc.evaluate()
        # cb_gold 显式跳过 → 7 个滚动因子 dynamic → macro_dynamic=True
        assert result.macro_dynamic is True
        assert "cb_gold" not in result.dynamic_factors
        # cb_gold 在 factors 列表里，data_date 仍是 STATIC_REF 描述
        cb_gold_factor = next(f for f in result.factors if f.key == "cb_gold")
        assert "滚动12月" in cb_gold_factor.data_date  # STATIC_REF 的描述

    async def test_59_samples_falls_back_per_factor(
        self, repo: MacroFactorHistoryRepository
    ) -> None:
        """59 样本 < min_samples=60 → 该因子回退 hardcode。"""
        for k in ROLLING_KEYS:
            n = 59 if k == "dxy" else 252
            await _seed_one_factor(repo, k, [96.0 + i * 0.1 for i in range(n)])

        calc = MacroThresholdCalculator(repo=repo, min_samples=60)
        svc = MacroFactorService(settings=None, central_bank=None, threshold_calculator=calc)
        result = await svc.evaluate()
        # dxy 回退 hardcode，其余 6 个切到 dynamic → 严格口径（全部动态才算）→ False
        assert result.macro_dynamic is False
        assert "dxy" not in result.dynamic_factors
        assert set(result.dynamic_factors) == set(ROLLING_KEYS) - {"dxy"}

    async def test_gov_debt_factors_never_dynamic(self, repo: MacroFactorHistoryRepository) -> None:
        """V0.119.0：3 个政府债务因子种满 252 日也不进 ``dynamic_factors``。

        季度/年度序列日频落表 ⇒ P10 == P90 ⇒ 滚动分位退化成常数。
        """
        for k in ("us_gov_debt", "cn_gov_debt", "eu_gov_debt"):
            await _seed_one_factor(
                repo,
                k,
                [100.0 + i * 0.1 for i in range(252)],
                source="FRED GFDEGDQ188S",
                data_date="2026-03-31",
            )
        for k in ROLLING_KEYS:
            await _seed_one_factor(repo, k, [96.0 + i * 0.1 for i in range(252)])

        calc = MacroThresholdCalculator(repo=repo, min_samples=60)
        svc = MacroFactorService(settings=None, central_bank=None, threshold_calculator=calc)
        result = await svc.evaluate()

        assert result.macro_dynamic is True
        assert set(result.dynamic_factors) == set(ROLLING_KEYS)
        for k in ("us_gov_debt", "cn_gov_debt", "eu_gov_debt"):
            assert k not in result.dynamic_factors
        # rolling_factors（前端「N/M」的分母）也只含 7 个日频因子
        assert set(result.rolling_factors) == set(ROLLING_KEYS)
