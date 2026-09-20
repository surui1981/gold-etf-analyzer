"""每日定时任务：北京时间 07:00 自动捕获当日快照 + 预生成"已服务"缓存；
日内多次预热：09:30 / 11:30 / 14:00 / 15:30 BJT 刷新 served cache（V0.60.0 新增）；
央行购金月度刷新：每月 1/15/末日 07:30 自动从 WGC 拉取最新数据并落库。

运行机制
--------
- 应用启动后由 ``main.lifespan`` 启动两个后台 asyncio 协程；
- 每日协程：``asyncio.sleep`` 到下一个北京时间 07:00，唤醒后调用
  ``DailySnapshotService.capture_today()`` 持久化快照，并触发 ``TrendService.analyze()`` 预热；
- 央行购金协程：``asyncio.sleep`` 到下一个北京时间 07:30（与每日错开 30min 避免资源争抢），
  唤醒后调用 ``scripts.import_central_bank.run_import()`` 从 WGC fsapi 拉取并 upsert；
- 失败仅日志告警，不阻塞下次重试（页面会惰性重算）。

设计取舍
--------
- 不引入 APScheduler / cron 表达式：用纯 asyncio 协程 + 简单日历计算，
  依赖最小，启动即可见（无后台进程）。
- 跨日定时容错：进程若长时间停服（如计划维护）后重启，协程会在启动时立即触发一次捕获，
  保证今日缓存不空。
- 央行购金调度每月 3 次（1/15/末日 07:30 BJT）。WGC Gold Demand Trends 报告通常在季末后 6-8 周发布，
  月初/月中触发可尽早拿到新增数据；月末触发是兜底（应对前两次失败/网络抖动）。
- ``CENTRAL_BANK_AUTO_REFRESH`` 环境变量控制开关（默认 True）；置 False 可仅用 CLI 手动触发。
- V0.60.0 日内预热：每日协程内部串联日内分钟表（09:30/11:30/14:00/15:30 BJT），
  无需另起 asyncio 任务。失败仅日志告警，不抛异常。
- ``INTRADAY_REFRESH_ENABLED`` 环境变量控制开关（默认 True）。
"""

import asyncio
import calendar
import os
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.services.cache import set_served
from app.services.snapshot import DailySnapshotService
from app.services.trend import GUIDE_TARGET, TrendService
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 北京时间 = UTC+8
BJT = timezone(timedelta(hours=8))
DAILY_TRIGGER_HOUR_BJT = 7  # 每日北京时间 07:00 触发

# 央行购金月度刷新：每月 1 / 15 / 最后一日，07:30 BJT（与每日 07:00 错开 30min）
CB_TRIGGER_HOUR_BJT = 7
CB_TRIGGER_MINUTE_BJT = 30
CB_TRIGGER_DAYS = (1, 15)  # 月初 + 月中；月末由日历动态计算

# 环境变量开关：央行购金月度自动刷新（默认启用；设为 "0"/"false"/"no" 关闭）
CB_AUTO_REFRESH_ENV = "CENTRAL_BANK_AUTO_REFRESH"

# 环境变量开关：日内多次预热（V0.60.0 新增，默认启用）
INTRADAY_REFRESH_ENV = "INTRADAY_REFRESH_ENABLED"


def _is_cb_auto_refresh_enabled() -> bool:
    """读环境变量判断央行购金自动刷新是否启用。"""
    raw = os.environ.get(CB_AUTO_REFRESH_ENV, "1").strip().lower()
    return raw not in ("0", "false", "no", "off", "")


def is_intraday_refresh_enabled() -> bool:
    """读环境变量判断日内多次预热是否启用。"""
    raw = os.environ.get(INTRADAY_REFRESH_ENV, "1").strip().lower()
    if raw in ("0", "false", "no", "off", ""):
        return False
    return get_settings().intraday_refresh_enabled


def next_intraday_run_utc(now_utc: datetime | None = None) -> datetime:
    """计算下一个日内预热触发点的 UTC 时间。

    触发时刻由 ``settings.intraday_refresh_hour_list`` 决定（默认 09:30 / 11:30 /
    14:00 / 15:30 BJT）。今日触发点都过了 → 明日第一个触发点。

    Examples:
        BJT 2026-09-07 10:00 → 2026-09-07 11:30 BJT
        BJT 2026-09-07 16:00 → 2026-09-08 09:30 BJT（明日首个）
    """
    now = now_utc or datetime.now(timezone.utc)
    now_bjt = now.astimezone(BJT)
    triggers = get_settings().intraday_refresh_hour_list if is_intraday_refresh_enabled() else []
    for hh, mm in triggers:
        cand = now_bjt.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if cand > now_bjt:
            return cand.astimezone(timezone.utc)
    # 今日触发点都过（或被禁用） → 退到明日 09:30 作为兜底
    fallback = now_bjt.replace(hour=9, minute=30, second=0, microsecond=0) + timedelta(days=1)
    if triggers:
        hh, mm = triggers[0]
        fallback = (now_bjt + timedelta(days=1)).replace(
            hour=hh,
            minute=mm,
            second=0,
            microsecond=0,
        )
    return fallback.astimezone(timezone.utc)


