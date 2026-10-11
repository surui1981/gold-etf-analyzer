"""每日快照 Schema。"""

import json
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from app.utils.logger import get_logger

logger = get_logger(__name__)


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
    news_index: float = 50.0
    trend_index: float
    index_level: str
    # V0.79.0 任务 #162：技术面 5 维度明细 JSON。
    # ⚠ **历史 24 条为 None**（上游 K 线只覆盖其中 16-17 天，无法回填完整）。
    # ⇒ 消费方（回测 Step G）读到 None 必须**显式跳过该日**，不可用中性 50 兜底
    # （V0.78.0 Step D 纪律：数据不足 ≠ 中性）。
    tech_detail: str | None = None
    # ⚠ V0.79.0 任务 #163：行情来源（live/stale/mock；空串或 None = 未能确定）。
    # 历史 24 条为 NULL —— 其中 5 条经查证是 **mock 产物**（close 是 mock 序列末值
    # 4725.07），故回测**必须**把来源非 live 的行排除，否则统计失真。
    data_source: str | None = None
    # V0.90.0 修复：V0.79.0 任务 #162 同类陷阱——``macro_detail`` 已落库（Text JSON）
    # 但 SnapshotOut **未声明此字段**；Pydantic ``from_attributes=True`` 会按白名单
    # 丢弃未声明字段 ⇒ 前端拿到的快照响应**永远没有 macro_detail**。
    # 与 V0.79.0 任务 #162 同根因（schema 漏配），V0.90.0 决策时间线回放需要
    # macro_detail 拼装「决策点状态卡片」，故此处补漏。
    macro_detail: dict[str, Any] | None = None

    @field_validator("macro_detail", mode="before")
    @classmethod
    def _parse_macro_detail(cls, v: Any) -> dict[str, Any] | None:
        """反序列化 macro_detail：dict 直接透传 / str JSON 解析 / None / 损坏 → None。

        落库格式（``services/snapshot.py:44-56``）是 ``json.dumps(...)`` 字符串，
        但 ORM 对象已 attached 时属性值就是 str；schema 端反序列化一次，前端
        即可直接 ``data.macro_detail['DXY']['value']`` 读，不必再 JSON.parse。

        损坏 JSON（V0.79.0 之前可能存在的脏数据）按 V0.79.0 tech_detail 历史 NULL
        纪律处理：log warning + 置 None（**数据不足 ≠ 中性**，不兜底为 ``{}``）。
        """
        if v is None:
            return None
        if isinstance(v, dict):
            return v
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, dict):
                    return parsed
                # JSON 合法但不是 dict（顶层 list/str/int）—— macro_detail 语义是 dict
                preview = v[:200] + ("…" if len(v) > 200 else "")
                logger.warning(
                    "SnapshotOut.macro_detail 顶层非 dict（%s）→ 置 None（preview=%r）",
                    type(parsed).__name__,
                    preview,
                )
                return None
            except (json.JSONDecodeError, ValueError):
                preview = v[:200] + ("…" if len(v) > 200 else "")
                logger.warning(
                    "SnapshotOut.macro_detail JSON 反序列化失败 → 置 None（preview=%r）",
                    preview,
                )
                return None
        # 非 str/dict/None（如 list/数字）—— 不预期，按损坏处理
        logger.warning(
            "SnapshotOut.macro_detail 收到非预期类型 %s → 置 None",
            type(v).__name__,
        )
        return None


class SnapshotListOut(BaseModel):
    """历史快照列表。"""

    total: int
    snapshots: list[SnapshotOut]
