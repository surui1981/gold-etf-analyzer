"""集中管理 0-100 分制下的方向/等级/决策阈值常量。

V0.78.0 新增：消除 5 个模块（消息面 / 单维度 / 综合指数等级 / 决策矩阵 / 共振信号）
里硬编码阈值（55/45/60/40/70/25）的口径冲突。

使用场景：
- ``DirectionThreshold`` —— 方向判定（消息面 > 55 看多、共振 ≥ 55 BULLISH、单维度 ≥ 60 BULLISH）
- ``LevelThreshold`` —— 综合指数 → 等级映射（含端点）
- ``DecisionThreshold`` —— 决策矩阵档位（BUY 拆 3 档 + HOLD 缓冲档）

修改此文件的常量前，请用 parameter-evaluation.md §6.2 的三维交叉验证方法
（Sharpe + 最大回撤 + 命中率/校准）评估新值的实际效果。
"""
from enum import IntEnum


class DirectionThreshold(IntEnum):
    """方向判定阈值（与 0-100 分制对齐）。

    字段语义：
    - ``STRONG_BULLISH`` ≥ 此值 → 强多（决策 BUY_HEAVY 触发）
    - ``BULLISH`` 严格大于此值 → 看多（消息面、共振信号）
    - ``NEUTRAL_HIGH`` ≥ 此值 → 单维度方向判定 BULLISH（比 BULLISH 严格一档）
    - ``NEUTRAL_LOW`` ≤ 此值 → 单维度方向判定 BEARISH
    - ``BEARISH`` 严格小于此值 → 看空（消息面、共振信号）
    - ``STRONG_BEARISH`` < 此值 → 综合指数 STRONG_DOWN 触发
    """

    STRONG_BULLISH = 70   # 强多（决策 BUY_HEAVY 触发）
    BULLISH = 55          # 看多（消息面 > 55、共振 ≥ 55）
    NEUTRAL_HIGH = 60     # 中性偏上（单维度方向判定）
    NEUTRAL_LOW = 40      # 中性偏下（单维度方向判定）
    BEARISH = 45          # 看空（消息面 < 45、共振 ≤ 45）
    STRONG_BEARISH = 25   # 弱势下降（综合指数 STRONG_DOWN 触发）


class LevelThreshold(IntEnum):
    """综合指数等级阈值（含端点，与 ``_to_level`` 对齐）。

    注意：等级阈值与 ``DirectionThreshold.BULLISH/BEARISH`` 共用 55/45，
    但等级用「含端点」(≥55 = UP)，消息面用「严格不等号」(>55 = 看多)。
    这不是冲突：UP 是综合指数等级，BULLISH 是单次打分方向，两者口径不同。
    """

    STRONG_UP = 75   # ≥ 75 强势上升
    UP = 55          # ≥ 55 上升
    SIDEWAYS = 45    # ≥ 45 震荡整理
    DOWN = 25        # ≥ 25 下降
    # < 25 弱势下降（STRONG_DOWN）


class DecisionThreshold(IntEnum):
    """决策矩阵档位阈值。

    V0.78.0 新设计：
    - BUY 拆 3 档：HEAVY (≥75, 80%) / 普通 (≥65, 60%) / LIGHT (≥55, 30%)
    - HOLD 拆 2 档：HOLD (≥55, medium) / HOLD_LOW 缓冲 (≥40, low, 新增)
    - REDUCE < 40
    """

    BUY_HEAVY = 75        # ≥ 75 重仓买入（80%）
    BUY = 65              # ≥ 65 普通买入（60%）
    BUY_LIGHT = 55        # ≥ 55 轻仓试仓（30%）
    HOLD = 50             # ≥ 50 持有观望
    HOLD_LOW = 40         # ≥ 40 观望持有（新增缓冲档）
    # < 40 减仓