def next_central_bank_run_utc() -> datetime:
    """计算下一次央行购金刷新的 UTC 时间。

    触发日：每月 1 日、15 日、当月最后一日。
    触发时间：北京时间 07:30。
    若当前 BJT 时间已过当次触发点，返回下一个触发日。

    Examples:
        BJT 2026-09-07 14:00 → 2026-09-15 07:30 BJT = 2026-09-14 23:30 UTC
        BJT 2026-09-14 23:00 → 2026-09-15 07:30 BJT（同月 15 日未到）
        BJT 2026-09-30 09:00 → 2026-09-30 07:30 BJT（已过，下个月 1 日）
    """
    now_utc = datetime.now(timezone.utc)
    now_bjt = now_utc.astimezone(BJT)

    # 生成当前月候选触发日列表（升序）
    last_day = calendar.monthrange(now_bjt.year, now_bjt.month)[1]
    candidates_bjt = [
        now_bjt.replace(
            day=1, hour=CB_TRIGGER_HOUR_BJT, minute=CB_TRIGGER_MINUTE_BJT, second=0, microsecond=0
        ),
        now_bjt.replace(
            day=15, hour=CB_TRIGGER_HOUR_BJT, minute=CB_TRIGGER_MINUTE_BJT, second=0, microsecond=0
        ),
        now_bjt.replace(
            day=last_day,
            hour=CB_TRIGGER_HOUR_BJT,
            minute=CB_TRIGGER_MINUTE_BJT,
            second=0,
            microsecond=0,
        ),
    ]

    # 找下一个未到的触发日；若当前月都过了，下个月 1 日
    for cand in candidates_bjt:
        if cand > now_bjt:
            return cand.astimezone(timezone.utc)

    # 全部已过 → 下月 1 日
    next_month_year = now_bjt.year + (1 if now_bjt.month == 12 else 0)
    next_month = 1 if now_bjt.month == 12 else now_bjt.month + 1
    return now_bjt.replace(
        year=next_month_year,
        month=next_month,
        day=1,
        hour=CB_TRIGGER_HOUR_BJT,
        minute=CB_TRIGGER_MINUTE_BJT,
        second=0,
        microsecond=0,
    ).astimezone(timezone.utc)


def next_run_utc() -> datetime:
    """计算下一个北京时间 07:00 对应的 UTC datetime。

    Examples:
        北京时间 2026-09-08 06:30 → 返回 2026-09-07 23:00 UTC
        北京时间 2026-09-08 08:00 → 返回 2026-09-08 23:00 UTC（明早）
    """
    now_utc = datetime.now(timezone.utc)
    now_bjt = now_utc.astimezone(BJT)
    target_bjt = now_bjt.replace(
        hour=DAILY_TRIGGER_HOUR_BJT,
        minute=0,
        second=0,
        microsecond=0,
    )
    if now_bjt >= target_bjt:
        target_bjt += timedelta(days=1)
    return target_bjt.astimezone(timezone.utc)


async def _capture_and_warm(snapshot_svc: DailySnapshotService, trend_svc: TrendService) -> None:
    """捕获当日快照并预热 served cache。

    失败仅日志，不抛异常：避免影响调度循环下一次触发。
    两条路径（快照成功 / 失败）都尝试预热 served cache，保证页面首屏命中。
    """
    snap_ok = False
    out = None
    try:
        out = await snapshot_svc.capture_today()
        logger.info(
            "Daily snapshot OK: date=%s, trend=%.1f (%s)",
            out.snapshot_date,
            out.trend_index,
            out.index_level,
        )
        snap_ok = True
    except Exception as exc:
        logger.error("Daily snapshot capture failed: %s", exc)

    # 显式预热 served cache：覆盖缓存（无论快照是否成功）
    try:
        result = await trend_svc.analyze(days=60, target=GUIDE_TARGET)
        set_served(GUIDE_TARGET, result)
        logger.info(
            "Served cache warmup: %s (index=%.1f)",
            "after snapshot" if snap_ok else "fallback (snapshot failed)",
            result.index.score,
        )
    except Exception as exc:
        logger.error("Served cache warmup failed: %s", exc)

    # V0.72.0 P3-b：告警分发钩子（仅快照成功时评估）
    if snap_ok and out is not None:
        try:
            from app.database import async_session_factory
            from app.dependencies import get_alert_dispatcher
            from app.repositories.settings import SettingRepository
            from app.schemas.market import TrendIndexLevel
            from app.services.alert import _SnapshotInput

            dispatcher = get_alert_dispatcher()
            async with async_session_factory() as session:
                repo = SettingRepository(session)
                prev_snapshot = await snapshot_svc.get_previous(out.snapshot_date)
                prev_input = None
                if prev_snapshot is not None:
                    prev_level = TrendIndexLevel(prev_snapshot.index_level)
                    prev_input = _SnapshotInput(
                        snapshot_date=prev_snapshot.snapshot_date,
                        trend_score=prev_snapshot.trend_index,
                        change_1d_pct=prev_snapshot.change_pct or 0.0,
                        trend_level=prev_level,
                    )
                curr_input = _SnapshotInput(
                    snapshot_date=out.snapshot_date,
                    trend_score=out.trend_index,
                    change_1d_pct=out.change_pct or 0.0,
                    trend_level=out.index_level,
                )
                triggered = await dispatcher.evaluate_and_dispatch(
                    prev=prev_input,
                    curr=curr_input,
                    repo=repo,
                )
                if triggered:
                    logger.info("Alert dispatched: %s", triggered)
        except Exception as exc:
            logger.warning("alert dispatch failed: %s", exc)


