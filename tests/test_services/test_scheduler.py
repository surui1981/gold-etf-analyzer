"""scheduler 单测：央行购金月度调度时间计算 + 开关 + 循环节流。

不引入 APScheduler / cron，纯 asyncio + 日历算术；测试聚焦：
- next_central_bank_run_utc() 在不同 BJT 时刻返回正确的下一个触发日
- 月末动态计算（28/29/30/31 天月）
- 环境变量 CENTRAL_BANK_AUTO_REFRESH 关闭时调度器不启动
- _refresh_central_bank 失败仅日志，不抛
"""

from datetime import datetime, timezone

import pytest

from app.services import scheduler as sch
from app.services.scheduler import (
    BJT,
    CB_TRIGGER_HOUR_BJT,
    CB_TRIGGER_MINUTE_BJT,
    _is_cb_auto_refresh_enabled,
    next_central_bank_run_utc,
)


# ── next_central_bank_run_utc 时间计算 ────────────────────────────


def test_next_run_mid_month_before_15() -> None:
    """月初触发点之后、月中触发点之前 → 等当月 15 日。"""
    # BJT 2026-09-07 14:00（刚过 9/1 07:30，未到 9/15 07:30）
    fixed_utc = datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc)  # = BJT 22:00
    # Actually 2026-09-07 14:00 UTC = 2026-09-07 22:00 BJT
    # After 09-01 07:30, before 09-15 07:30 → expect 2026-09-15 07:30 BJT = 2026-09-14 23:30 UTC
    expected_utc = datetime(2026, 9, 14, 23, 30, tzinfo=timezone.utc)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sch, "datetime", _FrozenDatetime(fixed_utc))
        result = next_central_bank_run_utc()
    assert result == expected_utc


def test_next_run_after_mid_15() -> None:
    """月中触发点之后、月末触发点之前 → 等当月末日。"""
    # BJT 2026-09-16 08:00 → UTC 2026-09-16 00:00
    # After 09-15 07:30, before 09-30 07:30 → expect 2026-09-30 07:30 BJT
    fixed_utc = datetime(2026, 9, 16, 0, 0, tzinfo=timezone.utc)
    expected_utc = datetime(2026, 9, 29, 23, 30, tzinfo=timezone.utc)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sch, "datetime", _FrozenDatetime(fixed_utc))
        result = next_central_bank_run_utc()
    assert result == expected_utc


def test_next_run_after_month_end() -> None:
    """月初触发点之后、月中触发点之前 → 等月中 15 日。"""
    # BJT 2026-10-01 08:00 = UTC 2026-10-01 00:00
    # 10/01 07:30 BJT 已过（= 09/30 23:30 UTC）；下一个候选是 10/15
    fixed_utc = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
    # 10/15 07:30 BJT = 10/14 23:30 UTC
    expected_utc = datetime(2026, 10, 14, 23, 30, tzinfo=timezone.utc)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sch, "datetime", _FrozenDatetime(fixed_utc))
        result = next_central_bank_run_utc()
    assert result == expected_utc


def test_next_run_after_month_15() -> None:
    """月中触发点之后、月末触发点之前 → 等月末。"""
    # BJT 2026-10-16 08:00 = UTC 2026-10-16 00:00
    # 10/15 07:30 BJT 已过（= 10/14 23:30 UTC）；下一个候选是 10/31
    fixed_utc = datetime(2026, 10, 16, 0, 0, tzinfo=timezone.utc)
    # 10/31 07:30 BJT = 10/30 23:30 UTC
    expected_utc = datetime(2026, 10, 30, 23, 30, tzinfo=timezone.utc)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sch, "datetime", _FrozenDatetime(fixed_utc))
        result = next_central_bank_run_utc()
    assert result == expected_utc


def test_next_run_late_december_rollover() -> None:
    """年末最后两天之后 → 下年 1 月 1 日。"""
    # BJT 2026-12-31 08:00 = UTC 2026-12-31 00:00
    # 12/01, 12/15, 12/31 07:30 都已过（12/31 = 12/30 23:30 UTC）
    # 下一个候选：2027/01/01 07:30 BJT = 2026/12/31 23:30 UTC
    fixed_utc = datetime(2026, 12, 31, 0, 0, tzinfo=timezone.utc)
    expected_utc = datetime(2026, 12, 31, 23, 30, tzinfo=timezone.utc)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sch, "datetime", _FrozenDatetime(fixed_utc))
        result = next_central_bank_run_utc()
    assert result == expected_utc


def test_next_run_exactly_at_trigger() -> None:
    """恰好在触发时刻之后 → 等下一个候选。"""
    # BJT 2026-09-01 07:30:01 → 触发已过，等 09/15 07:30 BJT
    fixed_utc = datetime(2026, 8, 31, 23, 30, 1, tzinfo=timezone.utc)
    expected_utc = datetime(2026, 9, 14, 23, 30, tzinfo=timezone.utc)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sch, "datetime", _FrozenDatetime(fixed_utc))
        result = next_central_bank_run_utc()
    assert result == expected_utc


