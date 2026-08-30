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
        return MacroIndexOut(score=50.0, direction=DirectionSignal.NEUTRAL, factors=[], summary="测试")


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
    assert out.symbol == "518880"
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
