"""购买决策引擎：参数面信号（趋势指数） × 交易面状态（持仓盈亏） → ETF 购买决策。

规则为典型经验（rule-based），集中在 ``DecisionService`` 内，可按策略调整；
后续 P2 将叠加宏观机会评分形成「宏观 × 技术」双维度共振。

V0.78.0 决策矩阵档位补全（Step B）：
- BUY 拆 3 档：``BUY_HEAVY``（≥75, 80%）/ ``BUY``（≥65, 60%）/ ``BUY_LIGHT``（≥55, 30%）
- 新增 ``HOLD_CAUTIOUS``（idx [40, 45)，观望持有缓冲档）
- 消除 idx [60, 70) × pnl [-10%, +15%] 卡死区
- 决策行动统一为 ``DecisionAction`` 枚举（``schemas/decision.py``）
"""

from app.schemas.decision import DecisionAction
from app.schemas.position import DecisionOut, ReasonItem
from app.schemas.thresholds import DecisionThreshold
from app.services.position import PositionService
from app.services.trend import GUIDE_TARGET, TrendService
from app.utils.logger import get_logger

logger = get_logger(__name__)

_ACTION_LABELS = {
    DecisionAction.BUY_HEAVY: "重仓买入",
    DecisionAction.BUY: "买入",
    DecisionAction.BUY_LIGHT: "轻仓试仓",
    DecisionAction.ADD: "加仓",
    DecisionAction.HOLD: "持有",
    DecisionAction.HOLD_CAUTIOUS: "观望持有",
    DecisionAction.REDUCE: "减仓",
    DecisionAction.SELL: "卖出",
    DecisionAction.WAIT: "观望",
}

_LEVEL_LABELS = {
    "strong_up": "强势上升",
    "up": "上升",
    "sideways": "震荡整理",
    "down": "下降",
    "strong_down": "弱势下降",
}

# V0.71.0：target → 品种中文名（用于资产文案切换，黄金/白银共享仓位建议口径）
_TARGET_LABELS = {
    "ny": "纽约黄金",
    "etf": "黄金ETF",
    "gram": "上海金克价",
    "silver_ny": "纽约白银",
    "silver_etf": "白银ETF",
    "silver_gram": "白银克价",  # V0.73.0 N+16：白银克价（ETF × 1000 推导）
}


