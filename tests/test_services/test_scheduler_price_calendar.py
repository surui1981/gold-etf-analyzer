"""价格日历自动刷新调度的单测（V0.128.4）。

背景（2026-11-24 用户报的故障）：
``gold_price_daily`` **没有任何调度器**去刷新它 —— 它只在「跑回测 / 研判复盘」时
按需回填 ⇒ 没人跑回测 ⇒ 价格日历停在 2026-11-11 ⇒
``scoring_daily_wide.gold_ny_close`` 变 NULL ⇒ scoring 页面「NY金收盘」列整列「—」。

本文件锁死三件事：
1. **触发时间计算**（每日 08:40 BJT，跨日正确）；
2. **环境变量开关**（``PRICE_CALENDAR_AUTO_REFRESH=0`` ⇒ 调度器不启动）；
3. ★ **只认真实行情**（mock 一律拒写）—— 这是本功能最关键的纪律：
   取数失败时 ``TrendService`` 会**静默降级为 mock** ⇒ mock 收盘价写进日历
   ⇒ 宽表/回测/区间预测全都基于**编造的价格**给出看似正常的结论 ⇒ 宁可留空。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import scheduler as sch
from app.services.scheduler import (
    BJT,
    PRICE_CALENDAR_AUTO_REFRESH_ENV,
    PRICE_CALENDAR_TRIGGER_HOUR_BJT,
    PRICE_CALENDAR_TRIGGER_MINUTE_BJT,
    _is_price_calendar_auto_refresh_enabled,
    next_price_calendar_run_utc,
)

# ── 1. 触发时间计算 ────────────────────────────────────────────────


def test_next_run_before_trigger_today() -> None:
    """当日触发点之前 → 就是今天那个点。"""
    now = datetime(2026, 11, 24, 0, 0, tzinfo=timezone.utc)  # = BJT 08:00
    nxt = next_price_calendar_run_utc(now)
    assert nxt.astimezone(BJT).hour == PRICE_CALENDAR_TRIGGER_HOUR_BJT
    assert nxt.astimezone(BJT).minute == PRICE_CALENDAR_TRIGGER_MINUTE_BJT
    assert nxt.astimezone(BJT).date() == datetime(2026, 11, 24, tzinfo=BJT).date()


def test_next_run_after_trigger_goes_to_tomorrow() -> None:
    """当日触发点已过 → 明天同一时刻。"""
    now = datetime(2026, 11, 24, 2, 0, tzinfo=timezone.utc)  # = BJT 10:00（已过 08:40）
    nxt = next_price_calendar_run_utc(now)
    assert (
        nxt.astimezone(BJT).date()
        == (datetime(2026, 11, 24, tzinfo=BJT) + timedelta(days=1)).date()
    )
    assert nxt.astimezone(BJT).hour == PRICE_CALENDAR_TRIGGER_HOUR_BJT


def test_next_run_is_in_the_future() -> None:
    """无论当前时刻，返回值必须在未来（调度器靠它 sleep）。"""
    now = datetime.now(timezone.utc)
    assert next_price_calendar_run_utc(now) > now


# ── 2. 环境变量开关 ────────────────────────────────────────────────


def test_enabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv(PRICE_CALENDAR_AUTO_REFRESH_ENV, raising=False)
    assert _is_price_calendar_auto_refresh_enabled() is True


@pytest.mark.parametrize("raw", ["0", "false", "no", "off", "OFF", ""])
def test_disabled_by_env(monkeypatch, raw: str) -> None:
    monkeypatch.setenv(PRICE_CALENDAR_AUTO_REFRESH_ENV, raw)
    assert _is_price_calendar_auto_refresh_enabled() is False


# ── 3. ★ 只认真实行情（mock 一律拒写）─────────────────────────────


class TestRefreshRejectsMock:
    """`_refresh_price_calendar` 必须拒写 mock —— 这是本功能最容易出事的地方。"""

    async def test_mock_source_is_not_written(self, monkeypatch) -> None:
        """取数降级成 mock ⇒ 一行都不许写。"""

        class _FakeTrend:
            async def fetch_price_bars(self, days: int = 30, target: str = "ny"):
                # ⚠ 真正危险的情形：取数失败时 TrendService **降级成 mock 并返回假价格**
                #   （不是空列表！）⇒ 若不拒写，假收盘价会进日历 ⇒ 宽表/回测/
                #   区间预测全都基于**编造的价格**给出看似正常的结论。
                from datetime import date as _d
                from datetime import timedelta as _td

                base = _d.today() - _td(days=5)
                return (
                    [(base + _td(days=i), 4500.0 + i) for i in range(5)],
                    {"ny": "mock"},
                )

        monkeypatch.setattr(
            "app.services.trend.TrendService", lambda *a, **k: _FakeTrend(), raising=False
        )

        written_calls: list = []

        class _FakeRepo:
            async def upsert_many(self, *, target: str, bars, source: str):
                # ⚠ 记录而不是抛异常：调度器把异常吞掉了（except Exception），
                #   抛异常的话测试分辨不出「尝试写」和「没写」⇒ 断言永远绿。
                written_calls.append((target, list(bars), source))
                return len(bars)

            async def latest(self, target: str):
                return None

        class _FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def commit(self):
                return None

        monkeypatch.setattr("app.repositories.review.GoldPriceRepository", lambda s: _FakeRepo())
        monkeypatch.setattr("app.repositories.db.async_session_factory", lambda: _FakeSession())

        n = await sch._refresh_price_calendar()
        assert n == 0
        assert written_calls == [], f"mock 数据被写进了价格日历：{written_calls}"


# ── 4. 重建只动「已存在」的行（不得凭空造行）────────────────────────


class TestRebuildOnlyExistingRows:
    """`rebuild()` 对没有 snapshot 的日期会**新建**一行 ⇒ 那是造数据，不是补数据。"""

    async def test_rebuild_skips_dates_without_existing_row(self, monkeypatch) -> None:
        rebuilt: list = []

        class _FakeWideService:
            def __init__(self, *a, **k):
                pass

            async def rebuild(self, d, user_id=None):
                rebuilt.append(d)
                return object()

        class _FakeRepo:
            async def list_dates(self, user_id=None):
                # 只有这一天「已存在」
                return [datetime.now(BJT).date() - timedelta(days=1)]

        monkeypatch.setattr(
            "app.services.scoring_wide.ScoringWideService", _FakeWideService, raising=False
        )
        monkeypatch.setattr(
            "app.repositories.scoring_wide.ScoringWideRepository", lambda s: _FakeRepo()
        )
        monkeypatch.setattr("app.repositories.snapshot.SnapshotRepository", lambda s: object())
        monkeypatch.setattr("app.repositories.news.NewsScoreRepository", lambda s: object())

        class _FakeGoldRepo:
            async def upsert_many(self, *, target: str, bars, source: str):
                return len(bars)

        monkeypatch.setattr(
            "app.repositories.review.GoldPriceRepository", lambda s: _FakeGoldRepo()
        )

        # 让取价走通（否则会在 upsert 前就 return 0，走不到重建分支）
        class _FakeTrend:
            async def fetch_price_bars(self, days: int = 30, target: str = "ny"):
                from datetime import date as _d

                return ([(_d.today(), 3000.0)], {"ny": "live"})

        monkeypatch.setattr(
            "app.services.trend.TrendService", lambda *a, **k: _FakeTrend(), raising=False
        )

        class _FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def commit(self):
                return None

        monkeypatch.setattr("app.repositories.db.async_session_factory", lambda: _FakeSession())

        await sch._refresh_price_calendar()
        # 只重建了「已存在」的那一天，没有为其它日期造行
        assert len(rebuilt) == 1
        assert rebuilt[0] == datetime.now(BJT).date() - timedelta(days=1)
