"""今日要闻 scheduler 单测（V0.106 4h 节奏）

覆盖：
- V0.106 之前 6h 节奏（00/06/12/18 UTC）已不在代码里；测试只覆盖当前 4h 节奏
- NEWS_FEED_INTERVAL_HOURS = 4 验证
- 6 个时点（00/04/08/12/16/20 UTC）的 next_news_feed_run_utc 计算
- 跨日（20:00 / 23:00 UTC）→ 明日 00:00 UTC
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.services.scheduler import (
    NEWS_FEED_INTERVAL_HOURS,
    next_news_feed_run_utc,
)


def test_news_feed_interval_is_4h() -> None:
    """V0.106 NEWS_FEED_INTERVAL_HOURS = 4（用户原话「每四小更新一次」）。

    6h 节奏是 V0.102 默认，4h 是 V0.106 用户新加需求。
    """
    assert NEWS_FEED_INTERVAL_HOURS == 4


def test_next_run_morning_3am_utc() -> None:
    """UTC 03:00 → 下一个 4h 触发点 = 04:00 UTC。"""
    now = datetime(2026, 10, 19, 3, 0, 0, tzinfo=timezone.utc)
    nxt = next_news_feed_run_utc(now)
    assert nxt == datetime(2026, 10, 19, 4, 0, 0, tzinfo=timezone.utc)


def test_next_run_4am_utc_skips_to_8am() -> None:
    """UTC 04:00 整点 → 下一个触发点 = 08:00 UTC（4h 节奏，不重复 04:00）。"""
    now = datetime(2026, 10, 19, 4, 0, 0, tzinfo=timezone.utc)
    nxt = next_news_feed_run_utc(now)
    assert nxt == datetime(2026, 10, 19, 8, 0, 0, tzinfo=timezone.utc)


def test_next_run_8am_utc_skips_to_12pm() -> None:
    """UTC 08:00 整点 → 下一个触发点 = 12:00 UTC。"""
    now = datetime(2026, 10, 19, 8, 0, 0, tzinfo=timezone.utc)
    nxt = next_news_feed_run_utc(now)
    assert nxt == datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)


def test_next_run_4pm_utc_skips_to_8pm() -> None:
    """UTC 16:00 整点 → 下一个触发点 = 20:00 UTC。"""
    now = datetime(2026, 10, 19, 16, 0, 0, tzinfo=timezone.utc)
    nxt = next_news_feed_run_utc(now)
    assert nxt == datetime(2026, 10, 19, 20, 0, 0, tzinfo=timezone.utc)


def test_next_run_8pm_utc_rolls_to_next_day() -> None:
    """UTC 20:00 后（今日最后触发点过了）→ 明日 00:00 UTC。"""
    now = datetime(2026, 10, 19, 21, 0, 0, tzinfo=timezone.utc)
    nxt = next_news_feed_run_utc(now)
    assert nxt == datetime(2026, 10, 20, 0, 0, 0, tzinfo=timezone.utc)


def test_next_run_11pm_utc_rolls_to_next_day() -> None:
    """UTC 23:00 → 明日 00:00 UTC。"""
    now = datetime(2026, 10, 19, 23, 0, 0, tzinfo=timezone.utc)
    nxt = next_news_feed_run_utc(now)
    assert nxt == datetime(2026, 10, 20, 0, 0, 0, tzinfo=timezone.utc)


def test_next_run_default_uses_now_utc() -> None:
    """不传 now_utc 参数：默认 ``datetime.now(timezone.utc)``，结果应当 < 4h 之后的整点。"""
    nxt = next_news_feed_run_utc()
    # 下一个 4h 触发点距 now 不超过 4h

    now = datetime.now(timezone.utc)
    diff = (nxt - now).total_seconds()
    assert 0 <= diff <= 4 * 3600, f"diff {diff}s out of 4h window"
