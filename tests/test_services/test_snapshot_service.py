"""每日快照服务单元测试：捕获、按日 upsert、惰性历史。"""

from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.market_data import GoldKline
from app.repositories.snapshot import SnapshotRepository
from app.schemas.common import DirectionSignal
from app.schemas.market import MacroIndexOut
from app.services.snapshot import DailySnapshotService
from app.services.trend import TrendService


class FakeRepo:
    """假行情：确定性上升序列。"""

    def __init__(self, klines: list[GoldKline]) -> None:
        self._k = klines

    async def get_gold_history(self, days: int = 60) -> list[GoldKline]:
        return self._k

    async def get_gold_gram_history(self, days: int = 60) -> list[GoldKline]:
        return self._k

    async def get_us_gold_history(self, days: int = 60) -> list[GoldKline]:
        return self._k


class FakeMacro:
    """假宏观：固定中性分。"""

    async def evaluate(self) -> MacroIndexOut:
        return MacroIndexOut(
            score=50.0, direction=DirectionSignal.NEUTRAL, factors=[], summary="测试"
        )


def _mk_klines() -> list[GoldKline]:
    closes = [round(1 + i * 0.01, 3) for i in range(60)]
    base = date(2026, 6, 1)
    return [
        GoldKline(date=base + timedelta(days=i), open=c, close=c, high=c, low=c, volume=0.0)
        for i, c in enumerate(closes)
    ]


def _service(db: AsyncSession) -> DailySnapshotService:
    trend = TrendService(FakeRepo(_mk_klines()), macro=FakeMacro())
    return DailySnapshotService(SnapshotRepository(db), trend)


async def test_capture_creates_snapshot(db_session: AsyncSession) -> None:
    svc = _service(db_session)
    out = await svc.capture_today()

    assert out.snapshot_date == date.today()
    assert out.symbol == "GC"
    assert "纽约金" in out.name
    assert out.tech_index > 0
    assert out.macro_index == 50.0
    assert out.trend_index > 0
    assert out.close > 0


async def test_capture_is_upsert_by_date(db_session: AsyncSession) -> None:
    svc = _service(db_session)
    await svc.capture_today()
    await svc.capture_today()  # 同日重复捕获 → 更新而非新增

    snaps = await SnapshotRepository(db_session).list_recent(10)
    assert len(snaps) == 1


async def test_list_history_lazy_capture(db_session: AsyncSession) -> None:
    svc = _service(db_session)
    result = await svc.list_history(days=10)

    assert result.total >= 1  # 当日无快照时自动捕获
    assert result.snapshots[0].snapshot_date == date.today()


async def test_v063_list_history_news_index_present(db_session: AsyncSession) -> None:
    """V0.63.0：list_history 返回的每条快照都含 news_index 字段（消息面曲线数据来源）。"""
    svc = _service(db_session)
    result = await svc.list_history(days=7)

    assert result.total >= 1
    for snap in result.snapshots:
        assert hasattr(snap, "news_index")
        assert isinstance(snap.news_index, (int, float))
        assert 0 <= snap.news_index <= 100  # 未打分场景下默认 50.0


async def test_v063_list_history_no_duplicate_dates(db_session: AsyncSession) -> None:
    """V0.63.0：list_history(days=N) 返回列表 snapshot_date 无重复（防御 upsert 失败导致翻倍）。"""
    svc = _service(db_session)
    # 连续调用两次（均触发惰性补当日）—— 同日只应保留 1 条
    await svc.list_history(days=5)
    result = await svc.list_history(days=5)

    dates = [s.snapshot_date for s in result.snapshots]
    assert len(dates) == len(set(dates)), f"重复日期：{dates}"
    assert result.total <= 5


# ──────────────── V0.90.0 · get_in_range ────────────────


