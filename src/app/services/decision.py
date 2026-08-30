"""购买决策引擎：参数面信号（趋势指数） × 交易面状态（持仓盈亏） → ETF 购买决策。

规则为典型经验（rule-based），集中在 ``DecisionService`` 内，可按策略调整；
后续 P2 将叠加宏观机会评分形成「宏观 × 技术」双维度共振。
"""

from app.schemas.position import DecisionOut
from app.services.position import PositionService
from app.services.trend import TrendService
from app.utils.logger import get_logger

logger = get_logger(__name__)

_ACTION_LABELS = {
    "BUY": "买入",
    "ADD": "加仓",
    "HOLD": "持有",
    "REDUCE": "减仓",
    "SELL": "卖出",
    "WAIT": "观望",
}

_LEVEL_LABELS = {
    "strong_up": "强势上升",
    "up": "上升",
    "sideways": "震荡整理",
    "down": "下降",
    "strong_down": "弱势下降",
}


class DecisionService:
    """决策引擎：综合趋势指数与持仓状态输出购买建议。"""

    def __init__(
        self,
        trend: TrendService,
        position: PositionService,
    ) -> None:
        self._trend = trend
        self._position = position

    async def evaluate(self, days: int = 60) -> DecisionOut:
        """生成 ETF 购买决策。

        Args:
            days: 趋势指数覆盖的交易日数量

        Returns:
            决策输出（行动 + 置信度 + 理由明细）

        Raises:
            ValueError: 趋势数据不足
        """
        trend = await self._trend.analyze(days=days)
        pos = await self._position.summary()

        action, confidence = self._decide(trend.index.score, pos.pnl_pct, pos.has_position)
        reasons = self._build_reasons(action, trend, pos)
        summary = self._summarize(action, confidence, trend, pos)

        logger.info(
            "Decision: %s (conf=%s) idx=%.1f has_pos=%s pnl=%.1f%%",
            action, confidence, trend.index.score, pos.has_position, pos.pnl_pct,
        )
        return DecisionOut(
            action=action,
            action_label=_ACTION_LABELS[action],
            confidence=confidence,
            signal_summary=f"趋势评估指数 {trend.index.score:.1f}/100 · {_LEVEL_LABELS[trend.index.level.value]}",
            trend_index=trend.index,
            position=pos,
            reasons=reasons,
            summary=summary,
        )

    # ---------------- 规则判定 ----------------

    @staticmethod
    def _decide(idx: float, pnl_pct: float, has_position: bool) -> tuple[str, str]:
        """核心规则：指数 + 持仓盈亏 → (行动, 置信度)。"""
        if not has_position:
            if idx >= 70:
                return "BUY", "high"
            if idx >= 55:
                return "BUY", "medium"
            if idx >= 45:
                return "WAIT", "low"
            return "WAIT", "medium"

        # 有持仓：先处理止盈/止损，再按趋势决策
        if pnl_pct >= 15 and idx < 60:
            return "SELL", "high"  # 浮盈显著且趋势转弱 → 止盈
        if pnl_pct <= -10 and idx < 40:
            return "REDUCE", "high"  # 浮亏显著且趋势弱势 → 止损减仓
        if idx >= 70:
            return "ADD", "high"
        if idx >= 55:
            return "HOLD", "medium"
        if idx >= 45:
            return "HOLD", "low"
        return "REDUCE", "medium"

    def _build_reasons(
        self,
        action: str,
        trend: object,
        pos: object,
    ) -> list[str]:
        """生成面向客户的中文决策理由明细。"""
        idx = trend.index.score
        level = _LEVEL_LABELS[trend.index.level.value]
        reasons = [
            f"参数面：趋势评估指数 {idx:.1f}/100，等级【{level}】",
        ]
        if pos.has_position:
            reasons.append(
                f"交易面：持仓 {pos.quantity:.0f} 份，成本 {pos.avg_cost:.3f} 元，"
                f"浮动盈亏 {pos.pnl:+.2f} 元（{pos.pnl_pct:+.2f}%）"
            )
        else:
            reasons.append("交易面：当前无持仓")

        rule_hint = {
            "BUY": "趋势走强且无持仓，具备建仓条件",
            "ADD": "趋势强劲且已有盈利/仓位，可顺势加仓",
            "HOLD": "趋势方向未破坏，继续持有观察",
            "REDUCE": "趋势转弱或亏损扩大，建议逢高减仓控制风险",
            "SELL": "浮盈可观且趋势动能衰减，建议止盈兑现",
            "WAIT": "信号不明或趋势偏弱，观望等待更优时机",
        }[action]
        reasons.append(f"决策依据：{rule_hint}")
        return reasons

    @staticmethod
    def _summarize(
        action: str,
        confidence: str,
        trend: object,
        pos: object,
    ) -> str:
        """决策总结句。"""
        conf_txt = {"high": "高置信", "medium": "中置信", "low": "低置信"}[confidence]
        return (
            f"建议【{_ACTION_LABELS[action]}】({conf_txt})："
            f"趋势指数 {trend.index.score:.1f}/100，"
            f"{'持仓浮盈 ' + format(pos.pnl_pct, '+.2f') + '%' if pos.has_position else '当前空仓'}，"
            f"详见理由明细"
        )
