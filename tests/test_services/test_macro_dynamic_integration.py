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

HARDCODE_DXY = (95.0, 105.0)
HARDCODE_US10Y = (3.5, 4.5)
HARDCODE_US30Y = (4.0, 5.0)
HARDCODE_VIX = (25.0, 12.0)
HARDCODE_CB_GOLD = (1200.0, 500.0)


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

        # 这里只种了 dxy，us10y/us30y/vix 都回退 hardcode → 不足 4 因子 → macro_dynamic=False
        assert result_dynamic.macro_dynamic is False
        # dxy 单因子 score 切到 percentile（hardcode→(95,105) vs percentile→P90/P10）
        dxy_dynamic = next(f for f in result_dynamic.factors if f.key == "dxy")
        dxy_baseline = next(f for f in result_baseline.factors if f.key == "dxy")
        assert dxy_dynamic.score != dxy_baseline.score

    async def test_all_4_rolling_factors_dynamic_marks_active(
        self, repo: MacroFactorHistoryRepository
    ) -> None:
        """4 个滚动因子全 dynamic → macro_dynamic=True。"""
        await _seed_one_factor(repo, "dxy", [96.0 + i * 0.1 for i in range(252)])
        await _seed_one_factor(repo, "us10y", [3.5 + i * 0.01 for i in range(252)])
        await _seed_one_factor(repo, "us30y", [4.0 + i * 0.01 for i in range(252)])
        await _seed_one_factor(repo, "vix", [15.0 + i * 0.05 for i in range(252)])

        calc = MacroThresholdCalculator(repo=repo, min_samples=60)
        svc = MacroFactorService(settings=None, central_bank=None, threshold_calculator=calc)
        result = await svc.evaluate()
        assert result.macro_dynamic is True

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
        await _seed_one_factor(repo, "dxy", [96.0 + i * 0.1 for i in range(252)])
        await _seed_one_factor(repo, "us10y", [3.5 + i * 0.01 for i in range(252)])
        await _seed_one_factor(repo, "us30y", [4.0 + i * 0.01 for i in range(252)])
        await _seed_one_factor(repo, "vix", [15.0 + i * 0.05 for i in range(252)])

        calc = MacroThresholdCalculator(repo=repo, min_samples=60)
        svc = MacroFactorService(settings=None, central_bank=None, threshold_calculator=calc)
        result = await svc.evaluate()
        # cb_gold 显式跳过 → 4 个滚动因子 dynamic → macro_dynamic=True
        assert result.macro_dynamic is True
        # cb_gold 在 factors 列表里，data_date 仍是 STATIC_REF 描述
        cb_gold_factor = next(f for f in result.factors if f.key == "cb_gold")
        assert "滚动12月" in cb_gold_factor.data_date  # STATIC_REF 的描述

    async def test_59_samples_falls_back_per_factor(
        self, repo: MacroFactorHistoryRepository
    ) -> None:
        """59 样本 < min_samples=60 → 该因子回退 hardcode。"""
        await _seed_one_factor(repo, "dxy", [96.0 + i * 0.1 for i in range(59)])
        await _seed_one_factor(repo, "us10y", [3.5 + i * 0.01 for i in range(252)])
        await _seed_one_factor(repo, "us30y", [4.0 + i * 0.01 for i in range(252)])
        await _seed_one_factor(repo, "vix", [15.0 + i * 0.05 for i in range(252)])

        calc = MacroThresholdCalculator(repo=repo, min_samples=60)
        svc = MacroFactorService(settings=None, central_bank=None, threshold_calculator=calc)
        result = await svc.evaluate()
        # dxy 回退 hardcode，3 个 us10y/us30y/vix 切到 dynamic → 不足 4 → False
        assert result.macro_dynamic is False
