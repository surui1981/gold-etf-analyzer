"""公共枚举：投资窗口与方向信号。"""

from enum import StrEnum


class OpportunityWindow(StrEnum):
    """投资机会窗口分级。"""

    STRONG = "strong"  # 强机会窗口
    MEDIUM = "medium"  # 中等机会
    WEAK = "weak"  # 弱机会
    STANDBY = "standby"  # 观望


class DirectionSignal(StrEnum):
    """因子/总评的方向信号（相对黄金而言）。"""

    BULLISH = "bullish"  # 利多黄金
    BEARISH = "bearish"  # 利空黄金
    NEUTRAL = "neutral"  # 中性
