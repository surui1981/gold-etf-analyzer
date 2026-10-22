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
from datetime import date, datetime, timedelta, timezone

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

# V0.102 ── 今日要闻 6h 自动刷新
# readhub 内部 API 匿名稳定，6h 一次足够覆盖「今日要闻」用户面（实测 1h ≈ 8-15 条）
NEWS_FEED_AUTO_REFRESH_ENV = "NEWS_FEED_AUTO_REFRESH"
NEWS_FEED_INTERVAL_HOURS = 4  # 00/04/08/12/16/20 UTC ≈ 08/12/16/20/00/04 BJT
# V0.106 用户原话「更新策略也没有实现，修改成每四小更新一次财经新闻」：
# 从 6h（4 触发点/日）加密到 4h（6 触发点/日），让首页顶部「今日要闻」chip
# 更频繁更新。readhub 内部 API 1h ≈ 8-15 条新流，4h 抓一次覆盖率足够。
# 启动后 30s 立即抓一次（不让用户首次访问看到空表）
NEWS_FEED_BOOTSTRAP_DELAY_SECONDS = 30.0


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


def _is_news_feed_auto_refresh_enabled() -> bool:
    """读环境变量判断今日要闻自动刷新是否启用（V0.102）。"""
    raw = os.environ.get(NEWS_FEED_AUTO_REFRESH_ENV, "1").strip().lower()
    return raw not in ("0", "false", "no", "off", "")


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

    # V0.72.0 P3-b + V0.74.0 N+18：告警分发钩子（仅快照成功时评估）
    if snap_ok and out is not None:
        try:
            from app.database import async_session_factory
            from app.dependencies import get_alert_dispatcher
            from app.repositories.settings import SettingRepository
            from app.repositories.snapshot import SnapshotRepository
            from app.schemas.market import TrendIndexLevel
            from app.services.alert import _SnapshotInput

            dispatcher = get_alert_dispatcher()
            async with async_session_factory() as session:
                repo = SettingRepository(session)
                snap_repo = SnapshotRepository(session)
                prev_snapshot = await snapshot_svc.get_previous(out.snapshot_date)
                prev_input = None
                if prev_snapshot is not None:
                    prev_level = TrendIndexLevel(prev_snapshot.index_level)
                    prev_input = _SnapshotInput(
                        snapshot_date=prev_snapshot.snapshot_date,
                        trend_score=prev_snapshot.trend_index,
                        change_1d_pct=prev_snapshot.change_pct or 0.0,
                        trend_level=prev_level,
                        close_price=prev_snapshot.close or 0.0,
                    )
                curr_input = _SnapshotInput(
                    snapshot_date=out.snapshot_date,
                    trend_score=out.trend_index,
                    change_1d_pct=out.change_pct or 0.0,
                    trend_level=out.index_level,
                    close_price=out.close or 0.0,
                )
                triggered = await dispatcher.evaluate_and_dispatch(
                    prev=prev_input,
                    curr=curr_input,
                    repo=repo,
                    snapshots_repo=snap_repo,
                )
                if triggered:
                    logger.info("Alert dispatched: %s", triggered)
        except Exception as exc:
            logger.warning("alert dispatch failed: %s", exc)

    # ── step 3（V0.79.0 Step E）：macro factor 落表 + warm threshold cache ──
    # 复用 trend_svc._macro._collect() 产出当日 5 因子原始值，按唯一键
    # (target, snapshot_date, factor_key) upsert 到 daily_macro_factors 表。
    # 失败仅日志告警，不抛异常：避免影响调度循环下一次触发。
    try:
        from app.repositories.db import async_session_factory
        from app.repositories.macro_factor_history import MacroFactorHistoryRepository
        from app.services.macro_thresholds import MacroThresholdCalculator

        values = await trend_svc._macro._collect()
        async with async_session_factory() as session:
            repo = MacroFactorHistoryRepository(session)
            await repo.upsert_batch(
                target="default",
                snapshot_date=date.today(),
                factors=[(key, val, dt, src) for key, (val, dt, src) in values.items()],
            )
            calculator = MacroThresholdCalculator(repo=repo)
            thresholds = await calculator.get_or_compute("default", today=date.today())
            logger.info(
                "Macro factor persisted + threshold warmed: %d factors, date=%s, dynamic=%s",
                len(values),
                date.today().isoformat(),
                calculator.is_dynamic_active(thresholds),
            )
    except Exception as exc:
        logger.warning("Macro factor persist/warmup failed: %s", exc)


