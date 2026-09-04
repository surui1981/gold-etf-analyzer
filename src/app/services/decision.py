"""购买决策引擎：参数面信号（趋势指数） × 交易面状态（持仓盈亏） → ETF 购买决策。

规则为典型经验（rule-based），集中在 ``DecisionService`` 内，可按策略调整；
后续 P2 将叠加宏观机会评分形成「宏观 × 技术」双维度共振。
"""

from app.schemas.position import DecisionOut, ReasonItem
from app.services.position import PositionService
from app.services.trend import GUIDE_TARGET, TrendService
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
    """决策引擎：综合趋势指数与持仓状态输出购买建议。

    指引基准默认为纽约金（COMEX GC）——连续交易、夜盘覆盖国内休市时段，
    对国内金价（ETF / 上海金）具备领先指示意义；持仓与交易仍以人民币 ETF 计。
    """

    def __init__(
        self,
        trend: TrendService,
        position: PositionService,
    ) -> None:
        self._trend = trend
        self._position = position

    async def evaluate(self, days: int = 60, target: str = GUIDE_TARGET) -> DecisionOut:
        """生成黄金购买决策。

        Args:
            days: 趋势指数覆盖的交易日数量
            target: 指引标的类型，ny（纽约金，默认）/ etf / gram

        Returns:
            决策输出（行动 + 置信度 + 理由明细）

        Raises:
            ValueError: 趋势数据不足
        """
        trend = await self._trend.analyze(days=days, target=target)
        pos = await self._position.summary()

        action, confidence = self._decide(trend.index.score, pos.pnl_pct, pos.has_position)
        suggested_position, position_level = self._suggest_position(trend.index.score)
        reason_items = self._build_reason_items(action, trend, pos, suggested_position, position_level)
        summary = self._summarize(action, confidence, trend, pos)

        logger.info(
            "Decision: %s (conf=%s) idx=%.1f pos_ratio=%.0f%% has_pos=%s pnl=%.1f%%",
            action, confidence, trend.index.score, suggested_position, pos.has_position, pos.pnl_pct,
        )
        return DecisionOut(
            action=action,
            action_label=_ACTION_LABELS[action],
            confidence=confidence,
            signal_summary=f"趋势评估指数 {trend.index.score:.1f}/100 · {_LEVEL_LABELS[trend.index.level.value]}",
            trend_index=trend.index,
            position=pos,
            suggested_position=suggested_position,
            position_level=position_level,
            reasons=[r.text for r in reason_items],
            reason_items=reason_items,
            summary=summary,
        )

    # ---------------- 仓位推荐 ----------------

    @staticmethod
    def _suggest_position(idx: float) -> tuple[float, str]:
        """由综合评估指数映射建议黄金仓位（0-100%）与等级。

        分段：≥75 重仓 80% ｜ ≥55 中高 60% ｜ ≥45 中性 40% ｜ ≥25 轻仓 20% ｜ <25 观望 10%。
        """
        if idx >= 75:
            return 80.0, "重仓"
        if idx >= 55:
            return 60.0, "中高仓位"
        if idx >= 45:
            return 40.0, "中性仓位"
        if idx >= 25:
            return 20.0, "轻仓"
        return 10.0, "观望空仓"

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

    def _build_reason_items(
        self,
        action: str,
        trend: object,
        pos: object,
        suggested_position: float,
        position_level: str,
    ) -> list[ReasonItem]:
        """生成面向客户的结构化决策理由（含利多/利空方向标记）。

        方向约定（红=利多/看多黄金 bullish，绿=利空/看空黄金 bearish，灰=中性）：
        - 参数面：跟随趋势指数方向；
        - 交易面：持仓浮盈→利多，浮亏→利空，无持仓→中性；
        - 决策依据：建仓/加仓→利多，止盈/减仓→利空，持有/观望→中性；
        - 仓位建议：指数偏高（≥55）→利多，偏低（≤40）→利空，其余中性。
        """
        idx = trend.index.score
        level = _LEVEL_LABELS[trend.index.level.value]
        # 指数方向：score 高→利多，低→利空，中间→中性
        if idx >= 55:
            idx_dir = "bullish"
        elif idx <= 40:
            idx_dir = "bearish"
        else:
            idx_dir = "neutral"

        items: list[ReasonItem] = [
            ReasonItem(
                text=f"参数面：趋势评估指数 {idx:.1f}/100，等级【{level}】",
                direction=idx_dir,
            ),
        ]
        if pos.has_position:
            trade_dir = "bullish" if pos.pnl_pct > 0 else "bearish" if pos.pnl_pct < 0 else "neutral"
            items.append(
                ReasonItem(
                    text=(
                        f"交易面：持仓 {pos.quantity:.0f} 份，成本 {pos.avg_cost:.3f} 元，"
                        f"浮动盈亏 {pos.pnl:+.2f} 元（{pos.pnl_pct:+.2f}%）"
                    ),
                    direction=trade_dir,
                )
            )
        else:
            items.append(ReasonItem(text="交易面：当前无持仓", direction="neutral"))

        rule_hint = {
            "BUY": "趋势走强且无持仓，具备建仓条件",
            "ADD": "趋势强劲且已有盈利/仓位，可顺势加仓",
            "HOLD": "趋势方向未破坏，继续持有观察",
            "REDUCE": "趋势转弱或亏损扩大，建议逢高减仓控制风险",
            "SELL": "浮盈可观且趋势动能衰减，建议止盈兑现",
            "WAIT": "信号不明或趋势偏弱，观望等待更优时机",
        }[action]
        action_dir = {"BUY": "bullish", "ADD": "bullish", "SELL": "bearish",
                      "REDUCE": "bearish", "HOLD": "neutral", "WAIT": "neutral"}[action]
        items.append(ReasonItem(text=f"决策依据：{rule_hint}", direction=action_dir))

        items.append(
            ReasonItem(
                text=(
                    f"仓位建议：评估指数 {idx:.1f}/100 → 建议黄金仓位 {suggested_position:.0f}%（{position_level}）"
                ),
                direction=idx_dir,
            )
        )
        return items

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
