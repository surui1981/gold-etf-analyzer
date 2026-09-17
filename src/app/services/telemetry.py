"""前端埋点服务（V0.68.0）。

职责：
- 校验白名单事件类型（防止恶意 POST 撑爆表）
- 批量入库 + 派生指标聚合
- 不解析 payload 业务字段（仅持久化为 JSON 文本）
"""

from datetime import datetime, timedelta, timezone

from app.models.telemetry import TelemetryEvent
from app.repositories.telemetry import TelemetryRepository, _event_to_model
from app.schemas.telemetry import (
    TelemetryBatchIn,
    TelemetryEventIn,
    TelemetryIngestResult,
    TelemetryStats,
    TelemetryStatsOut,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# V0.68.0 事件白名单（前端常量同源）；未列入直接拒收（不入 DB，避免被恶意填充垃圾类型）
# 命名与 docs/ux-roadmap.md 附录 C「自身可观测性埋点事件」对齐
ALLOWED_EVENT_TYPES: frozenset[str] = frozenset(
    {
        # 浏览 + 操作
        "page_view",
        "action_click",
        "range_change",
        "error_caught",
        # 命令面板三阶段
        "palette_open",
        "palette_query",
        "palette_select",
        # 汉堡抽屉两阶段
        "nav_drawer_open",
        "nav_drawer_select",
        # 主题切换（V0.69.0 预埋）
        "theme_change",
    }
)


class TelemetryService:
    """前端埋点业务编排：白名单校验 + 批量入库 + 派生聚合。"""

    def __init__(self, repo: TelemetryRepository) -> None:
        self._repo = repo

    async def ingest(
        self,
        batch: TelemetryBatchIn,
        *,
        trace_id: str | None = None,
    ) -> TelemetryIngestResult:
        """批量上报入库。

        白名单校验失败的整条丢弃（不抛错——埋点是辅助观测，失败不应阻塞用户）；
        返回 ``accepted`` / ``rejected`` + 失败原因摘要（最多 5 条）。
        """
        accepted: list[TelemetryEvent] = []
        rejected_reasons: list[str] = []

        for e in batch.events:
            err = _validate_event(e)
            if err is not None:
                if len(rejected_reasons) < 5:
                    rejected_reasons.append(err)
                continue
            accepted.append(
                _event_to_model(
                    event_type=e.event_type,
                    page=e.page,
                    payload=e.payload,
                    session_id=e.session_id,
                    trace_id=trace_id,
                )
            )

        inserted = await self._repo.insert_batch(accepted) if accepted else 0

        logger.info(
            "telemetry ingest: accepted=%s rejected=%s page=%s",
            inserted,
            len(batch.events) - inserted,
            batch.events[0].page if batch.events else "-",
        )

        return TelemetryIngestResult(
            accepted=inserted,
            rejected=len(batch.events) - inserted,
            rejected_reasons=rejected_reasons,
        )

    async def stats(self, days: int = 7) -> TelemetryStatsOut:
        """派生指标：最近 N 天按事件类型聚合 + 总数。

        派生率 ``rate = count_7d / total``（同窗口）；用于「事件占比」派生。
        """
        days = max(1, min(days, 30))
        now = datetime.now(timezone.utc)
        since_24h = now - timedelta(hours=24)
        since_7d = now - timedelta(days=days)

        type_counts_7d = await self._repo.count_by_type(since_7d)
        type_counts_24h = await self._repo.count_by_type(since_24h)
        total_7d = await self._repo.count_total(since_7d)
        # 24h 总数用于对 rate 兜底（防 total_7d 为 0 时全字段 None）
        _total_24h = await self._repo.count_total(since_24h)

        by_type: list[TelemetryStats] = []
        all_types = sorted(set(type_counts_7d) | set(type_counts_24h))
        for evt in all_types:
            c_7d = type_counts_7d.get(evt, 0)
            c_24h = type_counts_24h.get(evt, 0)
            rate = (c_7d / total_7d) if total_7d else None
            by_type.append(
                TelemetryStats(event_type=evt, count_24h=c_24h, count_7d=c_7d, rate=rate)
            )

        return TelemetryStatsOut(days=days, total=total_7d, by_type=by_type)


def _validate_event(e: TelemetryEventIn) -> str | None:
    """单条校验；返回 None 表示通过，返回 str 表示失败原因。"""
    if e.event_type not in ALLOWED_EVENT_TYPES:
        return f"event_type={e.event_type!r} not in whitelist"
    if not e.page or not e.page.startswith("/"):
        return f"page={e.page!r} invalid (must start with /)"
    if len(e.payload) > 50:  # payload 字段数上限（防 dict 炸弹）
        return f"payload keys={len(e.payload)} > 50"
    return None


__all__ = ["ALLOWED_EVENT_TYPES", "TelemetryService"]