async def intraday_warm_once(
    trend_svc: TrendService,
    snapshot_svc: DailySnapshotService | None = None,
) -> None:
    """单次日内预热（V0.60.0）：调 trend.analyze 并写入 served cache。

    不落库（区别于 daily_capture_and_warm 的快照落库）；只刷新 served cache，
    让趋势页 60s 轮询在前端立即拉到最新结果。失败仅日志，不抛异常。

    V0.74.0 N+18：传入 snapshot_svc 时,顺手评估一次 dispatcher(T+N 命中可能在
    日内多个时点被发现,不必等 07:00 BJT)。
    """
    try:
        result = await trend_svc.analyze(days=60, target=GUIDE_TARGET)
        set_served(GUIDE_TARGET, result)
        logger.info("Intraday warmup done (index=%.1f)", result.index.score)
    except Exception as exc:
        logger.error("Intraday warmup failed: %s", exc)

    # V0.74.0 N+18 · 日内告警评估
    if snapshot_svc is not None:
        try:
            await _intraday_dispatch(snapshot_svc)
        except Exception as exc:
            logger.warning("intraday alert dispatch failed: %s", exc)


async def _intraday_dispatch(snapshot_svc: DailySnapshotService) -> None:
    """V0.74.0 N+18 · 日内 60min 评估告警（无需重新落快照）。"""
    from datetime import date as _date

    from app.database import async_session_factory
    from app.dependencies import get_alert_dispatcher
    from app.repositories.settings import SettingRepository
    from app.repositories.snapshot import SnapshotRepository
    from app.schemas.market import TrendIndexLevel
    from app.services.alert import _SnapshotInput

    today = _date.today()
    dispatcher = get_alert_dispatcher()
    async with async_session_factory() as session:
        snap_repo = SnapshotRepository(session)
        # + 1 day 确保今天也能命中(若数据库已存今日快照)
        tomorrow = today.fromordinal(today.toordinal() + 1)
        latest = await snap_repo.get_latest_before(tomorrow)
        if latest is None:
            return
        prev = await snap_repo.get_latest_before(latest.snapshot_date)
        repo = SettingRepository(session)
        prev_input = None
        if prev is not None:
            try:
                prev_level = TrendIndexLevel(prev.index_level)
            except ValueError:
                prev_level = TrendIndexLevel.SIDEWAYS
            prev_input = _SnapshotInput(
                snapshot_date=prev.snapshot_date,
                trend_score=prev.trend_index or 0.0,
                change_1d_pct=prev.change_pct or 0.0,
                trend_level=prev_level,
                close_price=prev.close or 0.0,
            )
        try:
            curr_level = TrendIndexLevel(latest.index_level)
        except ValueError:
            curr_level = TrendIndexLevel.SIDEWAYS
        curr_input = _SnapshotInput(
            snapshot_date=latest.snapshot_date,
            trend_score=latest.trend_index or 0.0,
            change_1d_pct=latest.change_pct or 0.0,
            trend_level=curr_level,
            close_price=latest.close or 0.0,
        )
        triggered = await dispatcher.evaluate_and_dispatch(
            prev=prev_input,
            curr=curr_input,
            repo=repo,
            snapshots_repo=snap_repo,
        )
        if triggered:
            logger.info("Intraday alert dispatched: %s", triggered)


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
            # V0.74.0 N+18：传 snapshot_svc 让日内评估也走 dispatcher(T+N 命中)
            await intraday_warm_once(trend_svc, snapshot_svc=snapshot_svc)
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


# V0.102 ── 今日要闻自动刷新（V0.106 加密 6h → 4h）────────────


