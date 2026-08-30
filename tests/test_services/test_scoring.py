"""评分引擎单元测试：验证权重配置与多空环境映射。"""

import pytest

from app.schemas.common import DirectionSignal, OpportunityWindow
from app.schemas.factors import MacroFactorInput
from app.services.scoring import FACTOR_RULES, OpportunityScoringService


@pytest.fixture
def scoring() -> OpportunityScoringService:
    return OpportunityScoringService()


def test_weights_sum_to_one() -> None:
    """权重配置必须归一，否则评分失真。"""
    total = sum(r.weight for r in FACTOR_RULES)
    assert total == pytest.approx(1.0)


def test_bullish_environment_scores_high(scoring: OpportunityScoringService) -> None:
    """强利多环境：低实际利率、弱美元、低名义收益率、高通胀、高避险。"""
    factors = MacroFactorInput(
        dxy=96.0,
        us10y_yield=3.6,
        real_rate=1.4,
        inflation_expectation=3.0,
        risk_off=9,
    )
    result = scoring.evaluate(factors)

    assert result.score >= 70
    assert result.window == OpportunityWindow.STRONG
    assert result.signal == DirectionSignal.BULLISH
    assert len(result.factors) == 5
    # 逐因子贡献求和应等于综合分（允许浮点误差）
    assert sum(f.contribution for f in result.factors) == pytest.approx(result.score, abs=0.1)


def test_bearish_environment_scores_low(scoring: OpportunityScoringService) -> None:
    """强利空环境：高实际利率、强美元、高名义收益率、低通胀、低避险。"""
    factors = MacroFactorInput(
        dxy=106.0,
        us10y_yield=4.8,
        real_rate=2.8,
        inflation_expectation=2.0,
        risk_off=1,
    )
    result = scoring.evaluate(factors)

    assert result.score < 40
    assert result.window == OpportunityWindow.STANDBY
    assert result.signal == DirectionSignal.BEARISH


def test_neutral_environment_maps_to_weak(scoring: OpportunityScoringService) -> None:
    """中性环境：所有因子位于中枢，应落入弱机会/观望区间。"""
    factors = MacroFactorInput(
        dxy=100.0,
        us10y_yield=4.0,
        real_rate=2.0,
        inflation_expectation=2.5,
        risk_off=5,
    )
    result = scoring.evaluate(factors)

    assert 40 <= result.score < 55
    assert result.window == OpportunityWindow.WEAK
    assert result.signal == DirectionSignal.NEUTRAL


def test_direction_signal_in_factors(scoring: OpportunityScoringService) -> None:
    """单因子方向应正确反映多空（用于前端红绿着色）。"""
    factors = MacroFactorInput(
        dxy=103.5,
        us10y_yield=4.2,
        real_rate=2.3,
        inflation_expectation=2.6,
        risk_off=3,
    )
    result = scoring.evaluate(factors)
    by_key = {f.factor: f for f in result.factors}

    # 实际利率处于高位 → 利空黄金
    assert by_key["real_rate"].direction == DirectionSignal.BEARISH
    # 美元指数处于高位 → 利空黄金
    assert by_key["dxy"].direction == DirectionSignal.BEARISH
    # 通胀预期略高于中枢 → 利多黄金
    assert by_key["inflation_expectation"].direction == DirectionSignal.BULLISH
