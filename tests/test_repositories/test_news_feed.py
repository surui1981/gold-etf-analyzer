"""新闻流仓储单测（V0.104 单日模式扩展）

覆盖：
- list_items 现有 days 模式（与 V0.102 行为一致，0 字段破坏保护）
- list_items V0.104 date 模式：单日过滤 + tz_offset 边界
- list_items date + days 互斥：date 优先
- has_items_outside_day 4 象限：(older, newer) ∈ {T,F}²
- list_items 与 site_name / language / limit 复合过滤

镜像 tests/test_repositories/test_user_news_favorite.py 风格。
"""

from __future__ import annotations

from datetime import date as date_t, datetime, time, timedelta, timezone

import pytest

from app.models.news_feed import NewsFeedItem
from app.repositories.news_feed import NewsFeedRepository


# ──────────────── 公共 seed helper ────────────────


async def _seed(db) -> None:  # noqa: ANN001
    """3 条新闻跨 3 个日期（UTC）；与 tests/test_api/test_news_feed.py 一致。

    V0.105：每条带 ``category``（1001=财经 / 1002=财经 / 1003=科技）。
    """
    rows = [
        NewsFeedItem(
            external_id=1001,
            title="美联储官员暗示 11 月暂停加息",
            summary="美联储内部讨论 11 月暂停加息的可能",
            url="https://wallstreetcn.com/a/1001",
            mobile_url=None,
            site_name="华尔街见闻",
            language="zh-cn",
            author_name="张三",
            publish_date=datetime(2026, 10, 19, 0, 30, tzinfo=timezone.utc),
            source="readhub",
            category="财经",
        ),
        NewsFeedItem(
            external_id=1002,
            title="金价突破 2750 美元创历史新高",
            summary="受美元走弱支撑",
            url="https://cls.cn/a/1002",
            mobile_url=None,
            site_name="财联社",
            language="zh-cn",
            author_name=None,
            publish_date=datetime(2026, 10, 18, 8, 0, tzinfo=timezone.utc),
            source="readhub",
            category="财经",
        ),
        NewsFeedItem(
            external_id=1003,
            title="Powell signals rate cut pause",
            summary="Fed officials divided",
            url="https://reuters.com/a/1003",
            mobile_url=None,
            site_name="Reuters",
            language="en",
            author_name="Alice",
            publish_date=datetime(2026, 10, 17, 14, 0, tzinfo=timezone.utc),
            source="readhub",
            category="科技",  # V0.105：seeded 标科技便于测过滤
        ),
    ]
    for r in rows:
        db.add(r)
    await db.commit()


# ──────────────── V0.102 行为回归（0 字段破坏保护）────────────────


async def test_list_items_default_returns_all_in_desc_order(db_session) -> None:  # noqa: ANN001
    """默认无参：3 条全返回，按 publish_date 倒序。"""
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    items = await repo.list_items()
    assert len(items) == 3
    assert [it.external_id for it in items] == [1001, 1002, 1003]


async def test_list_items_days_filters_recent(db_session) -> None:  # noqa: ANN001
    """``days=1``：基于 UTC now cutoff，10-17 被排除。"""
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    items = await repo.list_items(days=1)
    # 10-17 距今 > 1 天（seed 是 2026-10，但 now 也接近），断言条数 ≤ 2
    assert all(it.external_id != 1003 for it in items)


# ──────────────── V0.104 · date 模式 ────────────────


async def test_list_items_by_date_filters_to_single_day(db_session) -> None:  # noqa: ANN001
    """``date=2026-10-18 + tz=0``：仅 1002（10-18 08:00 UTC）命中。"""
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    items = await repo.list_items(date=date_t(2026, 10, 18), tz_offset_minutes=0)
    assert [it.external_id for it in items] == [1002]


async def test_list_items_date_with_tz_offset_includes_late_night(db_session) -> None:  # noqa: ANN001
    """``date=2026-10-19 + tz=+480``（BJT）：1001 落 10-19 08:30 BJT，命中。

    1001 publish_date = 10-19 00:30 UTC = 10-19 08:30 BJT → 10-19 BJT 当天 ✅
    1002 publish_date = 10-18 08:00 UTC = 10-18 16:00 BJT → 不在 10-19 BJT
    1003 publish_date = 10-17 14:00 UTC = 10-17 22:00 BJT → 不在 10-19 BJT
    """
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    items = await repo.list_items(date=date_t(2026, 10, 19), tz_offset_minutes=480)
    assert [it.external_id for it in items] == [1001]