@pytest.mark.parametrize("last_day,expected_day,month_in", [
    (28, 28, 2),  # 平年 2 月（2023）
    (29, 29, 2),  # 闰年 2 月（2024）
    (30, 30, 4),  # 30 天月（4 月）
    (31, 31, 1),  # 31 天月（1 月）
])
def test_next_run_month_end_dynamic(last_day: int, expected_day: int, month_in: int) -> None:
    """月末动态计算：2/4 月等不到 31 日。"""
    # BJT 2023-02-16 08:00 → after 02/15 07:30, before 02/28 07:30 (平年) → expect 02/28
    fixed_utc = datetime(2023, 2, 16, 0, 0, tzinfo=timezone.utc) if last_day == 28 else \
                datetime(2024, 2, 16, 0, 0, tzinfo=timezone.utc) if last_day == 29 else \
                datetime(2026, 4, 16, 0, 0, tzinfo=timezone.utc) if last_day == 30 else \
                datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)
    # 触发时刻 07:30 BJT = 前一天 23:30 UTC
    expected_utc = datetime(fixed_utc.year, month_in, expected_day, tzinfo=BJT).astimezone(timezone.utc)
    expected_utc = expected_utc.replace(day=expected_day, hour=23, minute=30, second=0, microsecond=0)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sch, "datetime", _FrozenDatetime(fixed_utc))
        result = next_central_bank_run_utc()
    # 比较：应指向当月 last_day 的 07:30 BJT
    expected_bjt = fixed_utc.astimezone(BJT).replace(
        month=month_in, day=expected_day,
        hour=CB_TRIGGER_HOUR_BJT, minute=CB_TRIGGER_MINUTE_BJT,
        second=0, microsecond=0,
    )
    assert result == expected_bjt.astimezone(timezone.utc)


def test_next_run_year_rollover() -> None:
    """12 月 16 日 → 等月末（12/31）。"""
    # BJT 2026-12-16 08:00 = UTC 2026-12-16 00:00
    # 12/01, 12/15 已过 → 下一个候选 12/31 07:30 BJT = 12/30 23:30 UTC
    fixed_utc = datetime(2026, 12, 16, 0, 0, tzinfo=timezone.utc)
    expected_utc = datetime(2026, 12, 30, 23, 30, tzinfo=timezone.utc)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sch, "datetime", _FrozenDatetime(fixed_utc))
        result = next_central_bank_run_utc()
    assert result == expected_utc


# ── 环境变量开关 ──────────────────────────────────────────


def test_cb_auto_refresh_enabled_by_default(monkeypatch) -> None:
    """默认启用（环境变量未设置）。"""
    monkeypatch.delenv("CENTRAL_BANK_AUTO_REFRESH", raising=False)
    assert _is_cb_auto_refresh_enabled() is True


@pytest.mark.parametrize("val", ["0", "false", "no", "off", ""])
def test_cb_auto_refresh_disabled_by_env(monkeypatch, val: str) -> None:
    """禁用值：0/false/no/off/空。"""
    monkeypatch.setenv("CENTRAL_BANK_AUTO_REFRESH", val)
    assert _is_cb_auto_refresh_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "yes", "on", "TRUE", "  yes  "])
def test_cb_auto_refresh_enabled_by_env_truthy(monkeypatch, val: str) -> None:
    """启用值：1/true/yes/on/大小写不敏感/去前后空格。"""
    monkeypatch.setenv("CENTRAL_BANK_AUTO_REFRESH", val)
    assert _is_cb_auto_refresh_enabled() is True


# ── _refresh_central_bank 失败容错 ───────────────────────────


async def test_refresh_central_bank_handles_exception(monkeypatch) -> None:
    """run_import 抛异常时，_refresh_central_bank 不抛，仅日志告警，返回 0。"""
    async def fake_run_import(include_manual: bool = True) -> int:
        raise RuntimeError("网络挂了")

    monkeypatch.setattr(
        "app.scripts.import_central_bank.run_import",
        fake_run_import,
    )

    # 不应抛异常
    n = await sch._refresh_central_bank()
    assert n == 0


async def test_refresh_central_bank_returns_count(monkeypatch) -> None:
    """run_import 成功时返回 upserted 行数。"""
    async def fake_run_import(include_manual: bool = True) -> int:
        return 148

    monkeypatch.setattr(
        "app.scripts.import_central_bank.run_import",
        fake_run_import,
    )
    n = await sch._refresh_central_bank()
    assert n == 148


# ── monthly_central_bank_loop 关闭分支 ──────────────────────────


async def test_monthly_loop_disabled_returns_immediately(monkeypatch, caplog) -> None:
    """环境变量关闭时，loop 直接 return，不启动 while。"""
    monkeypatch.setenv("CENTRAL_BANK_AUTO_REFRESH", "0")
    # patch asyncio.sleep to detect 调用
    sleep_called = []
    async def fake_sleep(secs):
        sleep_called.append(secs)
    monkeypatch.setattr(sch.asyncio, "sleep", fake_sleep)

    await sch.monthly_central_bank_loop()
    assert sleep_called == []  # 没有任何 sleep 调用 → 没进入 while


# ── 工具类 ──────────────────────────────────────────────


class _FrozenDatetime:
    """替换 datetime.now() 用：返回固定 UTC 时间，其他方法透传。"""

    def __init__(self, frozen_utc: datetime) -> None:
        self._frozen = frozen_utc
        # 保留原 datetime 类（用于 astimezone 等）
        self._real = datetime

    def now(self, tz=None):
        if tz is None:
            return self._frozen.replace(tzinfo=None)
        return self._frozen.astimezone(tz)

    def __getattr__(self, name):
        return getattr(self._real, name)