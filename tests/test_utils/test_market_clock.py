"""交易时段与数据时效判定测试（UX 6.1：数据时效与语境透明）。"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.utils.market_clock import (
    FreshnessLevel,
    SessionState,
    classify_freshness,
    etf_session,
    freshness_label,
    ny_gold_session,
    sge_session,
    trading_days_between,
)

_ET = ZoneInfo("America/New_York")
_CN = ZoneInfo("Asia/Shanghai")


def _at_et(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    """构造美东时间时刻（自动带夏令时偏移）。"""
    return datetime(year, month, day, hour, minute, tzinfo=_ET)


def _at_cn(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    """构造北京时间时刻。"""
    return datetime(year, month, day, hour, minute, tzinfo=_CN)


# 参照日期：2026-08-31 周一、09-02 周三、09-03 周四、09-04 周五、09-05 周六、09-06 周日


@pytest.mark.parametrize(
    ("label", "moment", "expected"),
    [
        ("周三盘中", _at_et(2026, 9, 2, 10, 0), SessionState.OPEN),
        ("周三结算间歇", _at_et(2026, 9, 2, 17, 30), SessionState.BREAK),
        ("周五盘中", _at_et(2026, 9, 4, 16, 0), SessionState.OPEN),
        ("周五收盘后", _at_et(2026, 9, 4, 18, 0), SessionState.CLOSED),
        ("周六全天", _at_et(2026, 9, 5, 12, 0), SessionState.CLOSED),
        ("周日开盘前", _at_et(2026, 9, 6, 17, 0), SessionState.PRE),
        ("周日开盘后", _at_et(2026, 9, 6, 19, 0), SessionState.OPEN),
    ],
)
def test_ny_gold_session_states(label: str, moment: datetime, expected: SessionState) -> None:
    """纽约金近乎全天连续交易：周末休市、每日 17:00-18:00 结算间歇。"""
    assert ny_gold_session(moment).state == expected


@pytest.mark.parametrize(
    ("label", "moment", "expected"),
    [
        ("周二凌晨夜盘", _at_cn(2026, 9, 1, 1, 0), SessionState.OPEN),
        ("周二早盘", _at_cn(2026, 9, 1, 10, 0), SessionState.OPEN),
        ("周二午休", _at_cn(2026, 9, 1, 12, 0), SessionState.BREAK),
        ("周二午盘", _at_cn(2026, 9, 1, 14, 0), SessionState.OPEN),
        ("周四夜盘", _at_cn(2026, 9, 3, 22, 0), SessionState.OPEN),
        ("周五盘后无夜盘", _at_cn(2026, 9, 4, 18, 0), SessionState.CLOSED),
        ("周六休市", _at_cn(2026, 9, 5, 10, 0), SessionState.CLOSED),
        ("周一凌晨无夜盘", _at_cn(2026, 8, 31, 1, 0), SessionState.PRE),
    ],
)
def test_sge_session_states(label: str, moment: datetime, expected: SessionState) -> None:
    """上海金：夜盘 + 早盘 + 午盘，周五无夜盘，周末休市。"""
    assert sge_session(moment).state == expected


@pytest.mark.parametrize(
    ("label", "moment", "expected"),
    [
        ("周二盘前", _at_cn(2026, 9, 1, 9, 0), SessionState.PRE),
        ("周二早盘", _at_cn(2026, 9, 1, 10, 0), SessionState.OPEN),
        ("周二午休", _at_cn(2026, 9, 1, 12, 0), SessionState.BREAK),
        ("周二午盘", _at_cn(2026, 9, 1, 14, 0), SessionState.OPEN),
        ("周二已收盘", _at_cn(2026, 9, 1, 16, 0), SessionState.CLOSED),
        ("周六休市", _at_cn(2026, 9, 5, 10, 0), SessionState.CLOSED),
    ],
)
def test_etf_session_states(label: str, moment: datetime, expected: SessionState) -> None:
    """黄金 ETF 跟随上交所时段：09:30-11:30 / 13:00-15:00。"""
    assert etf_session(moment).state == expected


def test_session_carries_context() -> None:
    """时段快照应携带交易时间、下一时点与语境说明，供页面 tooltip 展示。"""
    session = ny_gold_session(_at_et(2026, 9, 2, 10, 0))
    assert session.is_open is True
    assert session.state_label == "交易中"
    assert len(session.windows) >= 2
    assert any("17:00" in w for w in session.windows)
    assert session.next_event


@pytest.mark.parametrize(
    ("status", "data_date", "session_state", "expected"),
    [
        ("live", date(2026, 9, 2), SessionState.OPEN, FreshnessLevel.REALTIME),
        ("live", date(2026, 9, 5), SessionState.CLOSED, FreshnessLevel.DELAYED),
        ("live", date(2026, 9, 1), SessionState.OPEN, FreshnessLevel.T1),
        ("live", date(2026, 8, 30), SessionState.OPEN, FreshnessLevel.LAGGED),
        ("stale", date(2026, 9, 2), SessionState.OPEN, FreshnessLevel.CACHED),
        ("mock", date(2026, 9, 2), SessionState.OPEN, FreshnessLevel.MOCK),
        ("-", None, SessionState.OPEN, FreshnessLevel.UNKNOWN),
    ],
)
def test_classify_freshness(
    status: str,
    data_date: date | None,
    session_state: SessionState,
    expected: FreshnessLevel,
) -> None:
    """时效分级：数据源状态优先，再按数据截止日与当日的时间差分级。"""
    now = _at_cn(2026, 9, 2, 20, 0)  # 周三 20:00 北京 → 纽约金交易中
    assert (
        classify_freshness(status=status, data_date=data_date, session_state=session_state, now=now)
        == expected
    )


def test_classify_freshness_delayed_on_weekend() -> None:
    """周末休市时，即使数据截止当日也只能判为延时（盘后静态价），不可标为实时。"""
    now = _at_cn(2026, 9, 5, 12, 0)  # 周六
    assert (
        classify_freshness(
            status="live", data_date=date(2026, 9, 5), session_state=SessionState.CLOSED, now=now
        )
        == FreshnessLevel.DELAYED
    )


# ───────────────────── V0.109.2：trading_days_between 单位测试 ─────────────────────


def test_trading_days_between_same_day() -> None:
    """V0.109.2：同日（含两端）= 1。"""
    assert trading_days_between(date(2026, 10, 20), date(2026, 10, 20)) == 1


def test_trading_days_between_midweek() -> None:
    """V0.109.2：周三→周五（中间无周末）= 3。"""
    assert trading_days_between(date(2026, 10, 14), date(2026, 10, 16)) == 3


def test_trading_days_between_across_weekend() -> None:
    """V0.109.2：周五→下周二 = 3（周五 + 周一 + 周二，跳过周末）。"""
    assert trading_days_between(date(2026, 10, 16), date(2026, 10, 20)) == 3


def test_trading_days_between_sunday_to_monday() -> None:
    """V0.109.2：周日→周一 = 1（只周一工作日，周日不计）。

    这是白银 SGE akshare 接口常见状态：周日 18:00 的数据，

    如果周一拉，trading_days_between = 1，max_lag_days=1 时不算 stale。
    """
    assert trading_days_between(date(2026, 10, 18), date(2026, 10, 19)) == 1


def test_trading_days_between_sunday_to_tuesday() -> None:
    """V0.109.2：周日→周二 = 2（周一 + 周二）→ 应触发 stale。

    这是本次故障的真实状态：2026-10-20 周二拉 akshare

    接口拿到 10-18 周日数据，trading_days_between = 2 > 1 → 标 fallback。
    """
    assert trading_days_between(date(2026, 10, 18), date(2026, 10, 20)) == 2


def test_trading_days_between_saturday_sunday_only_returns_0() -> None:
    """V0.109.2：周六→周日 = 0（两天都不是工作日）。"""
    assert trading_days_between(date(2026, 10, 17), date(2026, 10, 18)) == 0


def test_trading_days_between_reverse_returns_0() -> None:
    """V0.109.2：逆序 end < start 返回 0（staleness 永远不算 stale，让上层走其他判定）。"""
    assert trading_days_between(date(2026, 10, 20), date(2026, 10, 18)) == 0


def test_freshness_labels_cover_all_levels() -> None:
    """每个时效等级都有中文标签，避免前端出现 undefined。"""
    for level in FreshnessLevel:
        assert freshness_label(level)
