"""COMEX 黄金库存输出 schema。"""

from datetime import date

from pydantic import BaseModel, Field


class GoldInventoryPoint(BaseModel):
    """单日库存观测。"""

    # ⚠ `date` 这个**字段名**会遮蔽 `datetime.date` 类型名，所以这里只能写裸注解、
    # 不能给默认值（`date: date = Field(...)` 会让 pydantic 报
    # "field name clashing with a type annotation"）。
    # `schemas/market.py` 的 `GoldTrendPoint.date` 同样如此，两处口径一致。
    date: date
    tonnes: float = Field(..., description="COMEX 黄金库存（吨）")


class GoldInventoryChange(BaseModel):
    """一段回看窗口的变化率。

    ⚠ 三个字段都是 ``| None``：回看窗口内**没有基线点**时返回 None 而不是 0。
    「没数据」与「没变化」在投资语境里是两件相反的事 —— 把缺基线算成 0% 等于
    告诉用户「库存持平」，那是编数据（V0.78.0 NULL 纪律）。
    """

    window: str = Field(..., description="窗口标识：1w / 1m / 3m / 1y")
    days: int = Field(..., description="回看自然日数")
    base_date: date | None = Field(None, description="基线日期；窗口内无数据则 None")
    change_pct: float | None = Field(None, description="变化率 %；无基线则 None")


class GoldInventoryOut(BaseModel):
    """COMEX 黄金库存序列 + 多窗口变化率。"""

    source: str = Field("COMEX", description="数据源标识")
    unit: str = Field("吨", description="库存单位")
    # 同 GoldInventoryPoint.date：`date` 被字段名遮蔽，只能裸注解 + None 默认
    as_of: date | None = None
    latest_tonnes: float | None = Field(None, description="最新库存（吨）")
    points: list[GoldInventoryPoint] = Field(default_factory=list, description="序列，按日期升序")
    changes: list[GoldInventoryChange] = Field(default_factory=list, description="1w/1m/3m/1y 变化率")
    degraded: bool = Field(False, description="是否走了缓存降级（源不可用但有旧缓存）")