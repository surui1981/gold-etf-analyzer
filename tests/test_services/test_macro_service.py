"""宏观参考因子服务单元测试：友好度映射、权重归一、指数合成。"""

import pytest

from app.schemas.common import DirectionSignal
from app.services.macro import MACRO_FACTOR_RULES, MacroFactorService, _friendly_score

_RULES = {r["key"]: r for r in MACRO_FACTOR_RULES}


def test_weights_sum_to_one() -> None:
    """宏观因子权重必须归一。"""
    assert sum(r["weight"] for r in MACRO_FACTOR_RULES) == pytest.approx(1.0)


def test_negative_correlation_mapping() -> None:
    """负相关因子（美元指数/美债）：值越低越利好黄金。"""
    dxy = _RULES["dxy"]
    assert _friendly_score(95.0, dxy) == 100.0  # best 分位
    assert _friendly_score(105.0, dxy) == 0.0  # worst 分位
    assert _friendly_score(100.0, dxy) == 50.0  # 中枢

    us10y = _RULES["us10y"]
    assert _friendly_score(3.5, us10y) == 100.0
    assert _friendly_score(4.5, us10y) == 0.0


def test_positive_correlation_mapping() -> None:
    """正相关因子（VIX/央行购金）：值越高越利好黄金。"""
    cb = _RULES["cb_gold"]
    assert _friendly_score(1200.0, cb) == 100.0
    assert _friendly_score(500.0, cb) == 0.0
    assert _friendly_score(850.0, cb) == 50.0

    vix = _RULES["vix"]
    assert _friendly_score(25.0, vix) == 100.0
    assert _friendly_score(12.0, vix) == 0.0


async def test_macro_evaluate(monkeypatch) -> None:
    """指数合成：5 因子、分数与方向、贡献求和（绕过 TTL 缓存直接测合成逻辑）。"""
    async def fake_collect(self):
        return {
            "dxy": (96.5, "2026-08-28"),
            "us10y": (4.4, "2026-08-28"),
            "us30y": (4.9, "2026-08-28"),
            "vix": (18.5, "2026-08-28"),
            "cb_gold": (1045.0, "2024年度"),
        }

    monkeypatch.setattr(MacroFactorService, "_collect", fake_collect)
    out = await MacroFactorService()._evaluate_uncached()

    assert len(out.factors) == 5
    assert 0 <= out.score <= 100
    assert out.direction in (DirectionSignal.BULLISH, DirectionSignal.BEARISH, DirectionSignal.NEUTRAL)
    assert sum(f.contribution for f in out.factors) == pytest.approx(out.score, abs=0.5)
    assert all(0 <= f.score <= 100 for f in out.factors)
    # 美债 4.4% → 友好度 10（偏利空）
    us10y = next(f for f in out.factors if f.key == "us10y")
    assert us10y.direction == DirectionSignal.BEARISH
    assert us10y.score == pytest.approx(10.0, abs=0.1)
