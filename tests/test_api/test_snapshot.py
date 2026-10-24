"""每日快照 API 测试。"""

from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_market_data_repository, get_trend_service
from app.models.snapshot import DailySnapshot
from app.repositories.market_data import GoldKline
from app.schemas.common import DirectionSignal
from app.schemas.market import MacroIndexOut
from app.services.trend import TrendService


class FakeMarketRepo:
    async def get_gold_quote(self, symbol: str = "XAU"):
        return type(
            "Q",
            (),
            {"symbol": symbol, "price_usd": 5.5, "change_pct": 1.2, "updated_at": date.today()},
        )()

    async def get_gold_history(self, days: int = 60) -> list[GoldKline]:
        base = date(2026, 6, 1)
        return [
            GoldKline(
                date=base + timedelta(days=i),
                open=5.0,
                close=round(5.0 + i * 0.02, 3),
                high=5.1,
                low=4.9,
                volume=1000.0,
            )
            for i in range(days)
        ]

    async def get_gold_gram_history(self, days: int = 60) -> list[GoldKline]:
        base = date(2026, 6, 1)
        return [
            GoldKline(
                date=base + timedelta(days=i),
                open=990.0,
                close=round(990.0 + i * 1.5, 2),
                high=992.0,
                low=988.0,
                volume=0.0,
            )
            for i in range(days)
        ]

    async def get_us_gold_history(self, days: int = 60) -> list[GoldKline]:
        base = date(2026, 6, 1)
        return [
            GoldKline(
                date=base + timedelta(days=i),
                open=4400.0,
                close=round(4400.0 + i * 3.0, 2),
                high=4410.0,
                low=4390.0,
                volume=0.0,
            )
            for i in range(days)
        ]


class FakeMacro:
    async def evaluate(self) -> MacroIndexOut:
        return MacroIndexOut(
            score=50.0, direction=DirectionSignal.NEUTRAL, factors=[], summary="测试"
        )


@pytest.fixture(autouse=True)
def _override_deps():
    from app.main import app

    app.dependency_overrides[get_market_data_repository] = lambda: FakeMarketRepo()
    app.dependency_overrides[get_trend_service] = lambda: TrendService(
        FakeMarketRepo(), macro=FakeMacro()
    )
    yield
    app.dependency_overrides.clear()


