"""共振信号 Schema（V0.70.0 P2 #7）。

设计目标：把宏观、技术、消息面三维度方向打包成一张易读的「共振卡」，
直接挂在 trend 页面顶部；命中统计供复盘。

4 类信号
--------
- ``STRONG_UP``：三面同向看多（≥55）→ 强共振；
- ``STRONG_DOWN``：三面同向看空（≤45）→ 强反向；
- ``WEAK_UP``：三面中 2 维看多 → 弱多信号；
- ``DIVERGENT``：任意两维背离（幅度 ≥ 15，V0.78.0 起含消息面维度）；
- ``NEUTRAL``：其他 → 中性。

V0.78.0 变更
-----------
``DIVERGENT`` 原实现只识别「技术 vs 宏观」，且要求两者**方向相反**
（tech ≥ 55 且 macro ≤ 45）。这会漏掉「消息面已看多、技术仍看空」这类
典型反转先行信号（消息面是客户主观判断的投行展望，常领先于技术面），
整类信号被误判为 ``neutral``——依据见 ``docs/parameter-evaluation.md`` §3.5。

现改为**三维任意一对的背离幅度 ≥ 15** 即触发，并用 ``subtype`` 标明具体维度对
（``tech_macro`` / ``tech_news`` / ``macro_news``），前端可据此说明是哪两维在打架。
"""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class DivergentSubtype(StrEnum):
    """``DIVERGENT`` 的背离维度对（V0.78.0，``docs/parameter-evaluation.md`` §3.5）。

    用 ``StrEnum``（而非 ``str, Enum``，ruff UP042 会拒）：JSON 序列化直接得到
    字符串字面量，且 ``==`` 与裸字符串比较成立，前端无需转换。与
    ``DecisionAction`` 保持同一约定。
    """

    TECH_MACRO = "tech_macro"
    TECH_NEWS = "tech_news"
    MACRO_NEWS = "macro_news"


#: 背离维度对 -> 中文说明（服务端直出，前端无需再维护一份映射）
DIVERGENT_SUBTYPE_LABELS: dict[str, str] = {
    DivergentSubtype.TECH_MACRO.value: "技术面 vs 宏观面",
    DivergentSubtype.TECH_NEWS.value: "技术面 vs 消息面",
    DivergentSubtype.MACRO_NEWS.value: "宏观面 vs 消息面",
}


class ResonanceSignalOut(BaseModel):
    """单日共振信号输出。"""

    score_date: date | None = Field(None, description="日期（signal_today 为今日）")
    signal: str = Field(..., description="strong_up / strong_down / weak_up / divergent / neutral")
    label: str = Field(..., description="中文信号名")
    subtype: DivergentSubtype | None = Field(
        None,
        description="背离维度对（仅 signal=divergent 时有值）；V0.78.0 新增",
    )
    subtype_label: str = Field(
        "",
        description="背离维度对中文说明（仅 signal=divergent 时有值，服务端直出供前端展示）",
    )
    confidence: float = Field(..., ge=0, le=100, description="置信度 0-100")
    components: dict[str, float] = Field(
        default_factory=dict,
        description="三维度分值 components: tech / macro / news",
    )
    direction_summary: str = Field(..., description="三维度方向的中文一句话总结（红绿着色用）")


class ResonanceHistoryOut(BaseModel):
    """共振信号历史（按日期倒序）。"""

    days: int
    total: int
    items: list[ResonanceSignalOut] = Field(default_factory=list)


class StrengthUpStatsOut(BaseModel):
    """STRONG_UP 命中统计：当日「强共振看多」在 T+H 的命中率。

    复用 ``ReviewService._build_days`` 的对齐逻辑（基准日 + T+H 收盘对比），
    仅过滤条件改为「当日共振信号 = strong_up」而非「方向」。
    """

    model_config = ConfigDict(extra="forbid")

    days: int
    horizon: int
    total_strong_up: int = Field(..., description="窗口内 STRONG_UP 信号的天数")
    resolved: int = Field(..., description="已到 T+H 可对比的天数")
    hits: int = Field(..., description="命中（看多 + 实际上涨）天数")
    hit_rate: float | None = Field(None, description="命中率 %")
    sample_warning: bool = Field(False, description="样本不足 20 时为 True")
    note: str = Field("", description="人类可读说明")
