"""V0.72.0 P3-b：AlertDispatcher 档位穿越 / 波动检测 + 静默时段 + 去重。

mock Notifier，无真实网络推送。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

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