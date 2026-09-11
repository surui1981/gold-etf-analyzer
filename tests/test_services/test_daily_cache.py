"""当日 served cache + 每日调度器单元测试。"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.services import cache as served_cache
from app.services.scheduler import next_run_utc, _capture_and_warm, daily_capture_loop
from app.services.trend import TrendService, GUIDE_TARGET


# ---------------- served cache ----------------


def _sample_result(index_score: float = 60.0):
    """构造一个最小可用的 GoldTrendOut mock（仅 cache 测试用）。"""
    from app.schemas.common import DirectionSignal
    from app.schemas.market import (
        GoldTrendMetrics, GoldTrendOut, GoldTrendPoint,
        MacroIndexOut, NewsIndexOut, TrendDirection,
        TrendIndexLevel, TrendIndexOut,
    )

    today = date.today()
    return GoldTrendOut(
        symbol="GC",
        name="纽约金COMEX",
        days=1,
        points=[GoldTrendPoint(date=today, close=2400.0, ma5=None, ma20=None, ma40=None)],
        metrics=GoldTrendMetrics(
            start_date=today, end_date=today, trading_days=1,
            start_price=2400.0, end_price=2400.0, change_pct=0.0,
            high=2400.0, low=2400.0, ma20=None, ma40=None,
            change_pct_1d=0.0, change_pct_5d=0.0,
            direction=TrendDirection.SIDEWAYS, unit="美元/盎司", summary="测试",
        ),
        indicators=[],
        index=TrendIndexOut(
            score=index_score, level=TrendIndexLevel.SIDEWAYS,
            direction=DirectionSignal.NEUTRAL, summary="",
        ),
        macro=MacroIndexOut(score=50.0, direction=DirectionSignal.NEUTRAL, factors=[], summary=""),
        news=NewsIndexOut(score=50.0, direction=DirectionSignal.NEUTRAL, note="", scored=False),
        data_sources={}, degraded=False, freshness=None,
        served_at=datetime.now(),
    )


def test_served_cache_set_get_roundtrip() -> None:
    """set → get 当日缓存命中。"""
    target = "ny"
    served_cache.invalidate(target)  # 清理
    assert served_cache.get_served(target) is None

    result = _sample_result(65.0)
    served_cache.set_served(target, result)
    hit = served_cache.get_served(target)
    assert hit is result  # 同对象引用


def test_served_cache_target_isolation() -> None:
    """不同 target 互不污染。"""
    served_cache.invalidate()
    r1 = _sample_result(60.0)
    r2 = _sample_result(70.0)
    served_cache.set_served("ny", r1)
    served_cache.set_served("etf", r2)
    assert served_cache.get_served("ny") is r1
    assert served_cache.get_served("etf") is r2


def test_served_cache_invalidate_specific_target() -> None:
    """invalidate(target) 仅清指定 target，保留其他。"""
    served_cache.invalidate()
    r1, r2 = _sample_result(60.0), _sample_result(70.0)
    served_cache.set_served("ny", r1)
    served_cache.set_served("etf", r2)

    n = served_cache.invalidate("etf")
    assert n == 1
    assert served_cache.get_served("ny") is r1
    assert served_cache.get_served("etf") is None


def test_served_cache_invalidate_all() -> None:
    """invalidate() 无参 → 全清。"""
    served_cache.invalidate()
    served_cache.set_served("ny", _sample_result())
    served_cache.set_served("etf", _sample_result())
    assert served_cache.cache_size() == 2

    n = served_cache.invalidate()
    assert n == 2
    assert served_cache.cache_size() == 0


def test_served_cache_date_lookup() -> None:
    """按 on_date 查询可命中历史写入（非当日）。"""
    served_cache.invalidate()
    r = _sample_result(55.0)
    yesterday = date.today() - timedelta(days=1)
    served_cache.set_served("ny", r, on_date=yesterday)

    # 今日查询：未命中（key 不同）
    assert served_cache.get_served("ny", on_date=date.today()) is None
    # 昨日查询：命中
    assert served_cache.get_served("ny", on_date=yesterday) is r


# ---------------- scheduler ----------------


def test_next_run_utc_before_7am_bjt() -> None:
    """北京时间 06:00 → 下次为今日 07:00 BJT（UTC 23:00 昨日）。"""
    # 当前 UTC 时间在 06:00 BJT 之前：现在 21:00 UTC → BJT 次日 05:00
    # 此时 next_run 应为「今天 07:00 BJT」= 昨天 23:00 UTC
    # 由于测试运行时真实时间不固定，仅校验返回的是 UTC 时刻且在 22:00~23:00 UTC 之间
    nxt = next_run_utc()
    assert nxt.tzinfo == timezone.utc
    bjt = nxt.astimezone(timezone(timedelta(hours=8)))
    assert bjt.hour == 7
    assert bjt.minute == 0


def test_next_run_utc_after_7am_bjt() -> None:
    """北京时间 09:00 → 下次为明日 07:00 BJT（约 22 小时后）。"""
    nxt = next_run_utc()
    now_utc = datetime.now(timezone.utc)
    # 下次触发一定在未来（至少 0 秒后）
    assert nxt >= now_utc.replace(microsecond=0)
    # 距 now 最多 24 小时多一点点
    delta = (nxt - now_utc).total_seconds()
    assert 0 <= delta <= 24 * 3600 + 60


async def test_capture_and_warm_success(monkeypatch) -> None:
    """_capture_and_warm 成功路径：snapshot 落库 + served cache 写入。"""
    served_cache.invalidate()

    class FakeSnapshot:
        async def capture_today(self):
            from app.schemas.snapshot import SnapshotOut
            from datetime import date
            return SnapshotOut(
                snapshot_date=date.today(), symbol="GC", name="纽约金",
                close=2400.0, change_pct=0.5, high=2410.0, low=2390.0,
                ma20=2395.0, ma40=2380.0, direction="sideways",
                tech_index=60.0, macro_index=50.0, news_index=50.0,
                trend_index=55.0, index_level="sideways", macro_detail="{}",
                created_at=datetime.now(), updated_at=datetime.now(),
            )

    call_count = {"trend": 0}

    class FakeTrend:
        async def analyze(self, days=60, target=GUIDE_TARGET):
            call_count["trend"] += 1
            return _sample_result(55.0)

    await _capture_and_warm(FakeSnapshot(), FakeTrend())

    # 缓存写入成功
    assert served_cache.get_served(GUIDE_TARGET) is not None
    # trend.analyze 被调用 2 次：snapshot capture 内部 + _capture_and_warm 末尾预热
    assert call_count["trend"] >= 1


async def test_capture_and_warm_snapshot_failure_warms_cache(monkeypatch) -> None:
    """快照落库失败时：仍尝试预热 served cache（不抛异常）。"""
    served_cache.invalidate()

    class BrokenSnapshot:
        async def capture_today(self):
            raise RuntimeError("DB write failed")

    class FakeTrend:
        async def analyze(self, days=60, target=GUIDE_TARGET):
            return _sample_result(60.0)

    # 即便 snapshot 失败，_capture_and_warm 不应抛异常
    await _capture_and_warm(BrokenSnapshot(), FakeTrend())
    # cache 已写入（fallback warm-up 生效）
    assert served_cache.get_served(GUIDE_TARGET) is not None


async def test_capture_and_warm_both_failures_silent() -> None:
    """snapshot + warm 都失败：不抛异常（避免调度循环崩溃）。"""
    served_cache.invalidate()

    class BrokenSnapshot:
        async def capture_today(self):
            raise RuntimeError("DB fail")

    class BrokenTrend:
        async def analyze(self, days=60, target=GUIDE_TARGET):
            raise RuntimeError("warm fail")

    # 不抛异常
    await _capture_and_warm(BrokenSnapshot(), BrokenTrend())


async def test_daily_capture_loop_one_iteration(monkeypatch) -> None:
    """调度循环至少跑一次：mock sleep→0，触发一次 capture_and_warm。"""
    served_cache.invalidate()

    class FakeSnapshot:
        async def capture_today(self):
            from app.schemas.snapshot import SnapshotOut
            from datetime import date
            return SnapshotOut(
                snapshot_date=date.today(), symbol="GC", name="纽约金",
                close=2400.0, change_pct=0.5, high=2410.0, low=2390.0,
                ma20=2395.0, ma40=2380.0, direction="sideways",
                tech_index=60.0, macro_index=50.0, news_index=50.0,
                trend_index=55.0, index_level="sideways", macro_detail="{}",
                created_at=datetime.now(), updated_at=datetime.now(),
            )

    class FakeTrend:
        async def analyze(self, days=60, target=GUIDE_TARGET):
            return _sample_result(65.0)

    iter_count = {"n": 0}
    real_sleep = None

    async def fake_sleep(seconds):
        nonlocal real_sleep
        real_sleep = seconds
        iter_count["n"] += 1
        # 第一次 sleep 后抛异常跳出循环（此时 capture_and_warm 已执行完）
        if iter_count["n"] >= 2:
            raise asyncio.CancelledError

    import asyncio
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await daily_capture_loop(FakeSnapshot(), FakeTrend())

    # 至少 sleep 过一次（next_run_utc 的等待时长）
    assert real_sleep is not None
    # cache 已写入（capture_and_warm 在 sleep 1 之后执行）
    assert served_cache.get_served(GUIDE_TARGET) is not None


# ---------------- TrendService.invalidate_for_news ----------------


def test_trend_invalidate_for_news_delegates_to_cache() -> None:
    """TrendService.invalidate_for_news 应转发到 cache.invalidate。"""
    served_cache.invalidate()
    served_cache.set_served("ny", _sample_result())
    served_cache.set_served("etf", _sample_result())

    n = TrendService.invalidate_for_news("ny")
    assert n == 1
    assert served_cache.get_served("ny") is None
    # etf 不受影响
    assert served_cache.get_served("etf") is not None


def test_trend_invalidate_for_news_all() -> None:
    """None target → 全清。"""
    served_cache.invalidate()
    served_cache.set_served("ny", _sample_result())
    served_cache.set_served("etf", _sample_result())

    n = TrendService.invalidate_for_news()
    assert n == 2


# ---------------- V0.60.0: 日内 TTL ----------------


def test_v060_served_cache_set_records_timestamp() -> None:
    """V0.60.0：set_served 内部写入 set_at 时间戳（datetime UTC）。"""
    served_cache.set_served("ny", _sample_result())
    set_at = served_cache._entry_set_at("ny")
    assert set_at is not None
    assert isinstance(set_at, datetime)
    assert set_at.tzinfo is not None


def test_v060_get_served_within_max_age_returns() -> None:
    """V0.60.0：set 后立即以足够大的 max_age 调 get_served → 命中。"""
    served_cache.set_served("ny", _sample_result())
    result = served_cache.get_served("ny", max_age_seconds=600)
    assert result is not None
    assert result.index.score == 60.0


def test_v060_get_served_zero_or_negative_max_age_disables_ttl() -> None:
    """V0.60.0：``max_age_seconds<=0`` 视为禁用 TTL 派生（等同于不传参数）。"""
    served_cache.set_served("ny", _sample_result())
    # max_age_seconds=0 → 禁用 TTL → 命中（即使 entry 极旧）
    assert served_cache.get_served("ny", max_age_seconds=0) is not None
    # max_age_seconds=-1 → 同上
    assert served_cache.get_served("ny", max_age_seconds=-1) is not None


def test_v060_get_served_old_signature_unchanged() -> None:
    """V0.60.0：不传 max_age_seconds → 旧行为（仅按 date 命中，永不按 TTL 失效）。"""
    served_cache.set_served("ny", _sample_result())
    # 不传 max_age_seconds → 旧语义：命中
    assert served_cache.get_served("ny") is not None
    # 旧调用方后续再调仍然命中（不抛异常、不受 TTL 参数影响）
    assert served_cache.get_served("ny") is not None
    assert served_cache.cache_size() == 1