async def _insert(
    session: AsyncSession,
    snapshot_date: date,
    *,
    macro_json: str | None = '{"DXY": {"value": 104.5}}',
) -> None:
    """直接向 DB 插入指定日期的 DailySnapshot（绕过 capture_today，加快测试）。

    ``macro_detail`` 是 NOT NULL 列（V0.79.0 设计：snapshot 必带宏观因子；缺失时
    不写快照而不是写 NULL）。默认提供最小合法 JSON；测试可显式覆盖。
    """
    from app.models.snapshot import DailySnapshot

    session.add(
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
    await session.commit()


class TestGetInRange:
    """V0.90.0 新增 ``DailySnapshotService.get_in_range(start, end)`` 薄包装层。"""

    async def test_empty_db_returns_empty_list(self, db_session: AsyncSession) -> None:
        """空 DB → 空 list（不抛异常）。"""
        svc = _service(db_session)
        result = await svc.get_in_range(date(2026, 10, 1), date(2026, 10, 7))
        assert result == []

    async def test_inclusive_endpoints_with_ascending_order(self, db_session: AsyncSession) -> None:
        """含首尾 + 按日期升序（timeline 聚合的预期顺序）。"""
        start = date(2026, 10, 1)
        # 倒序插入 5 行
        for i in [4, 2, 0, 3, 1]:
            await _insert(db_session, start + timedelta(days=i))

        svc = _service(db_session)
        result = await svc.get_in_range(start, start + timedelta(days=4))

        assert len(result) == 5
        dates = [s.snapshot_date for s in result]
        assert dates == sorted(dates)
        assert dates[0] == start
        assert dates[-1] == start + timedelta(days=4)

    async def test_macro_detail_is_deserialized_to_dict(self, db_session: AsyncSession) -> None:
        """macro_detail str JSON 字符串 → 自动反序列化为 dict（V0.90.0 schema 修复的端到端路径）。"""
        await _insert(
            db_session,
            date(2026, 10, 1),
            macro_json='{"DXY": {"value": 104.5}, "US10Y": {"value": 4.2}}',
        )

        svc = _service(db_session)
        result = await svc.get_in_range(date(2026, 10, 1), date(2026, 10, 1))

        assert len(result) == 1
        macro = result[0].macro_detail
        assert isinstance(macro, dict)
        assert macro["DXY"]["value"] == 104.5
        assert macro["US10Y"]["value"] == 4.2

    async def test_inverted_range_returns_empty(self, db_session: AsyncSession) -> None:
        """``start > end`` → 空 list（仓储层语义透传）。"""
        await _insert(db_session, date(2026, 10, 5))
        svc = _service(db_session)
        result = await svc.get_in_range(date(2026, 10, 10), date(2026, 10, 1))
        assert result == []

    async def test_sparse_data_preserves_gaps(self, db_session: AsyncSession) -> None:
        """稀疏数据：只返回已存在行（中间不补全，调用方需自己决定如何渲染空洞）。"""
        await _insert(db_session, date(2026, 10, 1))
        await _insert(db_session, date(2026, 10, 5))
        await _insert(db_session, date(2026, 10, 8))

        svc = _service(db_session)
        result = await svc.get_in_range(date(2026, 10, 1), date(2026, 10, 10))

        assert len(result) == 3
        assert {s.snapshot_date for s in result} == {
            date(2026, 10, 1),
            date(2026, 10, 5),
            date(2026, 10, 8),
        }

    async def test_returns_snapshot_out_instances(self, db_session: AsyncSession) -> None:
        """返回类型是 ``SnapshotOut``（含所有 schema validator），不是裸 ORM。"""
        await _insert(db_session, date(2026, 10, 1))
        svc = _service(db_session)
        result = await svc.get_in_range(date(2026, 10, 1), date(2026, 10, 1))

        from app.schemas.snapshot import SnapshotOut

        assert isinstance(result[0], SnapshotOut)
        # snapshot_date 已被 Pydantic 转 date 类型（与 ORM 行为一致，但由 schema 守门）
        assert isinstance(result[0].snapshot_date, date)
