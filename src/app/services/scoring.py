"""黄金ETF交易机会评分引擎。

核心思路（延续 PM-Evaluator 的预期评估架构）：
对宏观因子按「典型经验」赋权，将每个因子值线性映射为 0-100 的
黄金友好度（友好度越高越利多黄金），加权求和得到综合机会评分，
再映射为投资窗口与方向信号。

注意：此处权重与中枢均为可调的经验参数（rule-based），
后续可用历史行情回归或机器学习校准，接口保持不变。
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from app.schemas.analysis import FactorSignal, OpportunityResponse
from app.schemas.common import DirectionSignal, OpportunityWindow
from app.schemas.factors import MacroFactorInput


@dataclass(frozen=True)
class FactorRule:
    """单个因子的评分规则。

    Attributes:
        key: 因子字段名（与 MacroFactorInput 对齐）
        label: 展示用中文名
        weight: 权重（总和须为 1）
        lower: 友好度 = 100 时对应的因子值
        upper: 友好度 = 0 时对应的因子值
               （lower > upper 表示该因子与黄金正相关，反之负相关）
    """

    key: str
    label: str
    weight: float
    lower: float
    upper: float


# 典型经验参数：实际利率权重最高（黄金不生息，机会成本主导金价）
FACTOR_RULES: tuple[FactorRule, ...] = (
    FactorRule(key="real_rate", label="实际利率", weight=0.35, lower=1.5, upper=2.5),
    FactorRule(key="dxy", label="美元指数", weight=0.30, lower=95.0, upper=105.0),
    FactorRule(key="us10y_yield", label="美债10Y收益率", weight=0.15, lower=3.5, upper=4.5),
    FactorRule(key="inflation_expectation", label="通胀预期", weight=0.10, lower=3.0, upper=2.0),
    FactorRule(key="risk_off", label="避险情绪", weight=0.10, lower=10.0, upper=0.0),
)

# 启动即校验权重配置，防止手误导致评分失真
_WEIGHT_SUM = sum(r.weight for r in FACTOR_RULES)
assert abs(_WEIGHT_SUM - 1.0) < 1e-6, f"因子权重之和必须为 1，当前为 {_WEIGHT_SUM}"

# 方向信号阈值（按友好度判定单因子多空）
_BULLISH_THRESHOLD = 55.0
_BEARISH_THRESHOLD = 45.0


class OpportunityScoringService:
    """无状态评分引擎：输入宏观因子，输出机会评分与投资窗口。"""

    def evaluate(self, factors: MacroFactorInput) -> OpportunityResponse:
        """对一组宏观因子执行加权评分。

        Args:
            factors: 宏观因子输入

        Returns:
            OpportunityResponse：综合评分、窗口、方向与逐因子明细
        """
        values: dict[str, float] = {
            "dxy": factors.dxy,
            "us10y_yield": factors.us10y_yield,
            "real_rate": factors.real_rate,
            "inflation_expectation": factors.inflation_expectation,
            "risk_off": float(factors.risk_off),
        }

        signals: list[FactorSignal] = []
        total = 0.0
        for rule in FACTOR_RULES:
            friendly = self._friendly_score(values[rule.key], rule)
            contribution = friendly * rule.weight
            total += contribution
            signals.append(
                FactorSignal(
                    factor=rule.key,
                    value=values[rule.key],
                    direction=self._to_direction(friendly),
                    weight=rule.weight,
                    contribution=round(contribution, 2),
                    reason=self._reason(rule, friendly),
                )
            )

        score = round(total, 2)
        return OpportunityResponse(
            score=score,
            window=self._to_window(score),
            signal=self._to_signal(score),
            summary=self._summarize(score),
            factors=signals,
            timestamp=datetime.now(timezone.utc),
        )

    @staticmethod
    def _friendly_score(value: float, rule: FactorRule) -> float:
        """因子值 → 0-100 黄金友好度（线性插值 + 边界截断）。

        正相关因子（lower > upper）：值越高友好度越高；
        负相关因子（lower < upper）：值越高友好度越低。
        """
        span = rule.lower - rule.upper
        if span == 0:  # 规则配置异常时给中性分，避免除零
            return 50.0
        raw = (value - rule.upper) / span
        return max(0.0, min(1.0, raw)) * 100.0

    @classmethod
    def _to_direction(cls, friendly: float) -> DirectionSignal:
        """友好度 → 单因子方向信号（相对黄金）。"""
        if friendly >= _BULLISH_THRESHOLD:
            return DirectionSignal.BULLISH
        if friendly <= _BEARISH_THRESHOLD:
            return DirectionSignal.BEARISH
        return DirectionSignal.NEUTRAL

    @staticmethod
    def _to_window(score: float) -> OpportunityWindow:
        """综合评分 → 投资窗口分级。"""
        if score >= 70:
            return OpportunityWindow.STRONG
        if score >= 55:
            return OpportunityWindow.MEDIUM
        if score >= 40:
            return OpportunityWindow.WEAK
        return OpportunityWindow.STANDBY

    @staticmethod
    def _to_signal(score: float) -> DirectionSignal:
        """综合评分 → 总体方向信号。"""
        if score >= 60:
            return DirectionSignal.BULLISH
        if score <= 40:
            return DirectionSignal.BEARISH
        return DirectionSignal.NEUTRAL

    @staticmethod
    def _reason(rule: FactorRule, friendly: float) -> str:
        """生成单因子信号解释文案。"""
        if friendly >= _BULLISH_THRESHOLD:
            return f"{rule.label}处于利多区间（友好度 {friendly:.0f}），构成黄金利多支撑"
        if friendly <= _BEARISH_THRESHOLD:
            return f"{rule.label}处于利空区间（友好度 {friendly:.0f}），形成黄金利空压力"
        return f"{rule.label}处于中性区间（友好度 {friendly:.0f}），影响有限"

    @staticmethod
    def _summarize(score: float) -> str:
        """生成一句话结论。"""
        if score >= 70:
            return (
                f"综合评分 {score:.1f}/100：宏观环境显著利多黄金，"
                "处于强机会窗口，可积极布局黄金ETF"
            )
        if score >= 55:
            return f"综合评分 {score:.1f}/100：中等机会窗口，建议逢低分批配置黄金ETF"
        if score >= 40:
            return f"综合评分 {score:.1f}/100：弱机会窗口，观望或轻仓试探为宜"
        return f"综合评分 {score:.1f}/100：宏观环境压制黄金，建议观望等待信号反转"
