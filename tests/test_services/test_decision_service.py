"""决策引擎单元测试：规则判定矩阵。"""

from types import SimpleNamespace

import pytest

from app.schemas.common import DirectionSignal
from app.schemas.decision import DecisionAction
from app.schemas.market import TrendIndexLevel, TrendIndexOut
from app.schemas.position import PositionSummary
from app.services.decision import DecisionService


class FakeTrend:
    """假趋势服务：返回指定指数的简化对象。"""

    def __init__(self, idx: float, level: TrendIndexLevel = TrendIndexLevel.UP) -> None:
        self._idx = idx
        self._level = level

    async def analyze(self, days: int = 60, target: str = "ny"):
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

    async def summary(self, account_id: int | None = None) -> PositionSummary:
        # V0.62.0：持仓摘要支持按账本过滤（None = 全部账本合并），替身需同步签名
        self.last_account_id = account_id
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


async def test_no_position_strong_trend_buy_heavy() -> None:
    """V0.78.0：空仓 + 指数≥75 → 高置信重仓买入（BUY_HEAVY）。"""
    out = await _svc(80.0, _empty()).evaluate()
    assert out.action == "BUY_HEAVY"
    assert out.confidence == "high"
    assert "参数面" in out.reasons[0]


async def test_no_position_strong_trend_buy() -> None:
    """V0.78.0：空仓 + 指数 70-74 → 普通买入（BUY，与 V0.77.2 idx≥70 BUY 等价行为）。"""
    out = await _svc(72.0, _empty()).evaluate()
    assert out.action == "BUY"
    assert out.confidence == "high"


async def test_no_position_weak_trend_wait() -> None:
    """空仓 + 指数<45 → 观望。"""
    out = await _svc(30.0, _empty()).evaluate()
    assert out.action == "WAIT"


async def test_position_strong_trend_add() -> None:
    """持仓 + 指数≥75 → 加仓。"""
    out = await _svc(80.0, _pos(5.0)).evaluate()
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
    """V0.78.0：持仓 + 指数 45-55 → 观望持有（HOLD_CAUTIOUS 缓冲档）。

    V0.77.2 旧逻辑：idx=50 → HOLD (low)
    V0.78.0 新逻辑：idx=50 处于 HOLD_LOW 区间（≥40），触发 HOLD_CAUTIOUS 缓冲档
    """
    out = await _svc(50.0, _pos(3.0)).evaluate()
    assert out.action == "HOLD_CAUTIOUS"
    assert out.confidence == "low"


async def test_suggested_position_mapping() -> None:
    """评估指数 → 建议仓位映射（80/60/40/20/10 + 等级）。"""
    assert _svc(80.0, _empty())._suggest_position(80.0) == (80.0, "重仓")
    assert _svc(80.0, _empty())._suggest_position(60.0) == (60.0, "中高仓位")
    assert _svc(80.0, _empty())._suggest_position(50.0) == (40.0, "中性仓位")
    assert _svc(80.0, _empty())._suggest_position(30.0) == (20.0, "轻仓")
    assert _svc(80.0, _empty())._suggest_position(10.0) == (10.0, "观望空仓")


async def test_evaluate_forwards_account_id_to_position_summary() -> None:
    """V0.62.0 多账本：account_id 必须透传到持仓摘要（None = 全部账本合并口径）。"""
    fake = FakePosition(_empty())
    svc = DecisionService(trend=FakeTrend(80.0), position=fake)

    await svc.evaluate(account_id=7)
    assert fake.last_account_id == 7

    await svc.evaluate()
    assert fake.last_account_id is None


async def test_decision_includes_position_rec() -> None:
    """决策输出包含仓位推荐字段与理由。"""
    out = await _svc(68.0, _empty()).evaluate()
    assert out.suggested_position == 60.0
    assert out.position_level == "中高仓位"
    assert any("仓位建议" in r for r in out.reasons)


# ───────────────────── V0.71.0：白银 target / target_label ─────────────────────


def test_target_label_returns_silver_labels() -> None:
    """target_label：白银 target 返回对应中文名，黄金 target 保持原样。"""
    from app.services.decision import target_label

    assert target_label("silver_etf") == "白银ETF"
    assert target_label("silver_ny") == "纽约白银"
    assert target_label("etf") == "黄金ETF"
    assert target_label("ny") == "纽约黄金"
    assert target_label("gram") == "上海金克价"


def test_target_label_unknown_returns_default() -> None:
    """target_label：未知 target 回退「黄金ETF」（与 V0.70.0 默认兼容）。"""
    from app.services.decision import target_label

    assert target_label("") == "黄金ETF"
    assert target_label("unknown") == "黄金ETF"
    assert target_label(None) == "黄金ETF"


