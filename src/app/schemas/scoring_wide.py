"""打分数据宽表 Schema（V0.92.0）

API 端点契约：
- ``GET /api/v1/scoring/summary?from=&to=&group_by=day|week|month&tag=`` → ``ScoringSummaryOut``
- ``GET /api/v1/scoring/by-date/{date}`` → ``ScoringWideOut``
- ``GET /api/v1/scoring/hit-stats?from=&to=&horizon=t1|t3|t5`` → ``ScoringHitStatsOut``
- ``GET /api/v1/scoring/hit-stats-all?from=&to=`` → ``ScoringHitStatsAllOut`` (V0.96.0)
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
    # V0.95.0：NY 金（COMEX）美元/盎司收盘价 —— 4 指数时序表替换「横盘日数」用。
    gold_ny_close: float | None = None

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
    # V0.93.0：T+0 outcome —— 当日 close vs 上一交易日 close 的命中判定。
    # 定位「当日尾盘快速反馈」，非「预测能力」评估（盘内信息泄露）。
    actual_change_pct_t0: float | None = None
    hit_t0: bool | None = None
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
    # V0.93.0：加 T+0 命中率（T+0 = 当日 close vs 上一交易日 close 的命中比例）
    hit_rate_t0: float | None = None
    hit_rate_t1: float | None = None
    hit_rate_t3: float | None = None
    hit_rate_t5: float | None = None
    up_days: int = 0
    down_days: int = 0
    # V0.95.0：「横盘日数」列替换为「NY金美元/盎司收盘价」（取桶内最后一日收盘）。
    # day 桶 → 当日收盘；week/month 桶 → period-end snapshot。
    gold_ny_close: float | None = None
    # V0.92.1 hotfix：单日桶（group_by=day 且桶内 1 行）按所选 horizon 标记该行 hit 状态；
    # week/month 桶/pending 行 → None。前端据此渲染"命中"列（是=红 / 否=绿 / —=灰）。
    hit: bool | None = None


class ScoringSummaryOut(BaseModel):
    """``/api/v1/scoring/summary`` 响应。"""

    from_date: date
    to_date: date
    group_by: str
    tag: str | None = None
    # V0.92.1 hotfix：命中筛选（"yes" / "no" / "all"）与所选 horizon（默认 t1）
    hit_filter: str = "all"
    horizon: str = "t1"
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


# ──────────── hit-stats-all 4 horizon 聚合（V0.96.0）────────────


class ScoringHitStatsAllHorizon(BaseModel):
    """单 horizon 的 by_month 时序（4 horizon 各 1 个）。"""

    horizon: str  # "t0" | "t1" | "t3" | "t5"
    by_month: list[ScoringSummaryBucket]  # 复用 summary bucket


class ScoringHitStatsAllMiniCard(BaseModel):
    """最近 30 天 / 同比上月 / 最佳 horizon 摘要。"""

    # V0.78.0 Step D 纪律：所有数值列允许 NULL（< 30 ready 日 / 无数据时为 None）
    last_30d: dict[str, float | None]  # {"t0": 0.62, "t1": 0.55, "t3": 0.48, "t5": 0.42}
    last_30d_mom: dict[str, float | None]  # {"t0": 0.05, "t1": -0.03, "t3": 0.01, "t5": -0.07}
    best_horizon: str | None  # 按 last_30d 命中率最大；全 None → None


class ScoringHitStatsAllOut(BaseModel):
    """``/api/v1/scoring/hit-stats-all`` 响应（V0.96.0）。

    1 次调用取 4 horizon 全部数据 + 3 mini card 摘要。
    """

    from_date: date
    to_date: date
    by_horizon: dict[str, ScoringHitStatsAllHorizon]  # {"t0": ..., "t1": ..., "t3": ..., "t5": ...}
    mini_card: ScoringHitStatsAllMiniCard


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


# ──────────── 预测评估卡（V0.94.0） ────────────


class ScoringHorizonVerdict(BaseModel):
    """单个 horizon 的判定状态（用于预测评估卡）。"""

    horizon: str  # "t0" | "t1" | "t3" | "t5"
    status: str  # "ready"（已就绪） | "pending"（等待收盘） | "missing"（无打分/无方向）
    actual_change_pct: float | None = None
    hit: bool | None = None
    pending_until: date | None = None  # pending 状态：等到该日收盘后才有 outcome


class ScoringVerdictOut(BaseModel):
    """``/api/v1/scoring/verdict`` 响应（V0.94.0 预测评估卡）。"""

    target_date: date
    # 你的预测
    news_index: float | None = None
    prediction_direction: str | None = None  # "bullish" | "bearish" | "neutral" | None
    prediction_confidence: float | None = None  # 0-100 数值
    # 4 个 horizon 状态
    verdicts: list[ScoringHorizonVerdict]
    # 依据（basis_tags 去重后）
    basis_tags: list[str] = []
    # 一句话总结
    summary: str
    # 无打分时的友好提示（前端可走「暂无打分」分支）
    no_score: bool = False