def next_news_feed_run_utc(now_utc: datetime | None = None) -> datetime:
    """计算下一次 readhub 抓取的 UTC 时间。

    触发时刻：``NEWS_FEED_INTERVAL_HOURS`` 倍数（4h 节奏 → 00/04/08/12/16/20 UTC
    ≈ 08/12/16/20/00/04 BJT；6h 节奏 → 00/06/12/18 UTC ≈ 08/14/20/02 BJT）。
    今日触发点都过了 → 明日 00:00 UTC。

    Examples:
        UTC 2026-10-19 03:00 (4h 节奏) → 2026-10-19 04:00 UTC
        UTC 2026-10-19 20:00 (4h 节奏) → 2026-10-20 00:00 UTC（明日首个）
    """
    now = now_utc or datetime.now(timezone.utc)
    hours = tuple(range(0, 24, NEWS_FEED_INTERVAL_HOURS))
    for hour in hours:
        cand = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if cand > now:
            return cand
    # 今日最后一个触发点也过了 → 明日 00:00
    return (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


async def _refresh_news_feed() -> int:
    """执行一次 readhub 抓取 + 落库（V0.102），V0.107 末尾重建日聚合。

    Returns:
        upserted 行数；失败返回 0。
    失败仅日志，不抛异常：避免影响调度循环下一次触发。

    V0.107 daily 重建：refresh 成功后**始终**重建 BJT 当日 + BJT 昨日 2 行
    （覆盖「跨 BJT 午夜 refresh」场景，避免昨日聚合遗漏）。
    2 次 rebuild ≈ 20ms，可接受（idempotent + self-healing）。
    """
    from app.repositories.db import async_session_factory
    from app.services.news_feed import NewsFeedService

    try:
        async with async_session_factory() as session:
            from app.repositories.news_feed import NewsFeedRepository

            service = NewsFeedService(NewsFeedRepository(session))
            result = await service.refresh(force=True)
            n_upserted = int(result["upserted"]) if result["ok"] else 0

            # V0.107：refresh 成功 → 重建 BJT 当日 + BJT 昨日
            # 即使 result.ok=False 仍尝试 rebuild：失败时仍可能有上次成功抓取的数据
            bjt_tz = timezone(timedelta(hours=8))
            bjt_today = datetime.now(bjt_tz).date()
            bjt_yesterday = bjt_today - timedelta(days=1)
            for d in (bjt_yesterday, bjt_today):  # 倒序避免同日覆盖顺序问题
                try:
                    rebuilt = await service.rebuild_daily(d)
                    if rebuilt is not None:
                        logger.info(
                            "news_feed_daily rebuilt: %s total=%d",
                            d,
                            rebuilt.total_count,
                        )
                except Exception as exc:
                    logger.error("rebuild_daily(%s) failed: %s", d, exc)

        if result["ok"]:
            logger.info("News feed auto-refresh OK: %d rows", n_upserted)
            return n_upserted
        logger.warning("News feed auto-refresh failed: %s", result.get("error"))
        return 0
    except Exception as exc:
        logger.error("News feed auto-refresh unexpected error: %s", exc)
        return 0


async def news_feed_loop() -> None:
    """无限循环：每 ``NEWS_FEED_INTERVAL_HOURS`` 小时抓一次 readhub（V0.106 4h）。

    通过环境变量 ``NEWS_FEED_AUTO_REFRESH`` 控制开关；默认启用。
    启动后 ``NEWS_FEED_BOOTSTRAP_DELAY_SECONDS``（30s）立即抓一次（不延迟到
    下一个触发点），保证用户首次访问页面不是空表。
    """
    if not _is_news_feed_auto_refresh_enabled():
        logger.info(
            "News feed auto-refresh DISABLED by env %s=0; "
            # ⚠ 原先提示 `python -m app.scripts.refresh_news_feed` —— 那个模块
            # 从来不存在（src/app/scripts/ 下只有 import_central_bank.py）。
            # 用户关掉自动刷新后照着这条提示敲命令，只会拿到一个 no module named。
            # 改成指向真实存在的 admin 端点。
            "call POST /api/v1/news-feed/refresh to refresh manually.",
            NEWS_FEED_AUTO_REFRESH_ENV,
        )
        return

    hours_label = "/".join(f"{h:02d}" for h in range(0, 24, NEWS_FEED_INTERVAL_HOURS))
    logger.info(
        "News feed auto-refresh scheduler started: every %dh (%s UTC), "
        "bootstrap in %.0fs (env %s controls switch)",
        NEWS_FEED_INTERVAL_HOURS,
        hours_label,
        NEWS_FEED_BOOTSTRAP_DELAY_SECONDS,
        NEWS_FEED_AUTO_REFRESH_ENV,
    )

    # 启动后 30s 立即抓一次（避开 lifespan 启动期资源争抢）
    await asyncio.sleep(NEWS_FEED_BOOTSTRAP_DELAY_SECONDS)
    await _refresh_news_feed()

    while True:
        next_run = next_news_feed_run_utc()
        wait = max(0.0, (next_run - datetime.now(timezone.utc)).total_seconds())
        logger.info(
            "News feed scheduler: next run at %s (in %.0f seconds, %.1f hours)",
            next_run.isoformat(),
            wait,
            wait / 3600,
        )
        await asyncio.sleep(wait)
        await _refresh_news_feed()


# V0.115.0 ── COMEX 黄金库存自动刷新 ────────────────────────────

# 触发时刻 08:10 BJT。刻意跟已有几个触发点错开：
#   07:00 BJT 每日快照（daily_capture_loop）
#   07:30 BJT 央行购金（月度）
#   00/04/08/12/16/20 UTC 今日要闻（4h）
# 08:10 落在 08:00 那次新闻抓取之后 10 分钟，不抢同一个源，也不在 A 股开盘
# （09:30）之前 —— 库存是慢变量，晚十分钟没有任何信息损失。
GOLD_INV_TRIGGER_HOUR_BJT = 8
GOLD_INV_TRIGGER_MINUTE_BJT = 10

# 环境变量开关：COMEX 库存自动刷新（默认启用；设为 "0"/"false"/"no" 关闭）
GOLD_INVENTORY_AUTO_REFRESH_ENV = "GOLD_INVENTORY_AUTO_REFRESH"

# 启动后 bootstrap 延迟：避开 lifespan 启动期资源争抢（同新闻流的 30s）。
# 只在「表空 / 最新观测超过 1 天」时才真抓，避免每次重启全量 upsert 1200+ 行。
GOLD_INV_BOOTSTRAP_DELAY_SECONDS = 45.0


def _is_gold_inventory_auto_refresh_enabled() -> bool:
    """读环境变量判断 COMEX 库存自动刷新是否启用（V0.115.0）。"""
    raw = os.environ.get(GOLD_INVENTORY_AUTO_REFRESH_ENV, "1").strip().lower()
    return raw not in ("0", "false", "no", "off", "")


def next_gold_inventory_run_utc(now_utc: datetime | None = None) -> datetime:
    """计算下一次 COMEX 库存刷新的 UTC 时间（每日 08:10 BJT）。

    今日触发点已过 → 明日同一时刻。

    Examples:
        BJT 2026-10-22 07:00 → BJT 2026-10-22 08:10 = 2026-10-22 00:10 UTC
        BJT 2026-10-22 09:00 → BJT 2026-10-23 08:10 = 2026-10-23 00:10 UTC
    """
    now = now_utc or datetime.now(timezone.utc)
    now_bjt = now.astimezone(BJT)
    cand = now_bjt.replace(
        hour=GOLD_INV_TRIGGER_HOUR_BJT,
        minute=GOLD_INV_TRIGGER_MINUTE_BJT,
        second=0,
        microsecond=0,
    )
    if cand > now_bjt:
        return cand.astimezone(timezone.utc)
    return (cand + timedelta(days=1)).astimezone(timezone.utc)


async def _refresh_gold_inventory() -> int:
    """执行一次 COMEX 库存抓取 + 落库。

    Returns:
        upserted 行数；失败返回 0。失败仅日志，不抛 —— 单个源挂掉不该
        影响调度循环下一次触发（首页该卡显示「—」，不是整站失联）。
    """
    from app.repositories.db import async_session_factory
    from app.repositories.gold_inventory import GoldInventoryRepository
    from app.services.gold_inventory import GoldInventoryService

    try:
        async with async_session_factory() as session:
            service = GoldInventoryService(repo=GoldInventoryRepository(session))
            return await service.refresh()
    except Exception as exc:
        logger.error("gold inventory auto-refresh unexpected error: %s", exc)
        return 0


async def gold_inventory_loop() -> None:
    """无限循环：每日 08:10 BJT 刷新 COMEX 黄金库存。

    通过环境变量 ``GOLD_INVENTORY_AUTO_REFRESH`` 控制开关；默认启用。
    启动后 45s 做一次 **条件** bootstrap —— 仅当表为空或最新观测超过 1 天
    才抓，否则跳过（重启不该每次都重写 1200+ 行）。
    """
    if not _is_gold_inventory_auto_refresh_enabled():
        logger.info(
            "Gold inventory auto-refresh DISABLED by env %s=0; "
            "use 'python -m app.scripts.import_gold_inventory' to refresh manually.",
            GOLD_INVENTORY_AUTO_REFRESH_ENV,
        )
        return

    logger.info(
        "Gold inventory auto-refresh scheduler started: daily at %02d:%02d BJT "
        "(env %s controls switch)",
        GOLD_INV_TRIGGER_HOUR_BJT,
        GOLD_INV_TRIGGER_MINUTE_BJT,
        GOLD_INVENTORY_AUTO_REFRESH_ENV,
    )

    await asyncio.sleep(GOLD_INV_BOOTSTRAP_DELAY_SECONDS)
    try:
        from app.repositories.db import async_session_factory
        from app.repositories.gold_inventory import GoldInventoryRepository
        from app.services.gold_inventory import GoldInventoryService

        async with async_session_factory() as session:
            svc = GoldInventoryService(repo=GoldInventoryRepository(session))
            if await svc.is_stale():
                logger.info("gold inventory bootstrap: table empty or stale, fetching")
                await svc.refresh()
            else:
                logger.info("gold inventory bootstrap skipped: table already current")
    except Exception as exc:
        logger.error("gold inventory bootstrap failed: %s", exc)

    while True:
        next_run = next_gold_inventory_run_utc()
        wait = max(0.0, (next_run - datetime.now(timezone.utc)).total_seconds())
        logger.info(
            "Gold inventory scheduler: next run at %s (in %.0f seconds, %.1f hours)",
            next_run.isoformat(),
            wait,
            wait / 3600,
        )
        await asyncio.sleep(wait)
        await _refresh_gold_inventory()
