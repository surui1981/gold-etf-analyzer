"""共振信号 Schema（V0.70.0 P2 #7）。

设计目标：把宏观、技术、消息面三维度方向打包成一张易读的「共振卡」，
直接挂在 trend 页面顶部；命中统计供复盘。

4 类信号
--------
- ``STRONG_UP``：三面同向看多（≥55）→ 强共振；
- ``STRONG_DOWN``：三面同向看空（≤45）→ 强反向；
- ``WEAK_UP``：三面中 2 维看多 → 弱多信号；
- ``DIVERGENT``：技术 / 宏观 反向（典型反转信号）；
- ``NEUTRAL``：其他 → 中性。
"""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class ResonanceSignalOut(BaseModel):
    """单日共振信号输出。"""

    score_date: date | None = Field(None, description="日期（signal_today 为今日）")
    signal: str = Field(..., description="strong_up / strong_down / weak_up / divergent / neutral")
    label: str = Field(..., description="中文信号名")
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
