"""决策引擎单元测试：规则判定矩阵。"""

from types import SimpleNamespace

from app.schemas.common import DirectionSignal
from app.schemas.market import TrendIndexLevel, TrendIndexOut
from app.schemas.position import PositionSummary
from app.services.decision import DecisionService


class FakeTrend:
    """假趋势服务：返回指定指数的简化对象。"""

    def __init__(self, idx: float, level: TrendIndexLevel = TrendIndexLevel.UP) -> None:
        self._idx = idx
        self._level = level

    async def analyze(self, days: int = 60):
        return SimpleNamespace(
            index=TrendIndexOut(
                score=self._idx,
                level=self._level,
                direction=DirectionSignal.BULLISH if self._idx >= 55 else DirectionSignal.NEUTRAL,
                summary="测试趋势",
            ),
        )


class FakePosition:
    """假持仓服务：返回指定摘要。"""

    def __init__(self, summary: PositionSummary) -> None:
        self._s = summary

    async def summary(self) -> PositionSummary:
        return self._s


def _empty() -> PositionSummary:
    return PositionSummary(has_position=False)


def _pos(pnl_pct: float) -> PositionSummary:
    return PositionSummary(
        has_position=True,
        quantity=100,
        avg_cost=9.0,
        pnl=round(pnl_pct * 9, 2),
        pnl_pct=pnl_pct,
    )


def _svc(idx: float, summary: PositionSummary) -> DecisionService:
    return DecisionService(trend=FakeTrend(idx), position=FakePosition(summary))


async def test_no_position_strong_trend_buy() -> None:
    """空仓 + 指数≥70 → 高置信买入。"""
    out = await _svc(80.0, _empty()).evaluate()
    assert out.action == "BUY"
    assert out.confidence == "high"
    assert "参数面" in out.reasons[0]


async def test_no_position_weak_trend_wait() -> None:
    """空仓 + 指数<45 → 观望。"""
    out = await _svc(30.0, _empty()).evaluate()
    assert out.action == "WAIT"


async def test_position_strong_trend_add() -> None:
    """持仓 + 指数≥70 → 加仓。"""
    out = await _svc(75.0, _pos(5.0)).evaluate()
    assert out.action == "ADD"
    assert out.confidence == "high"


async def test_position_profit_trend_weak_sell() -> None:
    """持仓浮盈≥15% + 指数<60 → 止盈卖出。"""
    out = await _svc(50.0, _pos(20.0)).evaluate()
    assert out.action == "SELL"
    assert out.confidence == "high"


async def test_position_loss_trend_weak_reduce() -> None:
    """持仓浮亏≥10% + 指数<40 → 止损减仓。"""
    out = await _svc(30.0, _pos(-15.0)).evaluate()
    assert out.action == "REDUCE"
    assert out.confidence == "high"


async def test_position_neutral_hold() -> None:
    """持仓 + 指数 45-55 → 持有。"""
    out = await _svc(50.0, _pos(3.0)).evaluate()
    assert out.action == "HOLD"


async def test_suggested_position_mapping() -> None:
    """评估指数 → 建议仓位映射（80/60/40/20/10 + 等级）。"""
    assert _svc(80.0, _empty())._suggest_position(80.0) == (80.0, "重仓")
    assert _svc(80.0, _empty())._suggest_position(60.0) == (60.0, "中高仓位")
    assert _svc(80.0, _empty())._suggest_position(50.0) == (40.0, "中性仓位")
    assert _svc(80.0, _empty())._suggest_position(30.0) == (20.0, "轻仓")
    assert _svc(80.0, _empty())._suggest_position(10.0) == (10.0, "观望空仓")


async def test_decision_includes_position_rec() -> None:
    """决策输出包含仓位推荐字段与理由。"""
    out = await _svc(68.0, _empty()).evaluate()
    assert out.suggested_position == 60.0
    assert out.position_level == "中高仓位"
    assert any("仓位建议" in r for r in out.reasons)