async def test_capture_snapshot(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/snapshots/capture")
    assert resp.status_code == 200
    body = resp.json()

    assert body["symbol"] == "GC"
    assert body["trend_index"] > 0
    assert body["index_level"] in {"strong_up", "up", "sideways", "down", "strong_down"}
    assert body["close"] > 0


async def test_list_snapshots(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/snapshots?days=10")
    assert resp.status_code == 200
    body = resp.json()

    assert body["total"] >= 1
    snap = body["snapshots"][0]
    assert snap["snapshot_date"] == date.today().isoformat()
    assert snap["tech_index"] > 0


async def test_v063_list_snapshots_days_one(client: AsyncClient) -> None:
    """V0.63.0：days=1 边界 —— 应当返回 1 条且为当日。"""
    resp = await client.get("/api/v1/snapshots?days=1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["snapshots"][0]["snapshot_date"] == date.today().isoformat()


async def test_v063_list_snapshots_days_max(client: AsyncClient) -> None:
    """V0.63.0：days=365 上限 —— 应当 200 且 total 与 days 兼容（≤ days，惰性补当日仍只有 1 条）。"""
    resp = await client.get("/api/v1/snapshots?days=365")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] <= 365
    assert body["total"] >= 1  # 惰性补当日至少 1 条


async def test_v063_snapshot_includes_news_index(client: AsyncClient) -> None:
    """V0.63.0：响应 schema 包含 news_index 字段（消息面曲线的数据来源）。"""
    resp = await client.get("/api/v1/snapshots?days=1")
    assert resp.status_code == 200
    snap = resp.json()["snapshots"][0]
    assert "news_index" in snap
    assert isinstance(snap["news_index"], (int, float))
    # 未打分的 fallback 是 50.0（中性）
    assert 0 <= snap["news_index"] <= 100


async def test_v063_days_query_validation(client: AsyncClient) -> None:
    """V0.63.0：days 越界（0 / 366）应返回 422 校验错误。"""
    for bad in ("0", "366", "-1"):
        resp = await client.get(f"/api/v1/snapshots?days={bad}")
        assert resp.status_code == 422, f"days={bad} 应被拒：{resp.status_code}"


# ──────────────── V0.90.0 · GET /by-date/{date} ────────────────


async def _seed(
    db_session: AsyncSession,
    snapshot_date: date,
    *,
    macro_json: str | None = '{"DXY": {"value": 104.5}, "US10Y": {"value": 4.2}}',
) -> None:
    """直接向 DB 插入测试快照（绕过 capture_today，避免触发行情/宏观依赖）。"""
    db_session.add(
        DailySnapshot(
            snapshot_date=snapshot_date,
            symbol="518880",
            name="黄金ETF华安",
            close=5.5,
            change_pct=1.0,
            high=5.6,
            low=5.4,
            ma20=5.45,
            ma40=5.40,
            direction="up",
            tech_index=65.0,
            macro_index=58.0,
            news_index=60.0,
            trend_index=61.0,
            index_level="偏多",
            macro_detail=macro_json or "",
            data_source="live",
        )
    )
    await db_session.commit()


class TestByDateEndpoint:
    """V0.90.0 ``GET /api/v1/snapshots/by-date/{date}`` —— 决策点状态卡片。"""

    async def test_returns_snapshot_with_macro_detail_dict(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """200 + 响应里 macro_detail 是 dict（非 raw JSON 字符串，端到端验证反序列化）。"""
        target = date(2026, 10, 1)
        await _seed(db_session, target)

        resp = await client.get(f"/api/v1/snapshots/by-date/{target.isoformat()}")
        assert resp.status_code == 200
        body = resp.json()

        assert body["snapshot_date"] == target.isoformat()
        assert body["trend_index"] == 61.0
        # V0.90.0 核心修复：macro_detail 是 dict 而非 str JSON
        assert isinstance(body["macro_detail"], dict)
        assert body["macro_detail"]["DXY"]["value"] == 104.5
        assert body["macro_detail"]["US10Y"]["value"] == 4.2

    async def test_404_when_snapshot_not_found(self, client: AsyncClient) -> None:
        """空 DB / 当日无快照 → 404 + code=snapshot_not_found（业务约定）。"""
        target = date(2026, 7, 15)  # DB 重建后无任何数据
        resp = await client.get(f"/api/v1/snapshots/by-date/{target.isoformat()}")
        assert resp.status_code == 404
        detail = resp.json()["detail"]
        assert detail["code"] == "snapshot_not_found"
        assert detail["date"] == target.isoformat()

    async def test_path_param_accepts_iso_date(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """路径参数接受 ISO 8601 YYYY-MM-DD（FastAPI 自动转 date）。"""
        target = date(2026, 10, 5)
        await _seed(db_session, target)

        resp = await client.get(f"/api/v1/snapshots/by-date/{target.isoformat()}")
        assert resp.status_code == 200
        assert resp.json()["snapshot_date"] == target.isoformat()

    async def test_422_on_malformed_date(self, client: AsyncClient) -> None:
        """路径参数非 ISO 格式 → FastAPI 422 校验错误（type=date 解析失败）。"""
        resp = await client.get("/api/v1/snapshots/by-date/not-a-date")
        assert resp.status_code == 422


# ──────────────── V0.90.0 · GET /in-range ────────────────


class TestInRangeEndpoint:
    """V0.90.0 ``GET /api/v1/snapshots/in-range?start=&end=`` —— timeline 批量取快照。"""

    async def test_returns_snapshots_in_range(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """200 + 范围内快照按日期升序。"""
        start = date(2026, 10, 1)
        for i in range(5):
            await _seed(db_session, start + timedelta(days=i))

        resp = await client.get(
            f"/api/v1/snapshots/in-range?start={start.isoformat()}&end={(start + timedelta(days=4)).isoformat()}"
        )
        assert resp.status_code == 200
        body = resp.json()

        assert body["total"] == 5
        assert len(body["snapshots"]) == 5
        # 升序
        dates = [s["snapshot_date"] for s in body["snapshots"]]
        assert dates == sorted(dates)
        # macro_detail 已反序列化
        assert isinstance(body["snapshots"][0]["macro_detail"], dict)

    async def test_400_on_inverted_range(self, client: AsyncClient) -> None:
        """``start > end`` → 400 + code=invalid_date_range。"""
        resp = await client.get("/api/v1/snapshots/in-range?start=2026-10-10&end=2026-10-01")
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail["code"] == "invalid_date_range"

    async def test_400_on_range_too_wide(self, client: AsyncClient) -> None:
        """范围 > 730 天（2 年）→ 400 + code=date_range_too_wide。"""
        resp = await client.get("/api/v1/snapshots/in-range?start=2020-01-01&end=2026-12-31")
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail["code"] == "date_range_too_wide"

    async def test_400_on_equal_endpoints_actually_works(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """``start == end`` 是合法边界（1 行返回），不是 400。"""
        target = date(2026, 10, 1)
        await _seed(db_session, target)

        resp = await client.get(
            f"/api/v1/snapshots/in-range?start={target.isoformat()}&end={target.isoformat()}"
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    async def test_empty_range_returns_empty(self, client: AsyncClient) -> None:
        """合法范围 + DB 空 → 200 + 空 list（不抛 404）。"""
        resp = await client.get("/api/v1/snapshots/in-range?start=2026-07-01&end=2026-07-07")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
        assert resp.json()["snapshots"] == []

    async def test_422_on_missing_query_params(self, client: AsyncClient) -> None:
        """缺 start 或 end → 422（FastAPI 必填参数校验）。"""
        r1 = await client.get("/api/v1/snapshots/in-range?start=2026-10-01")
        r2 = await client.get("/api/v1/snapshots/in-range?end=2026-10-01")
        r3 = await client.get("/api/v1/snapshots/in-range")
        assert r1.status_code == 422
        assert r2.status_code == 422
        assert r3.status_code == 422
