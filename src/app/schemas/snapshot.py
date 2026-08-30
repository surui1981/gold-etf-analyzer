"""每日快照 Schema。"""

from datetime import date

from pydantic import BaseModel, ConfigDict


class SnapshotOut(BaseModel):
    """单日快照：参数 + 评估值。"""

    model_config = ConfigDict(from_attributes=True)

    snapshot_date: date
    symbol: str
    name: str
    close: float
    change_pct: float
    high: float
    low: float
    ma20: float
    ma40: float
    direction: str
    tech_index: float
    macro_index: float
    trend_index: float
    index_level: str


class SnapshotListOut(BaseModel):
    """历史快照列表。"""

    total: int
    snapshots: list[SnapshotOut]