def target_label(target: str) -> str:
    """target → 品种中文名（V0.71.0 黄金/白银共享接口文案切换）。

    未知 target 回退「黄金ETF」以保持 V0.70.0 行为兼容。
    """
    return _TARGET_LABELS.get(target or "", "黄金ETF")


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

    async def evaluate(
        self, days: int = 60, target: str = GUIDE_TARGET, account_id: int | None = None
    ) -> DecisionOut:
        """生成购买决策（V0.71.0 起支持黄金/白银双资产类共享接口）。

        Args:
            days: 趋势指数覆盖的交易日数量
            target: 指引标的类型，ny（纽约金，默认）/ etf / gram /
                silver_etf（V0.71.0 白银 ETF）/ silver_ny（V0.71.0 纽约白银）
            account_id: 账本过滤；None=全部账本（持仓摘要按合并口径）

        Returns:
            决策输出（行动 + 置信度 + 理由明细）。白银场景下，
            文案「建议黄金仓位」自动切换为「建议白银仓位」。

        Raises:
            ValueError: 趋势数据不足
        """
        trend = await self._trend.analyze(days=days, target=target)
        pos = await self._position.summary(account_id=account_id)

        action, confidence = self._decide(trend.index.score, pos.pnl_pct, pos.has_position)
        suggested_position, position_level = self._suggest_position(trend.index.score)
        reason_items = self._build_reason_items(
            action, trend, pos, suggested_position, position_level, target=target
        )
        summary = self._summarize(action, confidence, trend, pos, target=target)

        logger.info(
            "Decision: %s (conf=%s) idx=%.1f pos_ratio=%.0f%% has_pos=%s pnl=%.1f%%",
            action,
            confidence,
            trend.index.score,
            suggested_position,
            pos.has_position,
            pos.pnl_pct,
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
    def _decide(
        idx: float, pnl_pct: float, has_position: bool
    ) -> tuple[DecisionAction, str]:
        """核心规则：指数 + 持仓盈亏 → (行动, 置信度)。

        V0.78.0 重写（Step B）：
        - BUY 拆 3 档（BUY_HEAVY / BUY / BUY_LIGHT），与仓位推荐档位对齐
        - 新增 HOLD_CAUTIOUS（idx [40, 45)）缓冲档，避免直接 REDUCE 过激
        - 消除 idx [60, 70) × pnl [-10%, +15%] 卡死区（落入 HOLD / HOLD_CAUTIOUS）
        - 阈值统一读 DecisionThreshold
        """
        if not has_position:
            # 无持仓：BUY 拆 3 档（与仓位推荐档位对齐：80% / 60% / 30%）
            if idx >= DecisionThreshold.BUY_HEAVY:    # ≥ 75
                return DecisionAction.BUY_HEAVY, "high"
            if idx >= DecisionThreshold.BUY:          # ≥ 65
                return DecisionAction.BUY, "high"
            if idx >= DecisionThreshold.BUY_LIGHT:    # ≥ 55
                return DecisionAction.BUY_LIGHT, "medium"
            if idx >= DecisionThreshold.HOLD:         # ≥ 50
                return DecisionAction.WAIT, "low"
            return DecisionAction.WAIT, "medium"

        # 有持仓：先处理止盈/止损，再按趋势决策
        assert pnl_pct is not None
        if pnl_pct >= 15 and idx < 60:
            return DecisionAction.SELL, "high"   # 浮盈显著且趋势转弱 → 止盈
        if pnl_pct <= -10 and idx < 40:
            return DecisionAction.REDUCE, "high"  # 浮亏显著且趋势弱势 → 止损减仓
        if idx >= DecisionThreshold.BUY_HEAVY:    # ≥ 75
            return DecisionAction.ADD, "high"
        if idx >= DecisionThreshold.BUY_LIGHT:    # ≥ 55
            return DecisionAction.HOLD, "medium"
        if idx >= DecisionThreshold.HOLD_LOW:     # ≥ 40  ← 新增缓冲档
            return DecisionAction.HOLD_CAUTIOUS, "low"
        return DecisionAction.REDUCE, "medium"

    def _build_reason_items(
        self,
        action: DecisionAction,
        trend: object,
        pos: object,
        suggested_position: float,
        position_level: str,
        target: str = GUIDE_TARGET,
    ) -> list[ReasonItem]:
        """生成面向客户的结构化决策理由（含利多/利空方向标记）。

        方向约定（红=利多/看多 bullish，绿=利空/看空 bearish，灰=中性）：
        - 参数面：跟随趋势指数方向；
        - 交易面：持仓浮盈→利多，浮亏→利空，无持仓→中性；
        - 决策依据：建仓/加仓→利多，止盈/减仓→利空，持有/观望→中性；
        - 仓位建议：指数偏高（≥55）→利多，偏低（≤40）→利空，其余中性。

        V0.71.0：仓位建议文案由「建议黄金仓位」切换为「建议{target_label(target)}仓位」，
        黄金/白银共享同一决策逻辑，仅品种名按 target 字段动态渲染。
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
            trade_dir = (
                "bullish" if pos.pnl_pct > 0 else "bearish" if pos.pnl_pct < 0 else "neutral"
            )
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
            DecisionAction.BUY_HEAVY: "趋势走强且无持仓，具备重仓建仓条件",
            DecisionAction.BUY: "趋势走强且无持仓，具备建仓条件",
            DecisionAction.BUY_LIGHT: "趋势温和偏多，建议轻仓试仓",
            DecisionAction.ADD: "趋势强劲且已有盈利/仓位，可顺势加仓",
            DecisionAction.HOLD: "趋势方向未破坏，继续持有观察",
            DecisionAction.HOLD_CAUTIOUS: "趋势转弱但未破位，观望持有等待方向确认",
            DecisionAction.REDUCE: "趋势转弱或亏损扩大，建议逢高减仓控制风险",
            DecisionAction.SELL: "浮盈可观且趋势动能衰减，建议止盈兑现",
            DecisionAction.WAIT: "信号不明或趋势偏弱，观望等待更优时机",
        }[action]
        action_dir = {
            DecisionAction.BUY_HEAVY: "bullish",
            DecisionAction.BUY: "bullish",
            DecisionAction.BUY_LIGHT: "bullish",
            DecisionAction.ADD: "bullish",
            DecisionAction.SELL: "bearish",
            DecisionAction.REDUCE: "bearish",
            DecisionAction.HOLD: "neutral",
            DecisionAction.HOLD_CAUTIOUS: "neutral",
            DecisionAction.WAIT: "neutral",
        }[action]
        items.append(ReasonItem(text=f"决策依据：{rule_hint}", direction=action_dir))

        asset_label = target_label(target)  # V0.71.0：黄金/白银共享口径，仅文案切换
        items.append(
            ReasonItem(
                text=(
                    f"仓位建议：评估指数 {idx:.1f}/100 → 建议{asset_label}仓位 {suggested_position:.0f}%（{position_level}）"
                ),
                direction=idx_dir,
            )
        )
        return items

    @staticmethod
    def _summarize(
        action: DecisionAction,
        confidence: str,
        trend: object,
        pos: object,
        target: str = GUIDE_TARGET,
    ) -> str:
        """决策总结句。

        V0.71.0：target 参数传入后，summary 文案中的品种名随之切换（黄金/白银）；
        V0.70.0 及更早版本不传 target，自动走默认 GUIDE_TARGET="ny" 渲染「黄金」。
        """
        conf_txt = {"high": "高置信", "medium": "中置信", "low": "低置信"}[confidence]
        return (
            f"建议【{_ACTION_LABELS[action]}】({conf_txt})："
            f"趋势指数 {trend.index.score:.1f}/100，"
            f"{'持仓浮盈 ' + format(pos.pnl_pct, '+.2f') + '%' if pos.has_position else '当前空仓'}，"
            f"详见理由明细"
        )
