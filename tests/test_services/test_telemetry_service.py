"""埋点服务测试（V0.68.0 客户端埋点底座）。

覆盖：
- 白名单校验：白名单内通过；白名单外拒绝（带原因）
- 字段长度上限：event_type / page 截断
- payload 字段数上限：> 50 拒绝
- page 路径校验：非 ``/`` 开头拒绝
- trace_id 透传：写入 ORM 模型时正确赋值
- 派生指标聚合：按 event_type + 时间窗口
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.telemetry import TelemetryEvent
from app.repositories.telemetry import TelemetryRepository
from app.schemas.telemetry import TelemetryBatchIn, TelemetryEventIn
from app.services.telemetry import ALLOWED_EVENT_TYPES, TelemetryService


def _service(session: AsyncSession) -> TelemetryService:
    return TelemetryService(TelemetryRepository(session))


def _event(event_type: str = "page_view", **kw) -> TelemetryEventIn:
    return TelemetryEventIn(
        event_type=event_type,
        page=kw.get("page", "/static/portfolio.html"),
        payload=kw.get("payload", {"from": "test"}),
        session_id=kw.get("session_id", "abcdef0123456789abcdef0123456789"),
    )


# ───────────────── 白名单校验 ─────────────────


def test_allowed_event_types_constants_present():
    """白名单包含 V0.68.0 全量事件类型 + V0.69.0 主题切换预埋。"""
    expected = {
        "page_view",
        "action_click",
        "range_change",
        "error_caught",
        "palette_open",
        "palette_query",
        "palette_select",
        "nav_drawer_open",
        "nav_drawer_select",
        "theme_change",
    }
    assert expected.issubset(ALLOWED_EVENT_TYPES)


async def test_ingest_accepts_whitelisted_event(db_session: AsyncSession):
    """白名单内事件应全部 accepted。"""
    svc = _service(db_session)
    batch = TelemetryBatchIn(events=[_event("page_view"), _event("palette_open")])
    result = await svc.ingest(batch, trace_id="trace-abc-123")
    assert result.accepted == 2
    assert result.rejected == 0


async def test_ingest_rejects_unknown_event_type(db_session: AsyncSession):
    """白名单外事件拒绝 + 原因首条带事件名。"""
    svc = _service(db_session)
    batch = TelemetryBatchIn(events=[_event("not_in_whitelist")])
    result = await svc.ingest(batch)
    assert result.accepted == 0
    assert result.rejected == 1
    assert "not_in_whitelist" in result.rejected_reasons[0]


async def test_ingest_rejects_page_without_leading_slash(db_session: AsyncSession):
    """page 必须以 ``/`` 开头；否则拒绝。"""
    svc = _service(db_session)
    batch = TelemetryBatchIn(events=[_event(page="static/portfolio.html")])
    result = await svc.ingest(batch)
    assert result.accepted == 0
    assert result.rejected == 1
    assert "must start with /" in result.rejected_reasons[0]


async def test_ingest_rejects_oversized_payload(db_session: AsyncSession):
    """payload 字段数 > 50 拒绝（防 dict 炸弹）。"""
    svc = _service(db_session)
    big = {f"k{i}": i for i in range(51)}
    batch = TelemetryBatchIn(events=[_event(payload=big)])
    result = await svc.ingest(batch)
    assert result.accepted == 0
    assert result.rejected == 1
    assert "payload keys=" in result.rejected_reasons[0]


# ───────────────── trace_id 透传 ─────────────────


async def test_ingest_persists_trace_id(db_session: AsyncSession):
    """trace_id 由 ingest 透传到 ORM 模型。"""
    svc = _service(db_session)
    batch = TelemetryBatchIn(events=[_event("page_view")])
    await svc.ingest(batch, trace_id="trace-xyz-001")

    rows = (
        (await db_session.execute(__import__("sqlalchemy").select(TelemetryEvent))).scalars().all()
    )
    assert len(rows) == 1
    assert rows[0].trace_id == "trace-xyz-001"


async def test_ingest_rejects_long_session_id_at_schema(db_session: AsyncSession):
    """session_id 超 32 字符在 Pydantic schema 层直接拒绝（max_length=32）。"""
    from pydantic import ValidationError as PydValidationError

    long_sid = "x" * 100
    with pytest.raises(PydValidationError):
        TelemetryEventIn(
            event_type="page_view",
            page="/static/portfolio.html",
            payload={},
            session_id=long_sid,
        )


# ───────────────── 派生指标聚合 ─────────────────


async def test_stats_counts_by_type_and_window(db_session: AsyncSession):
    """stats 按 event_type 分组 + 24h / 7d 双窗口聚合。"""
    svc = _service(db_session)
    # 入 5 条：3 page_view + 2 palette_open
    events = [
        _event("page_view"),
        _event("page_view"),
        _event("page_view"),
        _event("palette_open"),
        _event("palette_open"),
    ]
    await svc.ingest(TelemetryBatchIn(events=events))

    out = await svc.stats(days=7)
    assert out.days == 7
    assert out.total == 5
    by = {b.event_type: b for b in out.by_type}
    assert by["page_view"].count_7d == 3
    assert by["page_view"].count_24h == 3
    assert by["palette_open"].count_7d == 2
    assert by["palette_open"].count_24h == 2
    # rate：3/5 = 0.6 / 2/5 = 0.4
    assert by["page_view"].rate == pytest.approx(0.6)
    assert by["palette_open"].rate == pytest.approx(0.4)


async def test_stats_excludes_older_than_window(db_session: AsyncSession):
    """7 天窗口外的旧事件不计入（仅聚合 since_7d）。"""
    repo = TelemetryRepository(db_session)
    # 直接插一条 10 天前的旧事件（绕过 service 白名单）
    old = TelemetryEvent(
        event_type="page_view",
        page="/static/portfolio.html",
        payload="{}",
        session_id="x" * 32,
        user_id="1",
        created_at=datetime.now(timezone.utc) - timedelta(days=10),
    )
    await repo.insert(old)
    await db_session.commit()
    # 再插一条新事件
    svc = TelemetryService(repo)
    await svc.ingest(TelemetryBatchIn(events=[_event("page_view")]))

    out = await svc.stats(days=7)
    # 旧事件 + 新事件都 type=page_view，但 7d 窗口只算新的（1 条）
    by = {b.event_type: b for b in out.by_type}
    assert by["page_view"].count_7d == 1
