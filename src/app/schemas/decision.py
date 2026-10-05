"""V0.78.0：决策行动枚举。

V0.77.2 决策行动用裸字符串字面量（``"BUY"`` / ``"ADD"`` 等），
存在三个问题：
1. 没有类型约束 —— 输入 ``"BUY_HAVY"``（拼写错误）也能通过
2. 跨模块（API / 前端 / 测试）靠字符串约定，IDE 无法补全与校验
3. 新增档位（如 ``BUY_HEAVY`` / ``BUY_LIGHT`` / ``HOLD_CAUTIOUS``）无统一来源

V0.78.0 起统一为 ``DecisionAction`` 枚举（``str, Enum`` 混合）：

- 字符串兼容：``DecisionAction.BUY == "BUY"`` 成立，现有测试零修改
- Pydantic v2 序列化：自动输出 ``.value``（即字符串字面量）
- 前端 ``ACTION_STYLE[d.action]`` 仍按字符串查表（值不变）

档位语义（V0.78.0 新增）：
- ``BUY_HEAVY`` ≥ 75 分 → 重仓买入（80%）
- ``BUY`` ≥ 65 分 → 普通买入（60%）
- ``BUY_LIGHT`` ≥ 55 分 → 轻仓试仓（30%，用于消除 [60,70)×[-10%,+15%] 卡死区）
- ``HOLD_CAUTIOUS`` ≥ 40 分 → 观望持有（新增缓冲档，替代原 idx [40,45) 直接 REDUCE）
"""
from enum import StrEnum


class DecisionAction(StrEnum):
    """决策行动枚举（``StrEnum``，与项目其它枚举一致）。

    修改枚举时同步：
    1. ``schemas/position.py::DecisionOut.action`` 字段类型
    2. ``services/decision.py:_ACTION_LABELS`` 中文标签
    3. ``static/portfolio.html::ACTION_STYLE`` 与 ``_ACTION_FALLBACK``
    4. i18n 三语 ``dict.zh-CN.json`` / ``dict.zh-TW.json`` / ``dict.en-US.json``
       （key: ``portfolio.action_<value>``）
    """

    # 无持仓分支（按综合指数分档）
    BUY_HEAVY = "BUY_HEAVY"   # ≥ 75 重仓买入（80%）
    BUY = "BUY"               # ≥ 65 普通买入（60%）
    BUY_LIGHT = "BUY_LIGHT"   # ≥ 55 轻仓试仓（30%）
    WAIT = "WAIT"             # < 55 观望

    # 有持仓分支（按 pnl + idx 组合）
    ADD = "ADD"               # ≥ 75 加仓
    HOLD = "HOLD"             # ≥ 55 持有
    HOLD_CAUTIOUS = "HOLD_CAUTIOUS"   # ≥ 40 观望持有（新增缓冲档）
    REDUCE = "REDUCE"         # < 40 或止损条件
    SELL = "SELL"             # 止盈条件