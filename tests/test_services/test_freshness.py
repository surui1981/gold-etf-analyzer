"""数据时效服务测试（UX 6.1）：时效分级 + 交易时段 + 采集元信息。"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.repositories.market_data import GoldKline, MarketDataRepository
from app.schemas.market import FreshnessOut
from app.services.freshness import FreshnessService, build_data_freshness
from app.utils.market_clock import FreshnessLevel, SessionState, classify_freshness

_CN = ZoneInfo("Asia/Shanghai")
# 2026-09-02 20:00 北京（周三）→ 纽约金处于交易中
_NOW = datetime(2026, 9, 2, 20, 0, tzinfo=_CN)


class FakeProvider:
    """假数据源：返回固定 5 根 K 线，不触网。"""

    def __init__(self, last_date: date = date(2026, 9, 2)) -> None:
        self._last_date = last_date

    def _series(self, days: int) -> list[GoldKline]:
        return [
            GoldKline(
                date=date(2026, 9, 2) if i == days - 1 else self._last_date,
                open=5.0,
                close=5.0 + i * 0.02,
                high=5.1,
                low=4.9,
                volume=100.0,
            )
            for i in range(days)
        ]

    async def get_history(self, symbol: str, days: int = 60) -> list[GoldKline]:
        return self._series(days)

    async def get_gram_history(self, symbol: str = "Au99.99", days: int = 60) -> list[GoldKline]:
        return self._series(days)

    async def get_us_gold_history(self, symbol: str = "GC", days: int = 60) -> list[GoldKline]:
        return self._series(days)


class FakeMetaRepo:
    """假仓储：仅提供采集元信息，不带取数方法（用于验证不崩、不触网）。"""

    def __init__(self, meta: dict | None = None) -> None:
        self._meta = meta or {}

    def source_meta(self) -> dict:
        return self._meta


def test_build_data_freshness_realtime() -> None:
    """交易中 + 数据截止当日 → 实时。"""
    out = build_data_freshness(
        "ny", status="live", data_date=date(2026, 9, 2), fetched_at=_NOW, now=_NOW
    )
    assert out.market == "ny"
    assert out.status == "live"
    assert out.freshness == FreshnessLevel.REALTIME
    assert out.freshness_label == "实时"
    assert out.data_date == "2026-09-02"
    assert out.age_minutes == 0.0
    assert out.session.market == "ny"
    assert out.session.state == SessionState.OPEN.value


def test_build_data_freshness_degraded_states() -> None:
    """mock → 演示；stale → 缓存；无采集 → 未采集（绝不静默）。"""
    mock = build_data_freshness("etf", status="mock", data_date=date(2026, 9, 2), now=_NOW)
    assert mock.freshness == FreshnessLevel.MOCK
    assert "演示" in mock.freshness_label

    cached = build_data_freshness("sge", status="stale", data_date=date(2026, 9, 2), now=_NOW)
    assert cached.freshness == FreshnessLevel.CACHED
    assert "缓存" in cached.freshness_label

    unknown = build_data_freshness("etf", status="-", data_date=None, now=_NOW)
    assert unknown.freshness == FreshnessLevel.UNKNOWN
    assert unknown.data_date == ""
    assert unknown.age_minutes == -1.0


def test_build_data_freshness_age_minutes() -> None:
    """采集时间差按分钟计算，供页面显示「N 分钟前采集」。"""
    fetched = datetime(2026, 9, 2, 19, 25, tzinfo=_CN)
    out = build_data_freshness("ny", status="live", data_date=date(2026, 9, 2), fetched_at=fetched, now=_NOW)
    assert out.age_minutes == 35.0


async def test_report_returns_all_markets() -> None:
    """时效报告覆盖三个市场，并汇总时段与时效。"""
    meta = {
        "ny": {"status": "live", "fetched_at": _NOW, "last_date": date(2026, 9, 2)},
        "sge": {"status": "stale", "fetched_at": _NOW, "last_date": date(2026, 9, 1)},
        "etf": {"status": "mock", "fetched_at": None, "last_date": None},
    }
    out = await FreshnessService(FakeMetaRepo(meta)).report(now=_NOW)

    assert isinstance(out, FreshnessOut)
    assert set(out.markets) == {"ny", "sge", "etf"}
    assert out.markets["ny"].freshness == FreshnessLevel.REALTIME
    assert out.markets["sge"].freshness == FreshnessLevel.CACHED
    assert out.markets["etf"].freshness == FreshnessLevel.MOCK
    assert out.degraded is True
    assert "纽约金" in out.summary
    assert out.markets["ny"].age_minutes == 0.0
    assert out.markets["etf"].age_minutes == -1.0


async def test_report_without_meta_is_unknown() -> None:
    """仓储无采集元信息时（冷启动），全部判为未采集且不降级，接口不报错。"""
    out = await FreshnessService(FakeMetaRepo({})).report(now=_NOW)
    assert set(out.markets) == {"ny", "sge", "etf"}
    assert all(v.freshness == FreshnessLevel.UNKNOWN for v in out.markets.values())
    assert out.degraded is False


async def test_report_handles_repo_without_source_meta() -> None:
    """替身对象缺少 source_meta 方法时不应崩溃（兼容老替身）。"""

    class Bare:
        pass

    out = await FreshnessService(Bare()).report(now=_NOW)  # type: ignore[arg-type]
    assert set(out.markets) == {"ny", "sge", "etf"}


async def test_repo_records_fetch_meta() -> None:
    """仓储采集成功后记录状态、采集时刻与数据截止日（供时效展示）。"""
    repo = MarketDataRepository(provider=FakeProvider())
    await repo.get_gold_history(days=5)

    meta = repo.source_meta()
    assert meta["etf"]["status"] == "live"
    assert meta["etf"]["last_date"] == date(2026, 9, 2)
    assert meta["etf"]["fetched_at"] is not None
    assert repo.source_status()["etf"] == "live"


async def test_repo_records_all_markets_meta() -> None:
    """三个市场各自记录元信息，互不影响。"""
    repo = MarketDataRepository(provider=FakeProvider())
    await repo.get_us_gold_history(days=5)
    await repo.get_gold_gram_history(days=5)
    await repo.get_gold_history(days=5)

    meta = repo.source_meta()
    assert set(meta) == {"ny", "sge", "etf"}
    assert all(v["last_date"] == date(2026, 9, 2) for v in meta.values())


async def test_repo_marks_mock_when_provider_fails() -> None:
    """数据源异常时标记为 mock，时效判定随之降级为演示。"""

    class BoomProvider:
        async def get_history(self, symbol: str, days: int = 60) -> list[GoldKline]:
            raise RuntimeError("network down")

        async def get_gram_history(self, symbol: str = "Au99.99", days: int = 60) -> list[GoldKline]:
            raise RuntimeError("network down")

        async def get_us_gold_history(self, symbol: str = "GC", days: int = 60) -> list[GoldKline]:
            raise RuntimeError("network down")

    repo = MarketDataRepository(provider=BoomProvider())
    # days=7 为本用例专用：确保磁盘无历史缓存可兜底（否则会降级为 stale 而非 mock）
    await repo.get_gold_history(days=7)

    meta = repo.source_meta()
    assert meta["etf"]["status"] == "mock"
    assert (
        classify_freshness(
            status=meta["etf"]["status"],
            data_date=meta["etf"]["last_date"],
            session_state=SessionState.OPEN,
            now=_NOW,
        )
        == FreshnessLevel.MOCK
    )


@pytest.mark.parametrize("market", ["ny", "sge", "etf"])
def test_build_data_freshness_covers_all_markets(market: str) -> None:
    """三个市场均可构造时效输出，且携带各自交易时段。"""
    out = build_data_freshness(market, status="live", data_date=date(2026, 9, 2), now=_NOW)
    assert out.market == market
    assert out.session.market == market
    assert out.session.state in {"open", "pre", "break", "closed"}