def test_decision_evaluate_accepts_silver_etf_target() -> None:
    """DecisionService.evaluate(target='silver_etf') 文案中「建议仓位」切换为「白银ETF仓位」。

    不依赖网络与真实持仓——构造最小 stub 返回固定 score。
    """
    import asyncio

    from app.schemas.common import DirectionSignal
    from app.schemas.market import (
        TrendIndexLevel,
        TrendIndexOut,
    )
    from app.schemas.position import PositionSummary
    from app.services.decision import DecisionService

    class StubTrendService:
        async def analyze(self, days: int = 60, target: str = "ny", interval: str = "D"):
            return type(
                "T",
                (),
                {
                    "index": TrendIndexOut(
                        score=72.0,
                        level=TrendIndexLevel.UP,
                        direction=DirectionSignal.BULLISH,
                        summary="测试白银指数",
                        components={"tech": 70, "macro": 60, "news": 80},
                    )
                },
            )()

    class StubPositionService:
        async def summary(self, account_id=None):
            return PositionSummary(has_position=False)

    svc = DecisionService(StubTrendService(), StubPositionService())
    out = asyncio.run(svc.evaluate(days=30, target="silver_etf"))
    # 最后一条理由应当是「建议白银ETF仓位」（不是「建议黄金仓位」）
    last_reason = out.reason_items[-1].text
    assert "白银ETF仓位" in last_reason, f"期望白银ETF仓位，实际: {last_reason}"
    assert "黄金仓位" not in last_reason


# ───────────────────── V0.78.0：决策矩阵档位补全（Step B）─────────────────────


# 边界值矩阵覆盖（无持仓分支）
@pytest.mark.parametrize("idx,expected", [
    (80.0, DecisionAction.BUY_HEAVY),    # ≥75 重仓
    (75.0, DecisionAction.BUY_HEAVY),    # 边界 75
    (74.999, DecisionAction.BUY),        # <75 落入 BUY
    (70.0, DecisionAction.BUY),          # ≥65 普通
    (65.0, DecisionAction.BUY),          # 边界 65
    (64.999, DecisionAction.BUY_LIGHT),  # <65 落入 BUY_LIGHT
    (60.0, DecisionAction.BUY_LIGHT),    # ≥55 轻仓
    (55.0, DecisionAction.BUY_LIGHT),    # 边界 55
    (54.999, DecisionAction.WAIT),       # <55 落入 WAIT
    (52.0, DecisionAction.WAIT),         # ≥50 WAIT low
    (50.0, DecisionAction.WAIT),         # 边界 50
    (49.999, DecisionAction.WAIT),       # <50 WAIT medium
])
def test_decision_no_position_three_tier_buy(idx, expected):
    """V0.78.0：BUY 拆 3 档（HEAVY/BUY/LIGHT）+ WAIT 拆 2 档。"""
    action, conf = DecisionService._decide(idx, pnl_pct=None, has_position=False)
    assert action == expected
    assert conf in ("high", "medium", "low")


# 卡死区消除（V0.77.2 旧逻辑下 idx [60,70) × pnl [-10%, +15%] 什么都不做）
@pytest.mark.parametrize("idx,pnl,expected", [
    (65.0, 0.0, DecisionAction.HOLD),         # 卡死区正中
    (65.0, -5.0, DecisionAction.HOLD),        # 轻微亏损
    (68.0, 10.0, DecisionAction.HOLD),        # 轻微浮盈
    (60.0, 0.0, DecisionAction.HOLD),         # 边界 60（≥55 HOLD）
    (62.0, 14.9, DecisionAction.HOLD),        # pnl 接近 15 但未触发止盈
])
def test_decision_no_dead_zone_eliminated(idx, pnl, expected):
    """V0.78.0：消除 idx [60, 70) × pnl [-10%, +15%] 卡死区 → 落入 HOLD。"""
    action, conf = DecisionService._decide(idx, pnl_pct=pnl, has_position=True)
    assert action == expected
    assert conf == "medium"


# HOLD_CAUTIOUS 缓冲档（idx [40, 45)）
@pytest.mark.parametrize("idx,pnl,expected", [
    (44.0, 0.0, DecisionAction.HOLD_CAUTIOUS),   # 中位
    (40.0, 0.0, DecisionAction.HOLD_CAUTIOUS),   # 边界 40
    (42.0, 5.0, DecisionAction.HOLD_CAUTIOUS),   # 浮盈下不直接减仓
    (43.0, -8.0, DecisionAction.HOLD_CAUTIOUS),  # 接近止损但未触发
])
def test_decision_hold_cautious_buffer_zone(idx, pnl, expected):
    """V0.78.0：新增 HOLD_CAUTIOUS（idx [40, 45)），替代原 REDUCE 过激动作。"""
    action, conf = DecisionService._decide(idx, pnl_pct=pnl, has_position=True)
    assert action == expected
    assert conf == "low"


