"""阈值常量单测（V0.78.0 Step A 收口）。

Step A 的核心主张是「统一阈值口径 = **纯重构**，行为不变」。本测试把该主张
拆成三部分可验证：

1. 各枚举的边界值；
2. **已知不对称** —— 消息面 ``> 55`` 严格 vs 等级 ``>= 55`` 含端点 vs
   结论卡着色 ``>= 55 / <= 40``（第三套口径有意保留，见
   ``schemas/thresholds.py::DecisionThreshold`` 的 docstring）；
3. **机械保证** —— 用 AST 扫服务层，确认「判定层」不再出现裸阈值字面量。
   第 3 条刻意用 AST 而非 grep：grep 会命中 docstring、注释、行尾约定，
   也扛不住行号漂移；AST 只看真实的比较表达式。

这些断言的价值在于**锁死现状**：将来若有人要统一那三套口径（属产品语义决策），
会先撞到这里，从而被迫显式处理而不是悄悄改掉。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.schemas.common import DirectionSignal, OpportunityWindow
from app.schemas.thresholds import (
    DecisionThreshold,
    DirectionThreshold,
    LevelThreshold,
    OpportunityWindowThreshold,
)
from app.services.decision import DecisionService
from app.services.news import direction_of
from app.services.scoring import OpportunityScoringService

ROOT = Path(__file__).resolve().parents[2]
SERVICES = ROOT / "src" / "app" / "services"

#: 判定层不允许出现的裸阈值（与 thresholds.py 的口径值一致）
THRESHOLD_LITERALS = {25, 40, 45, 50, 55, 60, 65, 70, 75}


# ============================================================ 1. 枚举边界值


def test_direction_threshold_values() -> None:
    """单维度/共振/消息面方向阈值（V0.78.0 Step A 集中管理）。"""
    assert DirectionThreshold.STRONG_BULLISH == 70
    assert DirectionThreshold.BULLISH == 55
    assert DirectionThreshold.NEUTRAL_HIGH == 60
    assert DirectionThreshold.NEUTRAL_LOW == 40
    assert DirectionThreshold.BEARISH == 45
    assert DirectionThreshold.STRONG_BEARISH == 25


def test_level_threshold_values() -> None:
    """综合指数等级阈值（含端点）。"""
    assert LevelThreshold.STRONG_UP == 75
    assert LevelThreshold.UP == 55
    assert LevelThreshold.SIDEWAYS == 45
    assert LevelThreshold.DOWN == 25


def test_decision_threshold_values() -> None:
    """决策矩阵档位阈值（BUY 拆 3 档 + HOLD 缓冲档）。"""
    assert DecisionThreshold.BUY_HEAVY == 75
    assert DecisionThreshold.BUY == 65
    assert DecisionThreshold.BUY_LIGHT == 55
    assert DecisionThreshold.HOLD == 50
    assert DecisionThreshold.HOLD_LOW == 40


def test_opportunity_window_threshold_values() -> None:
    """宏观机会窗口分级（Step A 收口时从 scoring.py 裸字面量提升为枚举）。"""
    assert OpportunityWindowThreshold.STRONG == 70
    assert OpportunityWindowThreshold.MEDIUM == 55
    assert OpportunityWindowThreshold.WEAK == 40


# ====================================================== 2. 三套口径的差异


def test_message_uses_strict_inequality() -> None:
    """消息面用**严格** ``> 55`` / ``< 45``：恰好 55 判中性。"""
    assert direction_of(56) == DirectionSignal.BULLISH
    assert direction_of(55) == DirectionSignal.NEUTRAL
    assert direction_of(45) == DirectionSignal.NEUTRAL
    assert direction_of(44) == DirectionSignal.BEARISH


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (75, OpportunityWindow.STRONG),
        (70, OpportunityWindow.STRONG),
        (69, OpportunityWindow.MEDIUM),
        (55, OpportunityWindow.MEDIUM),
        (54, OpportunityWindow.WEAK),
        (40, OpportunityWindow.WEAK),
        (39, OpportunityWindow.STANDBY),
    ],
)
def test_opportunity_window_boundaries(score: int, expected: OpportunityWindow) -> None:
    """机会窗口用**含端点** ``>= 70/55/40``（与消息面的严格不等号不同，这是有意的）。"""
    assert OpportunityScoringService._to_window(float(score)) is expected


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (61, DirectionSignal.BULLISH),
        (60, DirectionSignal.BULLISH),
        (59, DirectionSignal.NEUTRAL),
        (41, DirectionSignal.NEUTRAL),
        (40, DirectionSignal.BEARISH),
    ],
)
def test_single_dimension_signal_uses_neutral_high_low(
    score: int, expected: DirectionSignal
) -> None:
    """单维度方向用 60/40（``NEUTRAL_HIGH``/``NEUTRAL_LOW``），比消息面的 55/45 更严。"""
    assert OpportunityScoringService._to_signal(float(score)) is expected


def test_summarize_shares_window_thresholds() -> None:
    """文案分支与 ``_to_window`` 必须同源，否则"分级"与"说法"会打架。"""
    for score, keyword in (
        (70, "强机会窗口"),
        (55, "中等机会窗口"),
        (40, "弱机会窗口"),
        (39, "建议观望"),
    ):
        assert keyword in OpportunityScoringService._summarize(float(score))


@pytest.mark.parametrize(
    ("idx", "expected_pct"),
    [(75, 80.0), (55, 60.0), (45, 40.0), (25, 20.0), (24, 10.0)],
)
def test_suggest_position_shares_level_thresholds(idx: int, expected_pct: float) -> None:
    """仓位档位分界点与 ``LevelThreshold`` 同源（等级 → 仓位）。"""
    pct, _label = DecisionService._suggest_position(float(idx))
    assert pct == expected_pct


# ============================================ 3. 机械保证：判定层无裸字面量


def _is_threshold_literal_compare(node: ast.Compare) -> bool:
    """该比较的右侧是否为阈值裸数字（并排除「非分数语义」）。"""
    if not isinstance(node.ops[0], (ast.Gt, ast.GtE, ast.Lt, ast.LtE)):
        return False
    right = node.comparators[0]
    if not (isinstance(right, ast.Constant) and isinstance(right.value, (int, float))):
        return False
    if right.value not in THRESHOLD_LITERALS:
        return False
    # 胜率(%) / 数组长度 / 键数上限 等与分数无关的比较，不属于本枚举要收口的对象
    left = node.left
    if isinstance(left, ast.Attribute) and left.attr in {
        "win_rate",
        "keys",
        "quantity",
        "grams_held",
    }:
        return False
    # 左边是 len(...) → 数组长度（交易日根数 / 键数上限），与分数无关
    return not (
        isinstance(left, ast.Call) and isinstance(left.func, ast.Name) and left.func.id == "len"
    )


#: 有意保留裸字面量的函数（显示层着色，非判定层），见下方 test 的 docstring
_SKIP_FUNCTIONS = frozenset({"_build_reason_items"})


class _ThresholdLiteralVisitor(ast.NodeVisitor):
    """遍历服务层 AST，收集「判定层裸阈值比较」，逐函数名跳过白名单。

    为什么用 AST 而不是 grep：grep 会命中 docstring 与注释里的数字，也扛不住
    行号漂移；AST 只看真实的比较表达式。**记法**：``_build_reason_items`` 内的
    ``idx >= 55 / idx <= 40`` 是结论卡的显示层方向着色（40 故意不同于
    ``DirectionThreshold.BEARISH``=45 以更早示警），属产品语义决策。
    """

    def __init__(self, path_name: str) -> None:
        self.path_name = path_name
        self.offenders: list[str] = []
        self._funcs: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._funcs.append(node.name)
        self.generic_visit(node)
        self._funcs.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._funcs.append(node.name)
        self.generic_visit(node)
        self._funcs.pop()

    def visit_Compare(self, node: ast.Compare) -> None:
        skipped = bool(self._funcs) and self._funcs[-1] in _SKIP_FUNCTIONS
        if not skipped and _is_threshold_literal_compare(node):
            self.offenders.append(f"{self.path_name}:{node.lineno}")
        self.generic_visit(node)


def test_no_threshold_literals_left_in_services() -> None:
    """服务层判定逻辑不得再出现裸阈值字面量。

    例外（有意保留）：``decision._build_reason_items`` 的 ``idx >= 55 / idx <= 40``
    —— 那是结论卡的**显示层方向着色**，40 故意不同于 ``BEARISH``(45) 以更早示警，
    属产品语义决策而非口径统一。``schemas/thresholds.py`` 顶部与本测试均已记录。
    """
    offenders: list[str] = []
    for path in sorted(SERVICES.glob("*.py")):
        visitor = _ThresholdLiteralVisitor(path.name)
        visitor.visit(ast.parse(path.read_text(encoding="utf-8")))
        offenders.extend(visitor.offenders)
    assert not offenders, (
        "服务层判定逻辑仍有裸阈值字面量，请改为引用 schemas/thresholds.py："
        + ", ".join(offenders)
        + "（若确属不同语义，请先在 thresholds.py 中新增对应枚举再引用）"
    )


def test_coloring_asymmetry_is_known_not_accidental() -> None:
    """把结论卡着色用的 55/40 现状**写成断言**，使其成为显式记录而非遗留。

    若将来决定统一它，本测试会失败 —— 那是正确的：应同时更新
    ``thresholds.py`` 的 docstring 与本用例，而不是悄悄改动。
    """
    src = (SERVICES / "decision.py").read_text(encoding="utf-8")
    assert "if idx >= 55:" in src, "结论卡着色阈值 55 已被改动 —— 请同步更新 thresholds.py 注释"
    assert "elif idx <= 40:" in src, "结论卡着色阈值 40 已被改动 —— 请同步更新 thresholds.py 注释"
    assert int(DirectionThreshold.BEARISH) == 45, "着色用 40 与 BEARISH 45 的差异前提已变"