async def test_list_items_date_with_negative_tz_offset(db_session) -> None:  # noqa: ANN001
    """``date=2026-10-17 + tz=-300``（UTC-5 EST）：10-17 当天 EST 包含 1003。

    1003 publish_date = 10-17 14:00 UTC = 10-17 09:00 EST → 10-17 EST 当天 ✅
    """
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    items = await repo.list_items(date=date_t(2026, 10, 17), tz_offset_minutes=-300)
    assert [it.external_id for it in items] == [1003]


async def test_list_items_date_overrides_days(db_session) -> None:  # noqa: ANN001
    """date 与 days 同给：date 优先（service 层也是 date 优先）。"""
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    # days=90 会全返回；date=10-18 只返回 1 条 → 证明 date 优先
    items = await repo.list_items(
        days=90, date=date_t(2026, 10, 18), tz_offset_minutes=0
    )
    assert [it.external_id for it in items] == [1002]


# ──────────────── V0.104 · has_items_outside_day ────────────────


async def test_has_items_outside_day_middle_day(db_session) -> None:  # noqa: ANN001
    """选中间一天（10-18）：更早（10-17）+ 更晚（10-19）都存在 → (T, T)。"""
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    tz = timezone.utc
    day_start = datetime(2026, 10, 18, 0, 0, tzinfo=tz)
    day_end = datetime(2026, 10, 19, 0, 0, tzinfo=tz)
    has_older, has_newer = await repo.has_items_outside_day(
        day_start=day_start, day_end=day_end
    )
    assert (has_older, has_newer) == (True, True)


async def test_has_items_outside_day_latest_day(db_session) -> None:  # noqa: ANN001
    """选最新一天（10-19）：更早存在 + 更晚不存在 → (T, F)。"""
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    tz = timezone.utc
    day_start = datetime(2026, 10, 19, 0, 0, tzinfo=tz)
    day_end = datetime(2026, 10, 20, 0, 0, tzinfo=tz)
    has_older, has_newer = await repo.has_items_outside_day(
        day_start=day_start, day_end=day_end
    )
    assert (has_older, has_newer) == (True, False)


async def test_has_items_outside_day_earliest_day(db_session) -> None:  # noqa: ANN001
    """选最早一天（10-17）：更早不存在 + 更晚存在 → (F, T)。"""
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    tz = timezone.utc
    day_start = datetime(2026, 10, 17, 0, 0, tzinfo=tz)
    day_end = datetime(2026, 10, 18, 0, 0, tzinfo=tz)
    has_older, has_newer = await repo.has_items_outside_day(
        day_start=day_start, day_end=day_end
    )
    assert (has_older, has_newer) == (False, True)


async def test_has_items_outside_day_empty_window(db_session) -> None:  # noqa: ANN001
    """选一个数据之外的日期（10-15）：更早不存在 + 更晚存在 → (F, T)。

    验证：service 层在 empty day 也能给出正确的 has_older/has_newer。
    """
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    tz = timezone.utc
    day_start = datetime(2026, 10, 15, 0, 0, tzinfo=tz)
    day_end = datetime(2026, 10, 16, 0, 0, tzinfo=tz)
    has_older, has_newer = await repo.has_items_outside_day(
        day_start=day_start, day_end=day_end
    )
    assert (has_older, has_newer) == (False, True)


# ──────────────── V0.105 · 类目筛选 ────────────────


async def test_list_items_filter_category_returns_only_match(db_session) -> None:  # noqa: ANN001
    """V0.105 ``category='财经'`` → 仅 1001 / 1002 两条（1003 是「科技」）。"""
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    items = await repo.list_items(category="财经")
    assert sorted([it.external_id for it in items]) == [1001, 1002]


async def test_list_items_filter_category_combined_with_site(db_session) -> None:  # noqa: ANN001
    """V0.105 ``site_name='财联社' + category='财经'`` 交集 → 仅 1002。"""
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    items = await repo.list_items(site_name="财联社", category="财经")
    assert [it.external_id for it in items] == [1002]


async def test_list_items_filter_category_orthogonal_to_date(db_session) -> None:  # noqa: ANN001
    """V0.105 ``date + category`` 正交叠加：date=10-18 仅 1002（财经），科技不命中。"""
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    items = await repo.list_items(
        date=date_t(2026, 10, 18), tz_offset_minutes=0, category="科技"
    )
    assert items == []  # 1002 是财经，10-18 当天没有科技
    items2 = await repo.list_items(
        date=date_t(2026, 10, 18), tz_offset_minutes=0, category="财经"
    )
    assert [it.external_id for it in items2] == [1002]


