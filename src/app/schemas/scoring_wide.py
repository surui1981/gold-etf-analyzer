"""打分数据宽表 Schema（V0.92.0）

API 端点契约：
- ``GET /api/v1/scoring/summary?from=&to=&group_by=day|week|month&tag=`` → ``ScoringSummaryOut``
- ``GET /api/v1/scoring/by-date/{date}`` → ``ScoringWideOut``
- ``GET /api/v1/scoring/hit-stats?from=&to=&horizon=t1|t3|t5`` → ``ScoringHitStatsOut``
- ``GET /api/v1/scoring/by-tag?from=&to=`` → ``ScoringByTagOut``

设计纪律（V0.78.0 Step D）：所有数值列允许 NULL（**绝不**用 50 / 0 兜底）。
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from app.utils.logger import get_logger

logger = get_logger(__name__)


class ScoringWideOut(BaseModel):
    """单日打分宽表行（4 指数 + 消息面 + 共振 + outcomes）。"""

    model_config = ConfigDict(from_attributes=True)

    date: date
    user_id: int
    snapshot_id: int | None = None

    # 4 指数（可空 —— V0.78.0 Step D）
    tech_index: float | None = None
    macro_index: float | None = None
    news_index: float | None = None
    trend_index: float | None = None
    index_level: str | None = None

    # 价格参数
    close: float | None = None
    change_pct: float | None = None
    direction: str | None = None
    data_source: str | None = None

    # 消息面聚合
    news_slot_count: int | None = None
    news_basis_tags: list[str] | None = None
    news_backfilled_count: int | None = None

    # 共振
    resonance_signal: str | None = None
    resonance_subtype: str | None = None

    # outcomes（pending 期为 NULL）
    actual_change_pct_t1: float | None = None
    actual_change_pct_t3: float | None = None
    actual_change_pct_t5: float | None = None
    hit_t1: bool | None = None
    hit_t3: bool | None = None
    hit_t5: bool | None = None
    outcome_pending_until: date | None = None

    @field_validator("news_basis_tags", mode="before")
    @classmethod
    def _parse_basis_tags(cls, v: Any) -> list[str] | None:
        """反序列化 news_basis_tags：JSON 数组字符串 / 列表 / None / 损坏 → list | None。

        落库格式（``services/scoring_wide.py::build_row``）是 ``json.dumps(list)`` 字符串，
        但 ORM 对象已 attached 时属性值就是 str；schema 端反序列化一次，前端
        即可直接 ``data.news_basis_tags`` 读 list，不必再 JSON.parse。
        """
        if v is None:
            return None
        if isinstance(v, list):
            return [str(x) for x in v if str(x).strip()]
        if isinstance(v, str):
            if not v.strip():
                return None
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return [str(x) for x in parsed if str(x).strip()]
                logger.warning(
                    "ScoringWideOut.news_basis_tags 顶层非 list（%s）→ 置 None",
                    type(parsed).__name__,
                )
                return None
            except (json.JSONDecodeError, ValueError):
                logger.warning("ScoringWideOut.news_basis_tags JSON 解析失败 → 置 None")
                return None
        logger.warning(
            "ScoringWideOut.news_basis_tags 收到非预期类型 %s → 置 None",
            type(v).__name__,
        )
        return None


class ScoringWideListOut(BaseModel):
    """宽表行列表。"""

    total: int
    rows: list[ScoringWideOut]


# ──────────── summary 聚合 ────────────


class ScoringSummaryBucket(BaseModel):
    """按 day/week/month 分桶的聚合。"""

    period: str  # "2026-10-13" / "2026-W42" / "2026-10"
    days: int
    trend_index_mean: float | None = None
    trend_index_median: float | None = None
    news_index_mean: float | None = None
    hit_rate_t1: float | None = None
    hit_rate_t3: float | None = None
    hit_rate_t5: float | None = None
    up_days: int = 0
    down_days: int = 0
    sideways_days: int = 0


class ScoringSummaryOut(BaseModel):
    """``/api/v1/scoring/summary`` 响应。"""

    from_date: date
    to_date: date
    group_by: str
    tag: str | None = None
    buckets: list[ScoringSummaryBucket]


# ──────────── hit-stats 聚合 ────────────


class ScoringHitDirectionStat(BaseModel):
    """按方向统计的命中率。"""

    direction: str
    hit_count: int
    total: int
    hit_rate: float


class ScoringHitCalibrationBucket(BaseModel):
    """按分值分箱的命中率。"""

    score_bucket: str  # "60-80"
    hit_count: int
    total: int
    hit_rate: float


class ScoringHitStatsOut(BaseModel):
    """``/api/v1/scoring/hit-stats`` 响应。"""

    horizon: str  # "t1" / "t3" / "t5"
    sample_size: int
    overall_hit_rate: float | None = None
    by_direction: list[ScoringHitDirectionStat]
    by_month: list[ScoringSummaryBucket]  # 复用 bucket schema
    calibration: list[ScoringHitCalibrationBucket]


# ──────────── by-tag 聚合 ────────────


class ScoringTagStat(BaseModel):
    """按依据标签统计的出现次数与命中率。"""

    tag: str
    count: int
    hit_rate_t1: float | None = None
    hit_rate_t3: float | None = None
    hit_rate_t5: float | None = None


class ScoringByTagOut(BaseModel):
    """``/api/v1/scoring/by-tag`` 响应。"""

    from_date: date
    to_date: date
    tags: list[ScoringTagStat]