# 止盈/止损条件优先级最高
@pytest.mark.parametrize("idx,pnl,expected,expected_conf", [
    (50.0, 16.0, DecisionAction.SELL, "high"),       # 浮盈 ≥15 + idx<60
    (59.9, 20.0, DecisionAction.SELL, "high"),       # 浮盈 20%
    (35.0, -11.0, DecisionAction.REDUCE, "high"),    # 浮亏 ≤-10 + idx<40
    (39.9, -15.0, DecisionAction.REDUCE, "high"),    # 浮亏 15%
])
def test_decision_take_profit_stop_loss_overrides(idx, pnl, expected, expected_conf):
    """止盈/止损优先级最高——即使 idx 达标，也优先 SELL/REDUCE。"""
    action, conf = DecisionService._decide(idx, pnl_pct=pnl, has_position=True)
    assert action == expected
    assert conf == expected_conf


# 仓位档位与决策 BUY 档部分对齐（V0.78.0 仅 BUY_HEAVY/BUY 对齐，BUY_LIGHT 保留原 60% 档待 V0.80.0 收口）
@pytest.mark.parametrize("idx,expected_sugg_pos", [
    (75.0, 80.0),   # BUY_HEAVY → 80%
    (80.0, 80.0),   # BUY_HEAVY → 80%
    (65.0, 60.0),   # BUY → 60%
    (70.0, 60.0),   # BUY → 60%
])
def test_decision_buy_heavy_buy_aligned_with_position_tier(idx, expected_sugg_pos):
    """V0.78.0：BUY_HEAVY (≥75) ↔ 仓位 80% / BUY (≥65) ↔ 仓位 60%。"""
    action, _ = DecisionService._decide(idx, pnl_pct=None, has_position=False)
    suggest, _ = DecisionService._suggest_position(idx)
    assert action in (DecisionAction.BUY_HEAVY, DecisionAction.BUY)
    assert suggest == expected_sugg_pos


# DecisionOut.action 现在是 DecisionAction 枚举（字符串兼容）
async def test_decision_out_action_is_decision_action_enum():
    out = await _svc(80.0, _empty()).evaluate()
    assert isinstance(out.action, DecisionAction)
    assert out.action == DecisionAction.BUY_HEAVY
    # 字符串兼容（V0.77.2 行为不变）
    assert out.action == "BUY_HEAVY"
    assert out.action.value == "BUY_HEAVY"


# action_label 中文映射覆盖 9 档
async def test_action_labels_cover_all_nine_tiers():
    """_ACTION_LABELS 必须覆盖所有 9 个 DecisionAction（含 3 新档）。"""
    from app.services.decision import _ACTION_LABELS

    for action in DecisionAction:
        assert action in _ACTION_LABELS, f"{action} 缺少中文标签"
        assert len(_ACTION_LABELS[action]) > 0, f"{action} 标签为空"


# 前端 ACTION_STYLE 覆盖 9 档（防止前端缺色块显示空白）
def test_frontend_action_style_covers_all_nine_tiers():
    """读取 portfolio.html 的 ACTION_STYLE 对象，验证 9 档都有色块。"""
    import re
    from pathlib import Path

    html = Path("static/portfolio.html").read_text(encoding="utf-8")
    # 在整个文件中找 ACTION_STYLE 起始点到 8 行内匹配所有键（绕开 regex 嵌套 {} 问题）
    m = re.search(r"const ACTION_STYLE = \{(.+?)^\};", html, re.DOTALL | re.MULTILINE)
    assert m, "ACTION_STYLE not found"
    body = m.group(1)

    for action in DecisionAction:
        # 用单词边界防止 BUY_HEAVY 误匹配 BUY_HEAVY 前缀
        assert re.search(rf"\b{action.value}\s*:", body), (
            f"ACTION_STYLE 缺 {action.value}"
        )


# i18n 三语覆盖 9 个 portfolio.action_* 键
# 注意：zh-TW 故意不全（docstring 声明「未翻譯的 deep body 走 fallback 到 zh-CN」）
@pytest.mark.parametrize("locale_file,required_keys", [
    ("static/i18n/zh-CN.js", {f"portfolio.action_{a.value.lower()}" for a in DecisionAction}),
    ("static/i18n/en-US.js", {f"portfolio.action_{a.value.lower()}" for a in DecisionAction}),
    # zh-TW 缺 wait（已声明 fallback 到 zh-CN），验证其余 8 个必有
    (
        "static/i18n/zh-TW.js",
        {
            "portfolio.action_buy_heavy", "portfolio.action_buy", "portfolio.action_buy_light",
            "portfolio.action_add", "portfolio.action_hold", "portfolio.action_hold_cautious",
            "portfolio.action_reduce", "portfolio.action_sell",
        },
    ),
])
def test_i18n_action_keys_required(locale_file, required_keys):
    """i18n 三语必须覆盖声明的 portfolio.action_* 键。"""
    from pathlib import Path

    src = Path(locale_file).read_text(encoding="utf-8")
    missing = [k for k in required_keys if k not in src]
    assert not missing, f"{locale_file} 缺 {missing}"
