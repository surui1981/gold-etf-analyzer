"""``GET /api/v1/trades/timeline`` 端点集成测试（V0.90.0 决策时间线回放）。

目标：覆盖端点 + TimelineService 全部边界分支。

策略：
- 真实 db_session fixture（in-memory SQLite），插入 Position / Account /
  TradeRecord / DailySnapshot 测试数据
- FastAPI TestClient via ``client`` fixture（ASGITransport）
- mock account_id / 默认 90 天窗口 / from > to 错误路径
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.position import Position, TradeRecord
from app.models.snapshot import DailySnapshot


# ──────────────── 测试 fixture ────────────────


async def _seed_account(db: AsyncSession, name: str = "默认账本") -> Account:
    acc = Account(name=name, is_default=True)
    db.add(acc)
    await db.commit()
    await db.refresh(acc)
    return acc


async def _seed_position(
    db: AsyncSession,
    account_id: int,
    symbol: str = "518880",
    name: str = "黄金ETF华安",
) -> Position:
    pos = Position(
        user_id=1,
        account_id=account_id,
        symbol=symbol,
        name=name,
        quantity=0.0,
        avg_cost=0.0,
        status="open",
    )
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    return pos


async def _seed_trade(
    db: AsyncSession,
    position_id: int,
    *,
    side: str,
    quantity: float,
    price: float,
    traded_at: datetime,
) -> TradeRecord:
    t = TradeRecord(
        position_id=position_id,
        side=side,
        quantity=quantity,
        price=price,
        fee=0.0,
        traded_at=traded_at,
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


async def _seed_snapshot(
    db: AsyncSession,
    snapshot_date: date,
    *,
    macro_json: str = '{"DXY": {"value": 104.5}}',
) -> DailySnapshot:
    snap = DailySnapshot(
        snapshot_date=snapshot_date,
        symbol="518880",
        name="黄金ETF华安",
        close=5.5, change_pct=1.0, high=5.6, low=5.4,
        ma20=5.45, ma40=5.40, direction="up",
        tech_index=65.0, macro_index=58.0, news_index=60.0,
        trend_index=61.0, index_level="偏多",
        macro_detail=macro_json,
        data_source="live",
    )
    db.add(snap)
    await db.commit()
    await db.refresh(snap)
    return snap


# ──────────────── 端点集成测试 ────────────────


class TestTradesTimelineEndpoint:
    """``GET /api/v1/trades/timeline`` 端点集成测试。"""

    async def test_empty_returns_one_idle_segment_covering_range(
        self, client: AsyncClient
    ) -> None:
        """空 DB + 合法窗口：返回 1 个 idle 段覆盖全范围 + decision_count=0。"""
        resp = await client.get(
            "/api/v1/trades/timeline"
            "?from_date=2026-10-01&to_date=2026-10-07"
        )
        assert resp.status_code == 200
        body = resp.json()

        assert body["from_date"] == "2026-10-01"
        assert body["to_date"] == "2026-10-07"
        assert body["span_days"] == 7
        assert body["decision_count"] == 0
        assert len(body["segments"]) == 1
        seg = body["segments"][0]
        assert seg["type"] == "idle"
        assert seg["start"] == "2026-10-01"
        assert seg["end"] == "2026-10-07"
        assert seg["idle_days"] == 7
        assert seg["compressed"] is False  # 7 == threshold 不折叠

    async def test_single_trade_with_same_day_snapshot(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """单笔 trade + 同日快照：1 decision + 1 idle 段（前后）+ macro_detail 反序列化。"""
        acc = await _seed_account(db_session)
        pos = await _seed_position(db_session, acc.id)
        target_day = date(2026, 10, 5)
        target_dt = datetime(2026, 10, 5, 14, 30)
        await _seed_trade(
            db_session, pos.id, side="buy", quantity=100.0, price=5.0,
            traded_at=target_dt,
        )
        await _seed_snapshot(db_session, target_day)

        resp = await client.get(
            f"/api/v1/trades/timeline?from_date=2026-10-01&to_date=2026-10-07"
        )
        assert resp.status_code == 200
        body = resp.json()

        assert body["decision_count"] == 1
        assert body["active_days"] == 1  # {10-05}（trade + snapshot 同日）

        # segments: idle(10-01 ~ 10-04) → decision(10-05) → idle(10-06 ~ 10-07)
        segs = body["segments"]
        assert len(segs) == 3
        assert segs[0]["type"] == "idle"
        assert segs[0]["idle_days"] == 4
        assert segs[1]["type"] == "decision"
        assert segs[1]["start"] == "2026-10-05"
        assert segs[1]["trade"]["side"] == "buy"
        # macro_detail 已在 snapshot 段反序列化
        assert isinstance(segs[1]["snapshot"]["macro_detail"], dict)
        assert segs[1]["snapshot"]["macro_detail"]["DXY"]["value"] == 104.5
        assert segs[2]["type"] == "idle"
        assert segs[2]["idle_days"] == 2

    async def test_trade_aligns_to_previous_day_snapshot(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """trade 当日无快照 → 回退到最近前一日快照（get_previous 语义）。"""
        acc = await _seed_account(db_session)
        pos = await _seed_position(db_session, acc.id)
        await _seed_trade(
            db_session, pos.id, side="buy", quantity=100.0, price=5.0,
            traded_at=datetime(2026, 10, 5, 14, 30),
        )
        # 只插入 10-03 快照（trade 当日 10-05 缺 → 回退 10-04 → 10-03）
        await _seed_snapshot(db_session, date(2026, 10, 3))

        resp = await client.get(
            f"/api/v1/trades/timeline?from_date=2026-10-01&to_date=2026-10-07"
        )
        assert resp.status_code == 200
        segs = resp.json()["segments"]

        decision_seg = next(s for s in segs if s["type"] == "decision")
        assert decision_seg["snapshot"]["snapshot_date"] == "2026-10-03"

    async def test_trade_with_no_snapshot_returns_null(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """trade 当日 + 回退 30 天内都无快照 → snapshot=None（前端展示「无数据」badge）。"""
        acc = await _seed_account(db_session)
        pos = await _seed_position(db_session, acc.id)
        await _seed_trade(
            db_session, pos.id, side="buy", quantity=100.0, price=5.0,
            traded_at=datetime(2026, 10, 5, 14, 30),
        )
        # 完全没快照

        resp = await client.get(
            f"/api/v1/trades/timeline?from_date=2026-10-01&to_date=2026-10-07"
        )
        assert resp.status_code == 200
        segs = resp.json()["segments"]

        decision_seg = next(s for s in segs if s["type"] == "decision")
        assert decision_seg["snapshot"] is None

    async def test_idle_segment_beyond_threshold_is_compressed(
        self, client: AsyncClient
    ) -> None:
        """空闲段 > compress_threshold → compressed=True（默认 7 天）。"""
        # 10 天窗口 + 无 trade → 1 个 idle 段（10 天 > 7 阈值 → compressed）
        resp = await client.get(
            "/api/v1/trades/timeline?from_date=2026-10-01&to_date=2026-10-10"
        )
        assert resp.status_code == 200
        segs = resp.json()["segments"]
        assert len(segs) == 1
        assert segs[0]["compressed"] is True
        assert segs[0]["idle_days"] == 10

    async def test_compress_threshold_zero_disables_compression(
        self, client: AsyncClient
    ) -> None:
        """compress_threshold_days=0 → 永远不压缩。"""
        resp = await client.get(
            "/api/v1/trades/timeline"
            "?from_date=2026-10-01&to_date=2026-10-31"
            "&compress_threshold_days=0"
        )
        assert resp.status_code == 200
        segs = resp.json()["segments"]
        # 即使 31 天也没压缩
        assert len(segs) == 1
        assert segs[0]["compressed"] is False
        assert segs[0]["idle_days"] == 31

    async def test_default_90_day_window_when_no_dates(
        self, client: AsyncClient
    ) -> None:
        """不传 from_date / to_date → 默认 90 天窗口（to_date=今日）。"""
        resp = await client.get("/api/v1/trades/timeline")
        assert resp.status_code == 200
        body = resp.json()
        today = date.today()
        assert body["to_date"] == today.isoformat()
        # from_date = to_date - 90
        expected_from = today - timedelta(days=90)
        assert body["from_date"] == expected_from.isoformat()
        assert body["span_days"] == 91  # 90 天跨度含首尾 = 91 天

    async def test_400_on_inverted_range(self, client: AsyncClient) -> None:
        """``from > to`` → 400 + code=invalid_date_range。"""
        resp = await client.get(
            "/api/v1/trades/timeline?from_date=2026-10-10&to_date=2026-10-01"
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "invalid_date_range"

    async def test_400_on_range_too_wide(self, client: AsyncClient) -> None:
        """范围 > 730 天 → 400 + code=date_range_too_wide。"""
        resp = await client.get(
            "/api/v1/trades/timeline?from_date=2020-01-01&to_date=2026-12-31"
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "date_range_too_wide"

    async def test_422_on_negative_compress_threshold(
        self, client: AsyncClient
    ) -> None:
        """compress_threshold_days=-1 → 422（Query ge=0）。"""
        resp = await client.get(
            "/api/v1/trades/timeline"
            "?from_date=2026-10-01&to_date=2026-10-07"
            "&compress_threshold_days=-1"
        )
        assert resp.status_code == 422

    async def test_422_on_malformed_dates(self, client: AsyncClient) -> None:
        """日期格式非法 → 422。"""
        resp = await client.get(
            "/api/v1/trades/timeline?from_date=bad&to_date=2026-10-07"
        )
        assert resp.status_code == 422

    async def test_filter_by_account_id(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """``account_id=2`` 过滤：只返回该账本的 trade（另一账本的 trade 被排除）。"""
        acc1 = await _seed_account(db_session, name="账本A")
        acc2 = await _seed_account(db_session, name="账本B")
        pos1 = await _seed_position(db_session, acc1.id)
        pos2 = await _seed_position(db_session, acc2.id)

        # 两个账本各 1 笔 trade，**同日**（同段塞 2 个 decision）
        same_day = datetime(2026, 10, 5, 10, 0)
        await _seed_trade(db_session, pos1.id, side="buy",
                          quantity=100.0, price=5.0, traded_at=same_day)
        await _seed_trade(db_session, pos2.id, side="buy",
                          quantity=200.0, price=5.0, traded_at=same_day)

        # account_id=1 → 只 1 笔 trade
        resp = await client.get(
            f"/api/v1/trades/timeline?account_id={acc1.id}"
            "&from_date=2026-10-01&to_date=2026-10-07"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["decision_count"] == 1
        assert body["segments"][1]["trade"]["account_id"] == acc1.id

    async def test_multiple_trades_same_day_each_get_segment(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """同日多笔 trade → 每个 trade 各 1 个 decision 段（顺次排列）。"""
        acc = await _seed_account(db_session)
        pos = await _seed_position(db_session, acc.id)
        day = date(2026, 10, 5)
        # 同日 3 笔 trade（早/午/晚）
        for hour in (9, 12, 15):
            await _seed_trade(
                db_session, pos.id, side="buy", quantity=100.0, price=5.0,
                traded_at=datetime(2026, 10, 5, hour, 0),
            )
        await _seed_snapshot(db_session, day)

        resp = await client.get(
            "/api/v1/trades/timeline?from_date=2026-10-01&to_date=2026-10-07"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["decision_count"] == 3
        decision_segs = [s for s in body["segments"] if s["type"] == "decision"]
        assert len(decision_segs) == 3
        # 同日共享快照
        assert all(s["snapshot"] is not None for s in decision_segs)

    async def test_active_days_counts_distinct_dates(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """``active_days`` = trade_date ∪ snapshot_date 去重数。"""
        acc = await _seed_account(db_session)
        pos = await _seed_position(db_session, acc.id)
        # 10-03 trade；10-05 snapshot；10-05 另 1 trade
        await _seed_trade(db_session, pos.id, side="buy",
                          quantity=100.0, price=5.0,
                          traded_at=datetime(2026, 10, 3, 10, 0))
        await _seed_snapshot(db_session, date(2026, 10, 5))
        await _seed_trade(db_session, pos.id, side="sell",
                          quantity=50.0, price=5.5,
                          traded_at=datetime(2026, 10, 5, 14, 0))

        resp = await client.get(
            "/api/v1/trades/timeline?from_date=2026-10-01&to_date=2026-10-10"
        )
        assert resp.status_code == 200
        body = resp.json()
        # active_days = {10-03, 10-05} = 2
        assert body["active_days"] == 2
        assert body["decision_count"] == 2

    async def test_alternating_idle_and_decision(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """决策点交错排列：decision → idle → decision → idle ... 的 segments 序列。"""
        acc = await _seed_account(db_session)
        pos = await _seed_position(db_session, acc.id)
        # 10-02 trade；10-03 snapshot；10-05 trade；10-08 snapshot
        await _seed_trade(db_session, pos.id, side="buy",
                          quantity=100.0, price=5.0,
                          traded_at=datetime(2026, 10, 2, 10, 0))
        await _seed_snapshot(db_session, date(2026, 10, 3))
        await _seed_trade(db_session, pos.id, side="sell",
                          quantity=50.0, price=5.5,
                          traded_at=datetime(2026, 10, 5, 14, 0))
        await _seed_snapshot(db_session, date(2026, 10, 8))

        resp = await client.get(
            "/api/v1/trades/timeline?from_date=2026-10-01&to_date=2026-10-10"
        )
        assert resp.status_code == 200
        segs = resp.json()["segments"]
        types = [s["type"] for s in segs]
        # 期望：idle(10-01) → decision(10-02) → idle(10-03~10-04) → decision(10-05) → idle(10-06~10-10)
        assert types == ["idle", "decision", "idle", "decision", "idle"]

    async def test_trade_aligns_to_today_snapshot_over_previous(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """trade 当日**有**快照时，优先用当日（不回退）。"""
        acc = await _seed_account(db_session)
        pos = await _seed_position(db_session, acc.id)
        await _seed_trade(db_session, pos.id, side="buy",
                          quantity=100.0, price=5.0,
                          traded_at=datetime(2026, 10, 5, 14, 30))
        # 当日 10-05 快照 + 前日 10-04 快照
        await _seed_snapshot(db_session, date(2026, 10, 4))
        await _seed_snapshot(db_session, date(2026, 10, 5))

        resp = await client.get(
            "/api/v1/trades/timeline?from_date=2026-10-01&to_date=2026-10-07"
        )
        assert resp.status_code == 200
        decision_seg = next(
            s for s in resp.json()["segments"] if s["type"] == "decision"
        )
        # 用当日，不回退
        assert decision_seg["snapshot"]["snapshot_date"] == "2026-10-05"