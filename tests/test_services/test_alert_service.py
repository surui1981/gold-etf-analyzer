"""V0.72.0 P3-b：AlertDispatcher 档位穿越 / 波动检测 + 静默时段 + 去重。

mock Notifier，无真实网络推送。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.alert import AlertRuleOut, NotifyChannel, QuietHours
from app.schemas.market import TrendIndexLevel
from app.services.alert import AlertDispatcher, _SnapshotInput

# ───────────────────── Helper ─────────────────────


class _RecordingNotifier:
    """测试用：记录每次 send 调用，可控制成功/失败。"""

    def __init__(self, success: bool = True, channel: str = "email") -> None:
        self._success = success
        self._channel = channel
        self.sent: list[tuple[str, str]] = []

    async def send(self, *, subject: str, body: str, trace_id: str | None = None) -> bool:
        self.sent.append((subject, body))
        return self._success

    @property
    def channel(self) -> str:
        return self._channel


def _mock_repo(rules: AlertRuleOut) -> Any:
    """Mock SettingRepository，返回固定 rules。"""
    repo = MagicMock()
    repo.get = AsyncMock(return_value=rules.model_dump_json())
    repo.set = AsyncMock(return_value=None)
    return repo


def _quiet(h: str = "12:00", m: str = "12:01") -> QuietHours:
    """默认静默窗口：12:00-12:01（1 分钟窗；测试运行时段通常不在此区间）。

    显式测试静默时段的用例会传 ``QuietHours(start="00:00", end="23:59")`` 这种
    永远命中的窗口。
    """
    return QuietHours(start=h, end=m)


def _rules(
    *,
    level_crossing: bool = True,
    volatility: bool = True,
    vol_pct: float = 3.0,
    channels: list[NotifyChannel] | None = None,
    quiet: QuietHours | None = None,
) -> AlertRuleOut:
    return AlertRuleOut(
        level_crossing_enabled=level_crossing,
        volatility_enabled=volatility,
        volatility_pct=vol_pct,
        quiet_hours=quiet or _quiet(),
        channels=channels or ["email"],
        updated_at=datetime.now(),
    )


# ───────────────────── 档位穿越测试 ─────────────────────


async def test_level_crossing_bullish_to_bearish_triggers() -> None:
    """BULLISH → BEARISH 主轴翻转触发档位穿越告警。"""
    notifier = _RecordingNotifier(success=True, channel="email")
    dispatcher = AlertDispatcher()

    repo = _mock_repo(_rules(vol_pct=10.0))  # 关掉 volatility，只测 level_crossing
    prev = _SnapshotInput(date(2026, 9, 20), trend_score=80.0, change_1d_pct=1.0,
                          trend_level=TrendIndexLevel.STRONG_UP)
    curr = _SnapshotInput(date(2026, 9, 21), trend_score=20.0, change_1d_pct=-5.0,
                          trend_level=TrendIndexLevel.STRONG_DOWN)

    triggered = await dispatcher.evaluate_and_dispatch(
        prev=prev, curr=curr, repo=repo, notifiers=[notifier],
    )
    assert "level_crossing" in triggered
    assert len(notifier.sent) == 1
    subject, _body = notifier.sent[0]
    assert "档位变化" in subject
    assert "弱势下降" in subject


async def test_level_crossing_bullish_to_bullish_no_trigger() -> None:
    """BULLISH → BULLISH（即使具体档位变化）不触发。"""
    notifier = _RecordingNotifier()
    dispatcher = AlertDispatcher()

    repo = _mock_repo(_rules())
    prev = _SnapshotInput(date(2026, 9, 20), 80.0, 1.0, TrendIndexLevel.STRONG_UP)
    curr = _SnapshotInput(date(2026, 9, 21), 60.0, 0.5, TrendIndexLevel.UP)

    triggered = await dispatcher.evaluate_and_dispatch(
        prev=prev, curr=curr, repo=repo, notifiers=[notifier],
    )
    assert "level_crossing" not in triggered
    assert notifier.sent == []


async def test_level_crossing_through_sideways_no_trigger() -> None:
    """BULLISH → SIDEWAYS 不触发（中间态抖动忽略）。"""
    notifier = _RecordingNotifier()
    dispatcher = AlertDispatcher()

    repo = _mock_repo(_rules())
    prev = _SnapshotInput(date(2026, 9, 20), 80.0, 1.0, TrendIndexLevel.STRONG_UP)
    curr = _SnapshotInput(date(2026, 9, 21), 50.0, -2.0, TrendIndexLevel.SIDEWAYS)

    triggered = await dispatcher.evaluate_and_dispatch(
        prev=prev, curr=curr, repo=repo, notifiers=[notifier],
    )
    assert "level_crossing" not in triggered
    assert notifier.sent == []


async def test_level_crossing_disabled_no_trigger() -> None:
    """rules.level_crossing_enabled=False 时不触发档位穿越。"""
    notifier = _RecordingNotifier()
    dispatcher = AlertDispatcher()

    repo = _mock_repo(_rules(level_crossing=False, vol_pct=10.0))  # 两类都关
    prev = _SnapshotInput(date(2026, 9, 20), 80.0, 1.0, TrendIndexLevel.STRONG_UP)
    curr = _SnapshotInput(date(2026, 9, 21), 20.0, -5.0, TrendIndexLevel.STRONG_DOWN)

    triggered = await dispatcher.evaluate_and_dispatch(
        prev=prev, curr=curr, repo=repo, notifiers=[notifier],
    )
    assert "level_crossing" not in triggered
    assert notifier.sent == []


# ───────────────────── 单日波动测试 ─────────────────────


async def test_volatility_above_threshold_triggers() -> None:
    """单日波动 ≥3% 触发。"""
    notifier = _RecordingNotifier()
    dispatcher = AlertDispatcher()

    repo = _mock_repo(_rules(vol_pct=3.0))
    prev = _SnapshotInput(date(2026, 9, 20), 50.0, 0.5, TrendIndexLevel.SIDEWAYS)
    curr = _SnapshotInput(date(2026, 9, 21), 48.0, -3.5, TrendIndexLevel.SIDEWAYS)  # 跌 3.5%

    triggered = await dispatcher.evaluate_and_dispatch(
        prev=prev, curr=curr, repo=repo, notifiers=[notifier],
    )
    assert "volatility" in triggered
    subject, _body = notifier.sent[0]
    assert "下跌" in subject and "3.50" in subject


async def test_volatility_below_threshold_no_trigger() -> None:
    """单日波动 < 阈值不触发。"""
    notifier = _RecordingNotifier()
    dispatcher = AlertDispatcher()

    repo = _mock_repo(_rules(vol_pct=3.0))
    prev = _SnapshotInput(date(2026, 9, 20), 50.0, 0.5, TrendIndexLevel.SIDEWAYS)
    curr = _SnapshotInput(date(2026, 9, 21), 49.5, 2.5, TrendIndexLevel.SIDEWAYS)

    triggered = await dispatcher.evaluate_and_dispatch(
        prev=prev, curr=curr, repo=repo, notifiers=[notifier],
    )
    assert "volatility" not in triggered
    assert notifier.sent == []


async def test_volatility_upward_triggers() -> None:
    """单日上涨 ≥ 阈值也触发。"""
    notifier = _RecordingNotifier()
    dispatcher = AlertDispatcher()

    repo = _mock_repo(_rules(vol_pct=2.0))
    prev = _SnapshotInput(date(2026, 9, 20), 50.0, 0.0, TrendIndexLevel.SIDEWAYS)
    curr = _SnapshotInput(date(2026, 9, 21), 53.0, 2.5, TrendIndexLevel.UP)

    triggered = await dispatcher.evaluate_and_dispatch(
        prev=prev, curr=curr, repo=repo, notifiers=[notifier],
    )
    assert "volatility" in triggered
    assert "上涨" in notifier.sent[0][0]


# ───────────────────── 静默时段测试 ─────────────────────


async def test_quiet_hours_queues_not_sends() -> None:
    """静默时段内触发告警：入队但不发送。"""
    notifier = _RecordingNotifier()
    dispatcher = AlertDispatcher()

    # 静默时段 00:00-23:59（永远在静默内）
    repo = _mock_repo(_rules(quiet=QuietHours(start="00:00", end="23:59"), vol_pct=10.0))

    prev = _SnapshotInput(date(2026, 9, 20), 80.0, 1.0, TrendIndexLevel.STRONG_UP)
    curr = _SnapshotInput(date(2026, 9, 21), 20.0, -5.0, TrendIndexLevel.STRONG_DOWN)

    triggered = await dispatcher.evaluate_and_dispatch(
        prev=prev, curr=curr, repo=repo, notifiers=[notifier],
    )
    assert "level_crossing" in triggered
    assert notifier.sent == []  # 未发送
    assert len(dispatcher._quiet_queue) == 1


async def test_quiet_queue_flush_after_window() -> None:
    """静默队列醒后（flush_quiet_queue）一次性汇总推送。"""
    notifier = _RecordingNotifier()
    dispatcher = AlertDispatcher()

    dispatcher._quiet_queue.append(("level_crossing", "档位变化", "body1"))
    dispatcher._quiet_queue.append(("volatility", "波动", "body2"))

    repo = _mock_repo(_rules(channels=["email"]))
    n = await dispatcher.flush_quiet_queue(repo=repo, notifiers=[notifier])
    assert n == 2
    assert len(notifier.sent) == 1  # 汇总成一条
    assert "汇总" in notifier.sent[0][0]
    assert dispatcher._quiet_queue == []  # 清空


# ───────────────────── 去重测试 ─────────────────────


async def test_same_day_duplicate_dedup() -> None:
    """同一日内重复触发：第二次 evaluate_and_dispatch 不重复发送。"""
    notifier = _RecordingNotifier()
    dispatcher = AlertDispatcher()

    repo = _mock_repo(_rules(vol_pct=10.0))  # 关掉 volatility，只测 level_crossing 去重
    prev = _SnapshotInput(date(2026, 9, 20), 80.0, 1.0, TrendIndexLevel.STRONG_UP)
    curr = _SnapshotInput(date(2026, 9, 21), 20.0, -5.0, TrendIndexLevel.STRONG_DOWN)

    # 第一次触发
    triggered1 = await dispatcher.evaluate_and_dispatch(
        prev=prev, curr=curr, repo=repo, notifiers=[notifier],
    )
    # 第二次同一天（prev/curr 完全相同），不应重复
    triggered2 = await dispatcher.evaluate_and_dispatch(
        prev=prev, curr=curr, repo=repo, notifiers=[notifier],
    )
    assert "level_crossing" in triggered1
    assert "level_crossing" not in triggered2
    assert len(notifier.sent) == 1  # 只发一次


# ───────────────────── 静默时段边界测试 ─────────────────────


def test_is_quiet_overnight_window() -> None:
    """跨夜静默时段（22:00-07:00）：凌晨 03:00 在静默内。"""
    q = QuietHours(start="22:00", end="07:00")
    assert AlertDispatcher._is_quiet(q, datetime(2026, 9, 21, 3, 0)) is True
    assert AlertDispatcher._is_quiet(q, datetime(2026, 9, 21, 22, 0)) is True
    assert AlertDispatcher._is_quiet(q, datetime(2026, 9, 21, 23, 59)) is True
    assert AlertDispatcher._is_quiet(q, datetime(2026, 9, 21, 7, 0)) is False  # 边界
    assert AlertDispatcher._is_quiet(q, datetime(2026, 9, 21, 12, 0)) is False


def test_is_quiet_daytime_window() -> None:
    """日间静默时段（12:00-14:00）：中午 13:00 在静默内。"""
    q = QuietHours(start="12:00", end="14:00")
    assert AlertDispatcher._is_quiet(q, datetime(2026, 9, 21, 13, 0)) is True
    assert AlertDispatcher._is_quiet(q, datetime(2026, 9, 21, 11, 59)) is False
    assert AlertDispatcher._is_quiet(q, datetime(2026, 9, 21, 14, 0)) is False  # 边界


# ───────────────────── 渠道多路并行推送 ─────────────────────


async def test_fan_out_multiple_channels() -> None:
    """channels=['email', 'wechat']：两个 notifier 并行调用。"""
    notifier_email = _RecordingNotifier(channel="email")
    notifier_wechat = _RecordingNotifier(channel="wechat")
    dispatcher = AlertDispatcher()

    repo = _mock_repo(_rules(channels=["email", "wechat"], vol_pct=10.0))  # 关 volatility 只测 fan-out
    prev = _SnapshotInput(date(2026, 9, 20), 80.0, 1.0, TrendIndexLevel.STRONG_UP)
    curr = _SnapshotInput(date(2026, 9, 21), 20.0, -5.0, TrendIndexLevel.STRONG_DOWN)

    triggered = await dispatcher.evaluate_and_dispatch(
        prev=prev, curr=curr, repo=repo, notifiers=[notifier_email, notifier_wechat],
    )
    assert "level_crossing" in triggered
    assert len(notifier_email.sent) == 1
    assert len(notifier_wechat.sent) == 1


# ───────────────────── V0.74.0 N+18 · discriminated union ──────────


from app.schemas.alert import (  # noqa: E402  -- late import for V0.74.0 N+18 tests
    CrossingRule,
    TPlusNRule,
    VolatilityRule,
    WindowRule,
    WindowSpec,
)


@pytest.fixture(autouse=True)
def _reset_alert_rules_cache():
    """V0.74.0 N+18 · 清空 settings._ALERT_RULES_CACHE,避免上一个测试的缓存干扰本测试。"""
    from app.services.settings import _ALERT_RULES_CACHE  # noqa: PLC0415
    _ALERT_RULES_CACHE["config"] = None
    _ALERT_RULES_CACHE["ts"] = 0.0
    yield
    _ALERT_RULES_CACHE["config"] = None
    _ALERT_RULES_CACHE["ts"] = 0.0


def _rules_v2(rules: list, channels: list[NotifyChannel] | None = None, quiet: QuietHours | None = None) -> AlertRuleOut:
    """V0.74.0 N+18 helper：直接构造 rules 列表。"""
    return AlertRuleOut(
        rules=rules,
        quiet_hours=quiet,
        channels=channels or ["email"],
        updated_at=datetime.now(),
    )


async def test_n18_crossing_axis_4_strong_to_strong_triggers() -> None:
    """V0.74.0 N+18 · axis_levels=4 细粒度跨档：STRONG_UP↔STRONG_DOWN 也算。"""
    notifier = _RecordingNotifier()
    dispatcher = AlertDispatcher()
    rule = CrossingRule(kind="crossing", axis_levels=4, enabled=True)
    repo = _mock_repo(_rules_v2([rule]))
    prev = _SnapshotInput(date(2026, 9, 20), 95.0, 1.0, TrendIndexLevel.STRONG_UP)
    curr = _SnapshotInput(date(2026, 9, 21), 15.0, -5.0, TrendIndexLevel.STRONG_DOWN)
    triggered = await dispatcher.evaluate_and_dispatch(
        prev=prev, curr=curr, repo=repo, notifiers=[notifier],
    )
    assert "level_crossing" in triggered
    assert len(notifier.sent) == 1


async def test_n18_crossing_axis_4_same_level_no_trigger() -> None:
    """V0.74.0 N+18 · axis_levels=4：相同档位不触发。"""
    notifier = _RecordingNotifier()
    dispatcher = AlertDispatcher()
    rule = CrossingRule(kind="crossing", axis_levels=4, enabled=True)
    repo = _mock_repo(_rules_v2([rule]))
    prev = _SnapshotInput(date(2026, 9, 20), 80.0, 1.0, TrendIndexLevel.UP)
    curr = _SnapshotInput(date(2026, 9, 21), 80.0, 1.0, TrendIndexLevel.UP)
    triggered = await dispatcher.evaluate_and_dispatch(
        prev=prev, curr=curr, repo=repo, notifiers=[notifier],
    )
    assert "level_crossing" not in triggered


async def test_n18_crossing_disabled_no_trigger() -> None:
    """V0.74.0 N+18 · crossing rule.enabled=False 时不触发。"""
    notifier = _RecordingNotifier()
    dispatcher = AlertDispatcher()
    rule = CrossingRule(kind="crossing", axis_levels=2, enabled=False)
    repo = _mock_repo(_rules_v2([rule]))
    prev = _SnapshotInput(date(2026, 9, 20), 80.0, 1.0, TrendIndexLevel.STRONG_UP)
    curr = _SnapshotInput(date(2026, 9, 21), 20.0, -5.0, TrendIndexLevel.STRONG_DOWN)
    triggered = await dispatcher.evaluate_and_dispatch(
        prev=prev, curr=curr, repo=repo, notifiers=[notifier],
    )
    assert "level_crossing" not in triggered
    assert notifier.sent == []


async def test_n18_volatility_disabled_no_trigger() -> None:
    """V0.74.0 N+18 · volatility rule.enabled=False 时不触发。"""
    notifier = _RecordingNotifier()
    dispatcher = AlertDispatcher()
    rule = VolatilityRule(kind="volatility", threshold_pct=1.0, enabled=False)
    repo = _mock_repo(_rules_v2([rule]))
    prev = _SnapshotInput(date(2026, 9, 20), 80.0, 1.0, TrendIndexLevel.UP)
    curr = _SnapshotInput(date(2026, 9, 21), 80.0, 5.0, TrendIndexLevel.UP)  # 大波动
    triggered = await dispatcher.evaluate_and_dispatch(
        prev=prev, curr=curr, repo=repo, notifiers=[notifier],
    )
    assert "volatility" not in triggered


async def test_n18_volatility_threshold_zero_always_trigger() -> None:
    """V0.74.0 N+18 · threshold_pct=0.1（小阈值）：小幅波动也触发。"""
    notifier = _RecordingNotifier()
    dispatcher = AlertDispatcher()
    rule = VolatilityRule(kind="volatility", threshold_pct=0.1, enabled=True)
    repo = _mock_repo(_rules_v2([rule]))
    prev = _SnapshotInput(date(2026, 9, 20), 80.0, 1.0, TrendIndexLevel.UP)
    curr = _SnapshotInput(date(2026, 9, 21), 80.0, 0.5, TrendIndexLevel.UP)
    triggered = await dispatcher.evaluate_and_dispatch(
        prev=prev, curr=curr, repo=repo, notifiers=[notifier],
    )
    assert "volatility" in triggered


class _FakeSnap:
    """V0.74.0 N+18 · mock DailySnapshot for T+N lookup."""

    def __init__(self, snapshot_date, index_level, close):
        self.snapshot_date = snapshot_date
        self.index_level = index_level
        self.close = close


class _FakeSnapRepo:
    """V0.74.0 N+18 · mock SnapshotRepository.get_latest_before()."""

    def __init__(self, by_date: dict):
        self._by = by_date

    async def get_latest_before(self, before):
        # 与 production SnapshotRepository 一致:严格小于 before
        candidates = sorted(
            [(d, s) for d, s in self._by.items() if d < before],
            key=lambda x: x[0],
            reverse=True,
        )
        return candidates[0][1] if candidates else None


async def test_n18_t_plus_n_buy_hit() -> None:
    """V0.74.0 N+18 · T+3 买入命中：3 天前信号为 UP，今日涨 2%。"""
    notifier = _RecordingNotifier()
    dispatcher = AlertDispatcher()
    rule = TPlusNRule(kind="t_plus_n", t_plus_n_days=3, t_plus_n_pct=1.5, enabled=True)
    repo = _mock_repo(_rules_v2([rule]))
    # curr=9-21, target_date=9-18, prod repo 严格小于 target,所以 past=9-17
    past = _FakeSnap(date(2026, 9, 17), "up", close=100.0)
    snap_repo = _FakeSnapRepo({past.snapshot_date: past})
    prev = _SnapshotInput(date(2026, 9, 20), 80.0, 1.0, TrendIndexLevel.UP)
    curr = _SnapshotInput(date(2026, 9, 21), 82.0, 1.0, TrendIndexLevel.UP, close_price=102.0)
    triggered = await dispatcher.evaluate_and_dispatch(
        prev=prev, curr=curr, repo=repo, snapshots_repo=snap_repo, notifiers=[notifier],
    )
    assert any(k.startswith("t_plus_n") for k in triggered)
    assert len(notifier.sent) == 1
    assert "T+3" in notifier.sent[0][0]
    assert "买入" in notifier.sent[0][0]


async def test_n18_t_plus_n_buy_miss() -> None:
    """V0.74.0 N+18 · T+3 买入未达阈值：不触发。"""
    notifier = _RecordingNotifier()
    dispatcher = AlertDispatcher()
    rule = TPlusNRule(kind="t_plus_n", t_plus_n_days=3, t_plus_n_pct=2.0, enabled=True)
    repo = _mock_repo(_rules_v2([rule]))
    past = _FakeSnap(date(2026, 9, 17), "up", close=100.0)
    snap_repo = _FakeSnapRepo({past.snapshot_date: past})
    prev = _SnapshotInput(date(2026, 9, 20), 80.0, 1.0, TrendIndexLevel.UP)
    curr = _SnapshotInput(date(2026, 9, 21), 80.5, 0.5, TrendIndexLevel.UP, close_price=100.5)
    triggered = await dispatcher.evaluate_and_dispatch(
        prev=prev, curr=curr, repo=repo, snapshots_repo=snap_repo, notifiers=[notifier],
    )
    assert not any(k.startswith("t_plus_n") for k in triggered)


async def test_n18_t_plus_n_neutral_past_no_trigger() -> None:
    """V0.74.0 N+18 · 3 天前信号为 SIDEWAYS：不触发（无方向预测）。"""
    notifier = _RecordingNotifier()
    dispatcher = AlertDispatcher()
    rule = TPlusNRule(kind="t_plus_n", t_plus_n_days=3, t_plus_n_pct=1.0, enabled=True)
    repo = _mock_repo(_rules_v2([rule]))
    past = _FakeSnap(date(2026, 9, 17), "sideways", close=100.0)
    snap_repo = _FakeSnapRepo({past.snapshot_date: past})
    prev = _SnapshotInput(date(2026, 9, 20), 80.0, 1.0, TrendIndexLevel.SIDEWAYS)
    curr = _SnapshotInput(date(2026, 9, 21), 80.0, 5.0, TrendIndexLevel.UP, close_price=110.0)
    triggered = await dispatcher.evaluate_and_dispatch(
        prev=prev, curr=curr, repo=repo, snapshots_repo=snap_repo, notifiers=[notifier],
    )
    assert not any(k.startswith("t_plus_n") for k in triggered)


async def test_n18_t_plus_n_no_snapshots_repo_silent() -> None:
    """V0.74.0 N+18 · 未传 snapshots_repo：T+N 静默 no-op,不抛异常。"""
    notifier = _RecordingNotifier()
    dispatcher = AlertDispatcher()
    rule = TPlusNRule(kind="t_plus_n", t_plus_n_days=3, t_plus_n_pct=1.5, enabled=True)
    repo = _mock_repo(_rules_v2([rule]))
    prev = _SnapshotInput(date(2026, 9, 20), 80.0, 1.0, TrendIndexLevel.UP)
    curr = _SnapshotInput(date(2026, 9, 21), 82.0, 1.0, TrendIndexLevel.UP, close_price=102.0)
    triggered = await dispatcher.evaluate_and_dispatch(
        prev=prev, curr=curr, repo=repo, snapshots_repo=None, notifiers=[notifier],
    )
    assert not any(k.startswith("t_plus_n") for k in triggered)


async def test_n18_legacy_migration_compat() -> None:
    """V0.74.0 N+18 · 旧 schema(扁平 boolean) → 自动迁移为 rules 列表。"""
    from app.schemas.alert import AlertRuleIn

    # 旧 PUT 体
    payload = {
        "level_crossing_enabled": True,
        "volatility_enabled": True,
        "volatility_pct": 2.5,
        "quiet_hours": {"start": "22:00", "end": "07:00"},
        "channels": ["email"],
    }
    parsed = AlertRuleIn.model_validate(payload)
    kinds = sorted(r.kind for r in parsed.rules)
    assert kinds == ["crossing", "volatility", "window"], f"迁移后 kinds 不对: {kinds}"
    # 验证 volatility 阈值正确迁移
    vol = next(r for r in parsed.rules if r.kind == "volatility")
    assert vol.threshold_pct == 2.5


async def test_n18_window_rule_quiet_in_window_queues() -> None:
    """V0.74.0 N+18 · window rule(mode=quiet) 当前在窗口内 → volatility 触发入队。"""
    notifier = _RecordingNotifier()
    dispatcher = AlertDispatcher()
    vol = VolatilityRule(kind="volatility", threshold_pct=1.0, enabled=True)
    win = WindowRule(kind="window", window=WindowSpec(mode="quiet", start="00:00", end="23:59"), enabled=True)
    repo = _mock_repo(_rules_v2([vol, win]))
    prev = _SnapshotInput(date(2026, 9, 20), 80.0, 1.0, TrendIndexLevel.UP)
    curr = _SnapshotInput(date(2026, 9, 21), 80.0, 5.0, TrendIndexLevel.UP)
    triggered = await dispatcher.evaluate_and_dispatch(
        prev=prev, curr=curr, repo=repo, notifiers=[notifier],
    )
    # 静默内:入队不推送
    assert "volatility" in triggered
    assert len(notifier.sent) == 0
    assert len(dispatcher._quiet_queue) == 1


async def test_n18_window_rule_active_outside_window_queues() -> None:
    """V0.74.0 N+18 · window rule(mode=active) 当前在窗口外 → volatility 触发入队。"""
    notifier = _RecordingNotifier()
    dispatcher = AlertDispatcher()
    vol = VolatilityRule(kind="volatility", threshold_pct=1.0, enabled=True)
    # active mode,start=00:00 end=00:01 → 几乎所有时刻都在窗口外
    win = WindowRule(kind="window", window=WindowSpec(mode="active", start="00:00", end="00:01"), enabled=True)
    repo = _mock_repo(_rules_v2([vol, win]))
    prev = _SnapshotInput(date(2026, 9, 20), 80.0, 1.0, TrendIndexLevel.UP)
    curr = _SnapshotInput(date(2026, 9, 21), 80.0, 5.0, TrendIndexLevel.UP)
    triggered = await dispatcher.evaluate_and_dispatch(
        prev=prev, curr=curr, repo=repo, notifiers=[notifier],
    )
    # 窗口外:入队
    assert "volatility" in triggered
    assert len(notifier.sent) == 0
    assert len(dispatcher._quiet_queue) == 1


async def test_n18_multiple_rules_same_day_dedup_isolated() -> None:
    """V0.74.0 N+18 · 多条 enabled 规则同日命中：各自去重互不干扰。"""
    notifier = _RecordingNotifier()
    dispatcher = AlertDispatcher()
    # vol@1.0 + vol@5.0:两条独立 volatility 规则
    rules = [
        VolatilityRule(kind="volatility", threshold_pct=1.0, enabled=True),
        VolatilityRule(kind="volatility", threshold_pct=5.0, enabled=True),
    ]
    repo = _mock_repo(_rules_v2(rules))
    prev = _SnapshotInput(date(2026, 9, 20), 80.0, 1.0, TrendIndexLevel.UP)
    curr = _SnapshotInput(date(2026, 9, 21), 80.0, 3.0, TrendIndexLevel.UP)
    triggered = await dispatcher.evaluate_and_dispatch(
        prev=prev, curr=curr, repo=repo, notifiers=[notifier],
    )
    # 3% >= 1.0 触发；3% < 5.0 不触发
    assert "volatility" in triggered
    # 因为只有一条规则触发,只推 1 次
    assert len(notifier.sent) == 1