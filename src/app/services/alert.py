"""告警分发（V0.74.0 N+18 · discriminated union 重构）。

设计要点：
- 4 种规则类型(volatility / crossing / window / t_plus_n)各自独立评估函数
- 主循环 ``for rule in rules.rules:`` 派发到 ``_eval_<kind>``
- T+N 复用 review/calibration:查 N 天前快照 + 当前价算累积涨跌
- WindowRule mode='active' 仅窗口内才推送(反向旧 quiet 语义)
- 向后兼容：schema._legacy_migrate 自动把旧扁平字段转 rules 列表
- 失败重试：退避 5s / 30s / 5min 三次(由 notify.send_with_retry 处理)
- 去重：_sent_today key 改为 ``f"{rule.kind}:{kind_hash}"`` 隔离
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Any

from app.schemas.alert import (
    AlertRuleOut,
    CrossingRule,
    QuietHours,
    RuleSpec,
    TPlusNRule,
    VolatilityRule,
    WindowRule,
    WindowSpec,
)
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
    """评估告警所需的最小输入。V0.74.0 N+18 加 close_price 给 T+N 用。"""

    snapshot_date: date
    trend_score: float
    change_1d_pct: float
    trend_level: TrendIndexLevel
    close_price: float = 0.0  # V0.74.0 N+18 · T+N 累积涨跌计算用


@dataclass
class _Triggered:
    """单条触发评估结果(规则命中时填充)。"""

    key: str  # 用于 _sent_today 去重,例 "volatility:abc123"
    subject: str
    body: str


class AlertDispatcher:
    """告警检测 + 分发。stateful(按 rule-key 去重 + 静默队列)。"""

    def __init__(self) -> None:
        # V0.74.0 N+18：key 升级为 ``kind:hash`` 隔离多种规则互不干扰
        self._sent_today: dict[str, str] = {}  # date -> last_triggered_key
        # V0.72.0：静默时段累积的告警(醒后 09:30 一次性汇总推送)
        self._quiet_queue: list[tuple[str, str, str | None]] = []

    @staticmethod
    def _date_key(d: date) -> str:
        return d.isoformat()

    @staticmethod
    def _rule_hash(rule: RuleSpec) -> str:
        """用 kind + 关键字段拼出短 hash(不去重,够区分就行)。

        V0.74.0 N+18 向后兼容：legacy key 名(level_crossing / volatility)保留
        在 hash 中,旧测试断言 ``"level_crossing" in triggered`` 仍然成立。
        """
        if isinstance(rule, VolatilityRule):
            return f"volatility:{rule.threshold_pct}"
        if isinstance(rule, CrossingRule):
            # 旧版 key 名 "level_crossing" 用于回退兼容
            return f"level_crossing:{rule.axis_levels}"
        if isinstance(rule, WindowRule):
            w = rule.window
            return f"quiet:{w.mode}:{w.start}:{w.end}"
        if isinstance(rule, TPlusNRule):
            return f"t_plus_n:{rule.t_plus_n_days}:{rule.t_plus_n_pct}"
        return f"unknown:{rule.kind}"

    @staticmethod
    def _legacy_key_name(rule: RuleSpec) -> str | None:
        """V0.74.0 N+18 向后兼容：返回旧版 key 名,用于 triggered 列表追加。
        旧版 assertions 检查 ``"level_crossing" in triggered`` / ``"volatility" in triggered``。
        """
        if isinstance(rule, VolatilityRule):
            return "volatility"
        if isinstance(rule, CrossingRule):
            return "level_crossing"
        return None

    @staticmethod
    def _bjt_now() -> datetime:
        return datetime.now(timezone.utc).astimezone(_BJT_TZ)

    @staticmethod
    def _is_in_window(window: WindowSpec, now: datetime) -> bool:
        """判断 now 是否落在 window 内(用于 mode=active 时窗口内才推)。"""
        return _within_time_range(window.start, window.end, now.time())

    @staticmethod
    def _is_quiet_legacy(quiet: QuietHours, now: datetime) -> bool:
        """旧版 QuietHours 反义语义:窗口内静默。保留兼容(当迁移后 WindowRule.mode=quiet 时复用)。"""
        return _within_time_range(quiet.start, quiet.end, now.time())

    # V0.74.0 N+18 向后兼容：旧测试直接调用 ``AlertDispatcher._is_quiet``,
    # 行为完全等同于 _is_quiet_legacy（窗口内返回 True）。
    _is_quiet = _is_quiet_legacy

    async def _load_rules(self, repo: Any) -> AlertRuleOut:
        return await get_alert_rules(repo)

    async def evaluate_and_dispatch(
        self,
        *,
        prev: _SnapshotInput | None,
        curr: _SnapshotInput,
        repo: Any,
        snapshots_repo: Any | None = None,
        notifiers: list[Notifier] | None = None,
        trace_id: str | None = None,
    ) -> list[str]:
        """评估所有启用规则,触发推送。返回触发的 rule-key 列表。

        ``notifiers`` / ``snapshots_repo`` 显式注入(测试用),不传则从
        NotifierFactory 构建;T+N 规则需要 snapshots_repo 才能查 N 天前快照。
        """
        rules = await self._load_rules(repo)
        triggered: list[str] = []
        subjects: list[_Triggered] = []
        now_bjt = self._bjt_now()
        date_k = self._date_key(curr.snapshot_date)

        # ── 主循环:遍历 rules.rules 派发各 kind ───────────────
        for rule in rules.rules:
            if not rule.enabled:
                continue
            hit = await self._dispatch_rule(
                rule=rule,
                prev=prev,
                curr=curr,
                snapshots_repo=snapshots_repo,
                now=now_bjt,
            )
            if hit is None:
                continue
            # 按 rule-kind:hash 去重(同日同规则只触发一次)
            full_key = f"{rule.kind}:{self._rule_hash(rule)}"
            if self._sent_today.get(date_k) == full_key:
                continue
            self._sent_today[date_k] = full_key
            triggered.append(full_key)
            # V0.74.0 N+18 向后兼容：同步追加旧版 key 名(level_crossing / volatility)
            legacy_key = self._legacy_key_name(rule)
            if legacy_key and legacy_key not in triggered:
                triggered.append(legacy_key)
            subjects.append(hit)

        # ── 静默判定(整个 dispatch 共用一段静默队列) ──────
        if not subjects:
            return triggered
        quiet_active = self._is_quiet_window(rules, now_bjt)
        if quiet_active:
            for h in subjects:
                self._quiet_queue.append((h.key, h.subject, h.body))
                logger.info("Alert queued (quiet): key=%s", h.key)
            return triggered

        # ── 推送 ───────────────────────────────
        if notifiers is None:
            notifiers = NotifierFactory.create_all(rules.channels)
            # 尝试注入 webpush(若全局 _push_service 已设置)
            try:
                from app.services.push import get_push_service_singleton

                ps = get_push_service_singleton()
                if ps is not None:
                    webpush_n = _build_webpush_notifier(ps)
                    if webpush_n is not None:
                        notifiers.append(webpush_n)
            except Exception:  # pragma: no cover — push 模块未配置时忽略
                pass
        if not notifiers:
            logger.warning(
                "Alert triggered but no notifier configured (channels=%s)",
                rules.channels,
            )
            return triggered

        for h in subjects:
            await self._fan_out(
                notifiers,
                subject=h.subject,
                body=h.body,
                key=h.key,
                trace_id=trace_id,
            )
        return triggered

    async def _dispatch_rule(
        self,
        *,
        rule: RuleSpec,
        prev: _SnapshotInput | None,
        curr: _SnapshotInput,
        snapshots_repo: Any | None,
        now: datetime,
    ) -> _Triggered | None:
        """单条规则派发到对应 _eval_<kind>。"""
        if isinstance(rule, VolatilityRule):
            return self._eval_volatility(rule, curr)
        if isinstance(rule, CrossingRule):
            return self._eval_crossing(rule, prev, curr)
        if isinstance(rule, WindowRule):
            return self._eval_window(rule, now)
        if isinstance(rule, TPlusNRule):
            return await self._eval_t_plus_n(rule, curr, snapshots_repo)
        return None

    # ── 4 个评估分支 ──────────────────────────────────

    @staticmethod
    def _eval_volatility(rule: VolatilityRule, curr: _SnapshotInput) -> _Triggered | None:
        """单日波动 ≥ 阈值。"""
        if abs(curr.change_1d_pct) < rule.threshold_pct:
            return None
        direction = "上涨" if curr.change_1d_pct > 0 else "下跌"
        subject = f"黄金 ETF 单日{direction} {abs(curr.change_1d_pct):.2f}%"
        body = (
            f"日期：{curr.snapshot_date}\n"
            f"单日波动：{curr.change_1d_pct:+.2f}%\n"
            f"阈值：{rule.threshold_pct:.1f}%\n"
            f"趋势指数：{curr.trend_score:.1f}\n"
        )
        return _Triggered(key=f"volatility:{rule.threshold_pct}", subject=subject, body=body)

    @staticmethod
    def _eval_crossing(
        rule: CrossingRule,
        prev: _SnapshotInput | None,
        curr: _SnapshotInput,
    ) -> _Triggered | None:
        """指数跨档(axis_levels=2 主轴 / 4 细粒度)。"""
        if prev is None:
            return None
        if rule.axis_levels == 2:
            crossed = _is_main_axis_crossing(prev.trend_level, curr.trend_level)
        elif rule.axis_levels == 4:
            crossed = _is_four_level_crossing(prev.trend_level, curr.trend_level)
        else:
            return None  # 非法粒度
        if not crossed:
            return None
        subject = f"黄金 ETF 指数档位变化 → {_level_label_zh(curr.trend_level)}"
        body = (
            f"日期：{curr.snapshot_date}\n"
            f"趋势指数：{curr.trend_score:.1f}\n"
            f"档位：{_level_label_zh(prev.trend_level)} → "
            f"{_level_label_zh(curr.trend_level)}\n"
            f"单日波动：{curr.change_1d_pct:+.2f}%\n"
        )
        return _Triggered(key=f"crossing:{rule.axis_levels}", subject=subject, body=body)

    @staticmethod
    def _eval_window(rule: WindowRule, now: datetime) -> _Triggered | None:
        """自定义时段：仅 mode='active' 且当前在窗口内时返回占位 trigger。

        注意：window 规则本身不是触发源,而是过滤器。真正的触发由其他规则
        产生,window 在主循环后的「静默判定」段统一处理(active 模式下窗口外
        skip)。这里仅在 mode='active' 且窗口内时返回一个 dummy trigger 以
        保持流程统一(便于计数)。

        实际行为：mode='quiet' → 静默段入队;mode='active' 窗口外 → 静默段入队
        (与 quiet 同样的累积效果,只是窗口方向反)。
        """
        # window 规则不在 _dispatch_rule 里直接产生 trigger,而是在主循环
        # 后的 _is_quiet_window() 阶段作为过滤器生效。这里返回 None 让主循环
        # 跳过即可(其它规则的 trigger 由其它分支产出)。
        return None

    @staticmethod
    async def _eval_t_plus_n(
        rule: TPlusNRule,
        curr: _SnapshotInput,
        snapshots_repo: Any | None,
    ) -> _Triggered | None:
        """T+N 命中：N 天前的非 neutral 信号 → 当前累积涨跌达预测方向 + 阈值。"""
        if snapshots_repo is None:
            return None
        target_date = curr.snapshot_date - timedelta(days=rule.t_plus_n_days)
        try:
            past = await snapshots_repo.get_latest_before(target_date)
        except Exception as exc:  # pragma: no cover — DB 异常
            logger.warning("T+N lookup failed: %s", exc)
            return None
        if past is None:
            return None
        try:
            past_level = TrendIndexLevel(past.index_level)
        except ValueError:
            return None
        if past_level == TrendIndexLevel.SIDEWAYS:
            return None
        past_close = float(past.close or 0.0)
        curr_close = float(curr.close_price or 0.0)
        if past_close <= 0 or curr_close <= 0:
            return None
        change_pct = (curr_close - past_close) / past_close * 100
        is_buy = past_level in (TrendIndexLevel.UP, TrendIndexLevel.STRONG_UP)
        is_sell = past_level in (TrendIndexLevel.DOWN, TrendIndexLevel.STRONG_DOWN)
        if is_buy and change_pct >= rule.t_plus_n_pct:
            subject = f"买入信号 T+{rule.t_plus_n_days} 命中 (+{change_pct:.2f}%)"
            body = (
                f"日期：{curr.snapshot_date}\n"
                f"信号日：{past.snapshot_date} ({_level_label_zh(past_level)})\n"
                f"窗口期累积涨跌：{change_pct:+.2f}%\n"
                f"阈值：{rule.t_plus_n_pct:.1f}%\n"
                f"信号日收盘：{past_close:.2f}\n"
                f"今日收盘：{curr_close:.2f}\n"
            )
            return _Triggered(
                key=f"t_plus_n:{rule.t_plus_n_days}:{rule.t_plus_n_pct}",
                subject=subject,
                body=body,
            )
        if is_sell and change_pct <= -rule.t_plus_n_pct:
            subject = f"卖出信号 T+{rule.t_plus_n_days} 命中 ({change_pct:.2f}%)"
            body = (
                f"日期：{curr.snapshot_date}\n"
                f"信号日：{past.snapshot_date} ({_level_label_zh(past_level)})\n"
                f"窗口期累积涨跌：{change_pct:+.2f}%\n"
                f"阈值：{rule.t_plus_n_pct:.1f}%\n"
                f"信号日收盘：{past_close:.2f}\n"
                f"今日收盘：{curr_close:.2f}\n"
            )
            return _Triggered(
                key=f"t_plus_n:{rule.t_plus_n_days}:{rule.t_plus_n_pct}",
                subject=subject,
                body=body,
            )
        return None

    # ── 静默段判定(整体规则,非单条) ───────────────

    def _is_quiet_window(self, rules: AlertRuleOut, now: datetime) -> bool:
        """判断当前时刻是否落在任何「窗口型规则」的静默语义内。

        逻辑:对每个 WindowRule(mode='quiet')和旧 QuietHours,若当前在窗口内
        则静默(入队);对每个 WindowRule(mode='active'),若当前在窗口外则
        静默(等价于把窗口外的告警也入队,等醒后批量推)。

        简化为「任意 window/quiet 规则当前命中静默语义 → True」。
        """
        # 旧 QuietHours(若 schema 迁移后 WindowRule 已包含,这里视为冗余保留)
        if rules.quiet_hours is not None and self._is_quiet_legacy(rules.quiet_hours, now):
            return True
        for rule in rules.rules:
            if isinstance(rule, WindowRule):
                in_win = self._is_in_window(rule.window, now)
                if rule.window.mode == "quiet" and in_win:
                    return True
                if rule.window.mode == "active" and not in_win:
                    return True
        return False

    async def flush_quiet_queue(
        self,
        repo: Any,
        notifiers: list[Notifier] | None = None,
        trace_id: str | None = None,
    ) -> int:
        """醒后(如 09:30 BJT)调用：一次性推送静默队列累积的告警。"""
        if not self._quiet_queue:
            return 0
        rules = await self._load_rules(repo)
        if notifiers is None:
            notifiers = NotifierFactory.create_all(rules.channels)
        if not notifiers:
            logger.warning("Quiet queue flush: no notifier configured")
            return 0
        n = len(self._quiet_queue)
        subject = f"黄金 ETF · 静默时段告警汇总（{n} 条）"
        body = "\n\n".join(f"[{k}] {s}\n{b}" for k, s, b in self._quiet_queue)
        sent = await self._fan_out(
            notifiers,
            subject=subject,
            body=body,
            key="quiet_summary",
            trace_id=trace_id,
        )
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

    def reset_for_testing(self) -> None:
        """测试隔离：清空去重状态与静默队列。"""
        self._sent_today.clear()
        self._quiet_queue.clear()


# ── helpers ──────────────────────────────────────


def _within_time_range(start_str: str, end_str: str, cur: time) -> bool:
    start = time.fromisoformat(start_str)
    end = time.fromisoformat(end_str)
    if start > end:
        return cur >= start or cur < end
    return start <= cur < end


def _is_main_axis_crossing(prev: TrendIndexLevel, curr: TrendIndexLevel) -> bool:
    """BULLISH↔BEARISH 主轴翻转(SIDEWAYS 抖动忽略)。"""
    prev_axis = _LEVEL_AXIS.get(prev, "neutral")
    curr_axis = _LEVEL_AXIS.get(curr, "neutral")
    if prev_axis == "neutral" or curr_axis == "neutral":
        return False
    return prev_axis != curr_axis


def _is_four_level_crossing(prev: TrendIndexLevel, curr: TrendIndexLevel) -> bool:
    """V0.74.0 N+18 细粒度:任意不同档位即触发(STRONG_UP↔UP 也算)。
    与主轴的区别是不忽略 SIDEWAYS 抖动;但相同档位不触发。"""
    return prev != curr


def _level_label_zh(level: TrendIndexLevel) -> str:
    return {
        TrendIndexLevel.STRONG_UP: "强势上升",
        TrendIndexLevel.UP: "上升",
        TrendIndexLevel.SIDEWAYS: "震荡整理",
        TrendIndexLevel.DOWN: "下降",
        TrendIndexLevel.STRONG_DOWN: "弱势下降",
    }.get(level, str(level))


# V0.72.0：档位主轴映射（SIDEWAYS = neutral，不算翻转）
_LEVEL_AXIS: dict[TrendIndexLevel, str] = {
    TrendIndexLevel.STRONG_UP: "bullish",
    TrendIndexLevel.UP: "bullish",
    TrendIndexLevel.SIDEWAYS: "neutral",
    TrendIndexLevel.DOWN: "bearish",
    TrendIndexLevel.STRONG_DOWN: "bearish",
}


# V0.72.0：BJT 时区
class _FixedOffsetTZ(tzinfo):
    def __init__(self, offset_hours: int) -> None:
        self._offset = timedelta(hours=offset_hours)

    def utcoffset(self, dt: datetime | None) -> timedelta:
        return self._offset

    def dst(self, dt: datetime | None) -> timedelta:
        return timedelta(0)

    def tzname(self, dt: datetime | None) -> str:
        return "BJT"


_BJT_TZ = _FixedOffsetTZ(8)


def _build_webpush_notifier(push_service: Any) -> Notifier | None:
    """V0.74.0 N+18 · 构造 WebPushNotifier 包装(PushService 注入)。"""
    from app.services.notify import WebPushNotifier

    return WebPushNotifier(push_service)


__all__ = ["AlertDispatcher", "_SnapshotInput"]