async def test_list_items_category_orthogonal_to_days(db_session) -> None:  # noqa: ANN001
    """V0.105 ``days=90 + category='科技'`` → 仅 1003。"""
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    items = await repo.list_items(days=90, category="科技")
    assert [it.external_id for it in items] == [1003]


async def test_list_categories_returns_distinct_sorted_by_count(db_session) -> None:  # noqa: ANN001
    """V0.105 ``list_categories()`` → 频次降序：财经 (2) > 科技 (1)。"""
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    cats = await repo.list_categories()
    assert cats == ["财经", "科技"]


async def test_backfill_categories_classifies_null_rows(db_session) -> None:  # noqa: ANN001
    """V0.105 ``backfill_categories()``：所有 category=NULL 行被分类填入。

    模拟「老库 NULL 行」：插入 3 条 category=NULL 行（1001 财经 / 1002 财经 / 1003 科技），
    backfill 后应被 ``classify()`` 正确打上类目。
    """
    rows = [
        NewsFeedItem(
            external_id=2001,
            title="美联储 11月 暂停加息",
            summary="",
            url="https://wallstreetcn.com/a/2001",
            site_name="华尔街见闻",
            publish_date=datetime(2026, 10, 19, 0, 30, tzinfo=timezone.utc),
            source="readhub",
            category=None,  # legacy NULL
        ),
        NewsFeedItem(
            external_id=2002,
            title="金价突破 2750 美元",
            summary="美元走弱",
            url="https://cls.cn/a/2002",
            site_name="财联社",
            publish_date=datetime(2026, 10, 18, 8, 0, tzinfo=timezone.utc),
            source="readhub",
            category=None,  # legacy NULL
        ),
        NewsFeedItem(
            external_id=2003,
            title="Powell rate cut pause",
            summary="Fed officials",
            url="https://reuters.com/a/2003",
            site_name="Reuters",
            publish_date=datetime(2026, 10, 17, 14, 0, tzinfo=timezone.utc),
            source="readhub",
            category=None,  # legacy NULL
        ),
    ]
    for r in rows:
        db_session.add(r)
    await db_session.commit()

    repo = NewsFeedRepository(db_session)
    n = await repo.backfill_categories(batch_size=500)
    assert n == 3

    items = await repo.list_items()
    by_id = {it.external_id: it.category for it in items}
    assert by_id[2001] == "财经"
    assert by_id[2002] == "财经"
    # 2003 "Powell rate cut pause" + "Fed officials" + "Reuters" 无中文关键词命中 → 其他
    assert by_id[2003] == "其他"


async def test_backfill_categories_is_idempotent(db_session) -> None:  # noqa: ANN001
    """V0.105 ``backfill_categories()`` 幂等：第二次跑返回 0（无 NULL 行）。"""
    await _seed(db_session)  # seed 全有 category
    repo = NewsFeedRepository(db_session)
    n = await repo.backfill_categories(batch_size=500)
    assert n == 0


async def test_upsert_bulk_updates_category_on_conflict(db_session) -> None:  # noqa: ANN001
    """V0.105 ``upsert_bulk`` set_ 含 category：再次插入同 external_id 时 category 被覆盖。

    模拟 readhub 偶发标题/摘要微调 + classifier 重新分类的情况。
    """
    # seed 一条 category=财经
    await _seed(db_session)

    # 重抓同 external_id=1001，category 改为「科技」（人工干预模拟）
    repo = NewsFeedRepository(db_session)
    await repo.upsert_bulk([{
        "external_id": 1001,
        "title": "美联储 11月 暂停加息 (修正)",
        "summary": "AI 模型辅助分析",
        "url": "https://wallstreetcn.com/a/1001",
        "site_name": "华尔街见闻",
        "language": "zh-cn",
        "publish_date": datetime(2026, 10, 19, 0, 30, tzinfo=timezone.utc),
        "fetched_at": datetime.now(timezone.utc),
        "source": "readhub",
        "category": "科技",  # 强制改为科技
    }])
    items = await repo.list_items(category="科技")
    # 1001 被 upsert 改为「科技」，1003 原本就是「科技」→ 共 2 条
    assert sorted([it.external_id for it in items]) == [1001, 1003]
    # 不带 filter 应仍 3 条（upsert 不增减行数）
    all_items = await repo.list_items()
    assert len(all_items) == 3
    # 1001 现在的 category 确实被覆盖为「科技」
    item_1001 = await repo.find_by_external(1001)
    assert item_1001 is not None
    assert item_1001.category == "科技"