async def intraday_warm_once(trend_svc: TrendService) -> None:
    """单次日内预热（V0.60.0）：调 trend.analyze 并写入 served cache。

    不落库（区别于 daily_capture_and_warm 的快照落库）；只刷新 served cache，
    让趋势页 60s 轮询在前端立即拉到最新结果。失败仅日志，不抛异常。
    """
    try:
        result = await trend_svc.analyze(days=60, target=GUIDE_TARGET)
        set_served(GUIDE_TARGET, result)
        logger.info("Intraday warmup done (index=%.1f)", result.index.score)
    except Exception as exc:
        logger.error("Intraday warmup failed: %s", exc)


async def daily_capture_loop(
    snapshot_svc: DailySnapshotService,
    trend_svc: TrendService,
) -> None:
    """无限循环：每日 07:00 BJT 捕获快照 + 多个日内时点刷新 served cache。

    V0.60.0：在 ``daily`` 协程内部串联日内分钟表（09:30/11:30/14:00/15:30 BJT），
    不另起 asyncio 任务。每次循环取 ``next_daily`` 与 ``next_intraday`` 的最近点触发：
    - ``next_intraday`` 更近 → 仅刷新 served cache（不落库）
    - ``next_daily`` 更近   → 落库快照 + 刷新 served cache

    进程长时间停服重启后：协程下一次醒来时若发现今日触发点已过，会直接跳到明日，
    不会补触发（避免重算风暴；启动期 ``main._warm_cache()`` 已经做了一次预热）。
    """
    while True:
        next_daily = next_run_utc()
        next_intra = next_intraday_run_utc()
        next_run = min(next_daily, next_intra)
        is_intra = next_intra < next_daily
        wait = max(0.0, (next_run - datetime.now(timezone.utc)).total_seconds())
        logger.info(
            "Scheduler next: %s (in %.0fs, type=%s)",
            next_run.isoformat(),
            wait,
            "intraday" if is_intra else "daily",
        )
        await asyncio.sleep(wait)
        if is_intra:
            await intraday_warm_once(trend_svc)
        else:
            await _capture_and_warm(snapshot_svc, trend_svc)


async def _refresh_central_bank() -> int:
    """执行一次央行购金数据刷新（拉 WGC + 落库）。

    Returns:
        upserted 行数；失败返回 0。
    失败仅日志，不抛异常：避免影响调度循环下一次触发。
    """
    from app.scripts.import_central_bank import run_import  # 延迟导入（避开 lifespan 启动期）

    try:
        n = await run_import(include_manual=True)
        logger.info("Central bank auto-refresh OK: %d rows", n)
        return n
    except Exception as exc:
        logger.error("Central bank auto-refresh failed: %s", exc)
        return 0


async def monthly_central_bank_loop() -> None:
    """无限循环：每月 1/15/末日 07:30 BJT 自动刷新央行购金数据。

    通过环境变量 ``CENTRAL_BANK_AUTO_REFRESH`` 控制开关；默认启用。
    若当前进程启动时已过当月某触发点，协程会等到下一个触发日（启动不立即触发，
    避免与手动 CLI 重复执行）。
    """
    if not _is_cb_auto_refresh_enabled():
        logger.info(
            "Central bank auto-refresh DISABLED by env %s=0; "
            "use 'python -m app.scripts.import_central_bank' to refresh manually.",
            CB_AUTO_REFRESH_ENV,
        )
        return

    logger.info(
        "Central bank auto-refresh scheduler started: monthly on day 1, 15, and last day "
        "at %02d:%02d BJT (env %s controls switch)",
        CB_TRIGGER_HOUR_BJT,
        CB_TRIGGER_MINUTE_BJT,
        CB_AUTO_REFRESH_ENV,
    )

    while True:
        next_run = next_central_bank_run_utc()
        wait = max(0.0, (next_run - datetime.now(timezone.utc)).total_seconds())
        logger.info(
            "Central bank scheduler: next run at %s (in %.0f seconds, %.1f hours)",
            next_run.isoformat(),
            wait,
            wait / 3600,
        )
        await asyncio.sleep(wait)
        await _refresh_central_bank()
