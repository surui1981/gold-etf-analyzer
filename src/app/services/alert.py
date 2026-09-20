"""告警分发（V0.72.0）：档位穿越 / 单日波动检测 + 多渠道推送调度。

设计要点：
- 档位穿越：仅 BULLISH↔BEARISH 主轴翻转触发（避免 SIDEWAYS 中间态抖动）
- 波动告警：日 1 次（避免日内反复）
- 静默时段：BJT 22:00-07:00 默认（用户可配）；此时告警入队但不推送
- 失败重试：退避 5s / 30s / 5min 三次（由 notify.send_with_retry 处理）
- 去重：每日档位翻转标记当日已发（避免日内 4 次 warm 重复触发）
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Any

from app.schemas.alert import AlertRuleOut, QuietHours
from app.schemas.market import TrendIndexLevel
from app.services.notify import (
    Notifier,
    NotifierFactory,
    send_with_retry,
)
from app.services.settings import (
    get_alert_rules,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class _SnapshotInput:
    """评估告警所需的最小输入（解耦 DailySnapshot / analyze 输出）。"""

    snapshot_date: date
    trend_score: float
    change_1d_pct: float
    trend_level: TrendIndexLevel


class AlertDispatcher:
    """告警检测 + 分发。stateful（按日期去重 + 静默队列）。"""

    def __init__(self) -> None:
        # V0.72.0：按日期去重，防止日内多次 warm 重复推送
        self._sent_today: dict[str, str] = {}  # date_key -> "level_crossing"/"volatility"
        # V0.72.0：静默时段累积的告警（醒后 09:30 一次性汇总推送）
        self._quiet_queue: list[tuple[str, str, str | None]] = []

    @staticmethod
    def _date_key(d: date) -> str:
        return d.isoformat()

    @staticmethod
    def _bjt_now() -> datetime:
        """BJT 当前时间。"""
        return datetime.now(timezone.utc).astimezone(_BJT_TZ)

    @staticmethod
    def _is_quiet(quiet: QuietHours, now: datetime) -> bool:
        """判断当前 BJT 时间是否在静默时段内。"""
        start = time.fromisoformat(quiet.start)
        end = time.fromisoformat(quiet.end)
        cur = now.time()
        # 跨午夜（如 22:00-07:00）：start > end
        if start > end:
            return cur >= start or cur < end
        return start <= cur < end

    async def _load_rules(self, repo: Any) -> AlertRuleOut:
        return await get_alert_rules(repo)

    async def evaluate_and_dispatch(
        self,
        *,
        prev: _SnapshotInput | None,
        curr: _SnapshotInput,
        repo: Any,
        notifiers: list[Notifier] | None = None,
        trace_id: str | None = None,
    ) -> list[str]:
        """评估档位穿越 / 波动，触发推送。返回触发的告警 key 列表（用于测试断言）。

        ``notifiers`` 显式注入（测试用），不传则从 NotifierFactory.create_all(rules.channels) 构建。
        """
        rules = await self._load_rules(repo)
        triggered: list[str] = []
        subjects: list[tuple[str, str, str]] = []  # (key, subject, body)

        # ── 1. 档位穿越检测 ──────────────────────────────────
        if rules.level_crossing_enabled and prev is not None:
            key = self._date_key(curr.snapshot_date)
            if (
                self._sent_today.get(key) != "level_crossing"
                and self._is_main_axis_crossing(prev.trend_level, curr.trend_level)
            ):
                subject = f"黄金 ETF 指数档位变化 → {self._level_label_zh(curr.trend_level)}"
                body = (
                    f"日期：{curr.snapshot_date}\n"
                    f"趋势指数：{curr.trend_score:.1f}\n"
                    f"档位：{self._level_label_zh(prev.trend_level)} → "
                    f"{self._level_label_zh(curr.trend_level)}\n"
                    f"单日波动：{curr.change_1d_pct:+.2f}%\n"
                )
                subjects.append(("level_crossing", subject, body))
                self._sent_today[key] = "level_crossing"
                triggered.append("level_crossing")

        # ── 2. 单日波动检测 ──────────────────────────────────
        if rules.volatility_enabled and abs(curr.change_1d_pct) >= rules.volatility_pct:
            key = self._date_key(curr.snapshot_date)
            if self._sent_today.get(key) != "volatility":
                direction = "上涨" if curr.change_1d_pct > 0 else "下跌"
                subject = f"黄金 ETF 单日{direction} {abs(curr.change_1d_pct):.2f}%"
                body = (
                    f"日期：{curr.snapshot_date}\n"
                    f"单日波动：{curr.change_1d_pct:+.2f}%\n"
                    f"阈值：{rules.volatility_pct:.1f}%\n"
                    f"趋势指数：{curr.trend_score:.1f}\n"
                )
                subjects.append(("volatility", subject, body))
                self._sent_today[key] = "volatility"
                triggered.append("volatility")

        if not subjects:
            return triggered

        # ── 3. 静默时段判定 ──────────────────────────────────
        now_bjt = self._bjt_now()
        quiet = rules.quiet_hours
        if self._is_quiet(quiet, now_bjt):
            for key, subj, body in subjects:
                self._quiet_queue.append((key, subj, body))
                logger.info(
                    "Alert queued (quiet hours): key=%s subject=%s",
                    key,
                    subj,
                )
            return triggered

        # ── 4. 推送：按渠道偏好顺序 ───────────────────────────
        notifiers = notifiers or NotifierFactory.create_all(rules.channels)
        if not notifiers:
            logger.warning(
                "Alert triggered but no notifier configured (channels=%s)",
                rules.channels,
            )
            return triggered

        for key, subj, body in subjects:
            await self._fan_out(notifiers, subject=subj, body=body, key=key, trace_id=trace_id)

        return triggered

    async def flush_quiet_queue(
        self, repo: Any, notifiers: list[Notifier] | None = None, trace_id: str | None = None,
) -> int:
        """醒后（如 09:30 BJT）调用：一次性推送静默队列累积的告警。返回推送条数。"""
        if not self._quiet_queue:
            return 0
        rules = await self._load_rules(repo)
        notifiers = notifiers or NotifierFactory.create_all(rules.channels)
        if not notifiers:
            logger.warning("Quiet queue flush: no notifier configured")
            return 0

        # 合并成一条汇总
        n = len(self._quiet_queue)
        subject = f"黄金 ETF · 静默时段告警汇总（{n} 条）"
        body = "\n\n".join(f"[{k}] {s}\n{b}" for k, s, b in self._quiet_queue)
        sent = await self._fan_out(notifiers, subject=subject, body=body, key="quiet_summary", trace_id=trace_id)
        if sent > 0:
            self._quiet_queue.clear()
        return n

    @staticmethod
    async def _fan_out(
        notifiers: list[Notifier],
        *,
        subject: str,
        body: str,
        key: str,
        trace_id: str | None = None,
    ) -> int:
        """对所有渠道并行推送（每渠道独立退避重试）。返回成功渠道数。"""
        results = await asyncio.gather(
            *(send_with_retry(n, subject=subject, body=body, trace_id=trace_id) for n in notifiers),
            return_exceptions=True,
        )
        ok = 0
        for n, r in zip(notifiers, results, strict=False):
            if r is True:
                logger.info("Alert dispatched: key=%s channel=%s", key, n.channel)
                ok += 1
            else:
                logger.warning(
                    "Alert dispatch failed: key=%s channel=%s result=%s",
                    key,
                    n.channel,
                    r if isinstance(r, Exception) else "False",
                )
        return ok

    @staticmethod
    def _is_main_axis_crossing(prev: TrendIndexLevel, curr: TrendIndexLevel) -> bool:
        """BULLISH↔BEARISH 主轴翻转检测（SIDEWAYS 抖动忽略）。"""
        prev_axis = _LEVEL_AXIS.get(prev, "neutral")
        curr_axis = _LEVEL_AXIS.get(curr, "neutral")
        if prev_axis == "neutral" or curr_axis == "neutral":
            return False
        return prev_axis != curr_axis

    @staticmethod
    def _level_label_zh(level: TrendIndexLevel) -> str:
        return {
            TrendIndexLevel.STRONG_UP: "强势上升",
            TrendIndexLevel.UP: "上升",
            TrendIndexLevel.SIDEWAYS: "震荡整理",
            TrendIndexLevel.DOWN: "下降",
            TrendIndexLevel.STRONG_DOWN: "弱势下降",
        }.get(level, str(level))

    def reset_for_testing(self) -> None:
        """测试隔离：清空去重状态与静默队列。"""
        self._sent_today.clear()
        self._quiet_queue.clear()


# V0.72.0：档位主轴映射（SIDEWAYS = neutral，不算翻转）
_LEVEL_AXIS: dict[TrendIndexLevel, str] = {
    TrendIndexLevel.STRONG_UP: "bullish",
    TrendIndexLevel.UP: "bullish",
    TrendIndexLevel.SIDEWAYS: "neutral",
    TrendIndexLevel.DOWN: "bearish",
    TrendIndexLevel.STRONG_DOWN: "bearish",
}


# V0.72.0：BJT 时区（Asia/Shanghai，UTC+8，固定偏移避免 tzdata 依赖）
class _FixedOffsetTZ(tzinfo):
    """固定偏移时区（BJT = UTC+8）。"""

    def __init__(self, offset_hours: int) -> None:
        self._offset = timedelta(hours=offset_hours)

    def utcoffset(self, dt: datetime | None) -> timedelta:
        return self._offset

    def dst(self, dt: datetime | None) -> timedelta:
        return timedelta(0)

    def tzname(self, dt: datetime | None) -> str:
        return "BJT"


_BJT_TZ = _FixedOffsetTZ(8)


__all__ = ["AlertDispatcher", "_SnapshotInput"]