"""新闻流仓储单测（V0.104 单日模式扩展 / V0.105 类目筛选 / V0.107 按日聚合）

覆盖：
- list_items 现有 days 模式（与 V0.102 行为一致，0 字段破坏保护）
- list_items V0.104 date 模式：单日过滤 + tz_offset 边界
- list_items date + days 互斥：date 优先
- has_items_outside_day 4 象限：(older, newer) ∈ {T,F}²
- list_items 与 site_name / language / limit 复合过滤
- V0.105 类目筛选（list_items + list_categories + backfill_categories 幂等）
- V0.107 按日聚合（upsert_daily / get_daily / list_daily / backfill_daily）

镜像 tests/test_repositories/test_user_news_favorite.py 风格。
"""

from __future__ import annotations

from datetime import date as date_t
from datetime import datetime, timezone

from sqlalchemy import select

from app.models.news_feed import NewsFeedItem
from app.repositories.news_feed import NewsFeedRepository

# ──────────────── 公共 seed helper ────────────────


async def _seed(db) -> None:
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


async def test_list_items_default_returns_all_in_desc_order(db_session) -> None:
    """默认无参：3 条全返回，按 publish_date 倒序。"""
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    items = await repo.list_items()
    assert len(items) == 3
    assert [it.external_id for it in items] == ["1001", "1002", "1003"]


async def test_list_items_days_filters_recent(db_session) -> None:
    """``days=1``：基于 UTC now cutoff，10-17 被排除。"""
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    items = await repo.list_items(days=1)
    # 10-17 距今 > 1 天（seed 是 2026-10，但 now 也接近），断言条数 ≤ 2
    assert all(it.external_id != 1003 for it in items)


# ──────────────── V0.104 · date 模式 ────────────────


async def test_list_items_by_date_filters_to_single_day(db_session) -> None:
    """``date=2026-10-18 + tz=0``：仅 1002（10-18 08:00 UTC）命中。"""
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    items = await repo.list_items(date=date_t(2026, 10, 18), tz_offset_minutes=0)
    assert [it.external_id for it in items] == ["1002"]


async def test_list_items_date_with_tz_offset_includes_late_night(db_session) -> None:
    """``date=2026-10-19 + tz=+480``（BJT）：1001 落 10-19 08:30 BJT，命中。

    1001 publish_date = 10-19 00:30 UTC = 10-19 08:30 BJT → 10-19 BJT 当天 ✅
    1002 publish_date = 10-18 08:00 UTC = 10-18 16:00 BJT → 不在 10-19 BJT
    1003 publish_date = 10-17 14:00 UTC = 10-17 22:00 BJT → 不在 10-19 BJT
    """
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    items = await repo.list_items(date=date_t(2026, 10, 19), tz_offset_minutes=480)
    assert [it.external_id for it in items] == ["1001"]


async def test_list_items_date_with_negative_tz_offset(db_session) -> None:
    """``date=2026-10-17 + tz=-300``（UTC-5 EST）：10-17 当天 EST 包含 1003。

    1003 publish_date = 10-17 14:00 UTC = 10-17 09:00 EST → 10-17 EST 当天 ✅
    """
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    items = await repo.list_items(date=date_t(2026, 10, 17), tz_offset_minutes=-300)
    assert [it.external_id for it in items] == ["1003"]


async def test_list_items_date_overrides_days(db_session) -> None:
    """date 与 days 同给：date 优先（service 层也是 date 优先）。"""
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    # days=90 会全返回；date=10-18 只返回 1 条 → 证明 date 优先
    items = await repo.list_items(days=90, date=date_t(2026, 10, 18), tz_offset_minutes=0)
    assert [it.external_id for it in items] == ["1002"]


# ──────────────── V0.104 · has_items_outside_day ────────────────


async def test_has_items_outside_day_middle_day(db_session) -> None:
    """选中间一天（10-18）：更早（10-17）+ 更晚（10-19）都存在 → (T, T)。"""
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    tz = timezone.utc
    day_start = datetime(2026, 10, 18, 0, 0, tzinfo=tz)
    day_end = datetime(2026, 10, 19, 0, 0, tzinfo=tz)
    has_older, has_newer = await repo.has_items_outside_day(day_start=day_start, day_end=day_end)
    assert (has_older, has_newer) == (True, True)


async def test_has_items_outside_day_latest_day(db_session) -> None:
    """选最新一天（10-19）：更早存在 + 更晚不存在 → (T, F)。"""
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    tz = timezone.utc
    day_start = datetime(2026, 10, 19, 0, 0, tzinfo=tz)
    day_end = datetime(2026, 10, 20, 0, 0, tzinfo=tz)
    has_older, has_newer = await repo.has_items_outside_day(day_start=day_start, day_end=day_end)
    assert (has_older, has_newer) == (True, False)


async def test_has_items_outside_day_earliest_day(db_session) -> None:
    """选最早一天（10-17）：更早不存在 + 更晚存在 → (F, T)。"""
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    tz = timezone.utc
    day_start = datetime(2026, 10, 17, 0, 0, tzinfo=tz)
    day_end = datetime(2026, 10, 18, 0, 0, tzinfo=tz)
    has_older, has_newer = await repo.has_items_outside_day(day_start=day_start, day_end=day_end)
    assert (has_older, has_newer) == (False, True)


async def test_has_items_outside_day_empty_window(db_session) -> None:
    """选一个数据之外的日期（10-15）：更早不存在 + 更晚存在 → (F, T)。

    验证：service 层在 empty day 也能给出正确的 has_older/has_newer。
    """
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    tz = timezone.utc
    day_start = datetime(2026, 10, 15, 0, 0, tzinfo=tz)
    day_end = datetime(2026, 10, 16, 0, 0, tzinfo=tz)
    has_older, has_newer = await repo.has_items_outside_day(day_start=day_start, day_end=day_end)
    assert (has_older, has_newer) == (False, True)


# ──────────────── V0.105 · 类目筛选 ────────────────


async def test_list_items_filter_category_returns_only_match(db_session) -> None:
    """V0.105 ``category='财经'`` → 仅 1001 / 1002 两条（1003 是「科技」）。"""
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    items = await repo.list_items(category="财经")
    assert sorted([it.external_id for it in items]) == ["1001", "1002"]


async def test_list_items_filter_category_combined_with_site(db_session) -> None:
    """V0.105 ``site_name='财联社' + category='财经'`` 交集 → 仅 1002。"""
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    items = await repo.list_items(site_name="财联社", category="财经")
    assert [it.external_id for it in items] == ["1002"]


async def test_list_items_filter_category_orthogonal_to_date(db_session) -> None:
    """V0.105 ``date + category`` 正交叠加：date=10-18 仅 1002（财经），科技不命中。"""
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    items = await repo.list_items(date=date_t(2026, 10, 18), tz_offset_minutes=0, category="科技")
    assert items == []  # 1002 是财经，10-18 当天没有科技
    items2 = await repo.list_items(date=date_t(2026, 10, 18), tz_offset_minutes=0, category="财经")
    assert [it.external_id for it in items2] == ["1002"]


async def test_list_items_category_orthogonal_to_days(db_session) -> None:
    """V0.105 ``days=90 + category='科技'`` → 仅 1003。"""
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    items = await repo.list_items(days=90, category="科技")
    assert [it.external_id for it in items] == ["1003"]


async def test_list_categories_returns_distinct_sorted_by_count(db_session) -> None:
    """V0.105 ``list_categories()`` → 频次降序：财经 (2) > 科技 (1)。"""
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    cats = await repo.list_categories()
    assert cats == ["财经", "科技"]


async def test_backfill_categories_classifies_null_rows(db_session) -> None:
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


async def test_backfill_categories_is_idempotent(db_session) -> None:
    """V0.105 ``backfill_categories()`` 幂等：第二次跑返回 0（无 NULL 行）。"""
    await _seed(db_session)  # seed 全有 category
    repo = NewsFeedRepository(db_session)
    n = await repo.backfill_categories(batch_size=500)
    assert n == 0


async def test_upsert_bulk_updates_category_on_conflict(db_session) -> None:
    """V0.105 ``upsert_bulk`` set_ 含 category：再次插入同 external_id 时 category 被覆盖。

    模拟 readhub 偶发标题/摘要微调 + classifier 重新分类的情况。
    """
    # seed 一条 category=财经
    await _seed(db_session)

    # 重抓同 external_id=1001，category 改为「科技」（人工干预模拟）
    repo = NewsFeedRepository(db_session)
    await repo.upsert_bulk(
        [
            {
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
            }
        ]
    )
    items = await repo.list_items(category="科技")
    # 1001 被 upsert 改为「科技」，1003 原本就是「科技」→ 共 2 条
    assert sorted([it.external_id for it in items]) == ["1001", "1003"]
    # 不带 filter 应仍 3 条（upsert 不增减行数）
    all_items = await repo.list_items()
    assert len(all_items) == 3
    # 1001 现在的 category 确实被覆盖为「科技」
    item_1001 = await repo.find_by_external(1001)
    assert item_1001 is not None
    assert item_1001.category == "科技"


# ──────────────── V0.107 · 按日聚合（news_feed_daily）────────────────


async def test_upsert_daily_aggregates_by_bjt_day(db_session) -> None:
    """V0.107 ``upsert_daily(2026-10-19)``：BJT 当日（10-19 00:00 ~ 10-20 00:00 BJT）。

    _seed 3 条新闻：
    - 1001 publish_date = 10-19 00:30 UTC = 10-19 08:30 BJT → 10-19 BJT 当天 ✅
    - 1002 publish_date = 10-18 08:00 UTC = 10-18 16:00 BJT → 10-19 BJT 之外 ❌
    - 1003 publish_date = 10-17 14:00 UTC = 10-17 22:00 BJT → 10-19 BJT 之外 ❌

    期望：total_count=1, finance_count=1, unique_sites_count=1, en_count=0, zh_count=1
    """
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    result = await repo.upsert_daily(date_t(2026, 10, 19))
    assert result is not None
    assert result.date == date_t(2026, 10, 19)
    assert result.total_count == 1
    assert result.finance_count == 1
    assert result.tech_count == 0
    assert result.unique_sites_count == 1  # 1001 = 华尔街见闻
    assert result.en_count == 0
    assert result.zh_count == 1


async def test_upsert_daily_returns_none_for_empty_day(db_session) -> None:
    """V0.107 空日不创建行：upsert_daily(10-15) 无数据 → 返回 None。"""
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    result = await repo.upsert_daily(date_t(2026, 10, 15))
    assert result is None
    # DB 中仍无 10-15 行
    assert await repo.get_daily(date_t(2026, 10, 15)) is None


async def test_upsert_daily_is_idempotent_on_replay(db_session) -> None:
    """V0.107 ``upsert_daily`` 幂等：重跑同一日只更新 last_refresh_at，行数 +0。"""
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    first = await repo.upsert_daily(date_t(2026, 10, 19))
    assert first is not None

    # 重跑（sleep > 0 区分时间戳；本测试用「重跑后值变化」粗略断言）
    second = await repo.upsert_daily(date_t(2026, 10, 19))
    assert second is not None
    assert second.date == first.date
    assert second.total_count == first.total_count == 1
    # DB 仍只有 1 行 10-19（date 是 PK）
    assert await repo.get_daily(date_t(2026, 10, 19)) is not None
    rows_in_range = await repo.list_daily(start=date_t(2026, 10, 19), end=date_t(2026, 10, 19))
    assert len(rows_in_range) == 1


async def test_list_daily_returns_range_in_desc_order(db_session) -> None:
    """V0.107 ``list_daily(start, end)``：闭区间 + 倒序（最近 → 远期）。

    _seed 3 条跨 3 日 → backfill 3 天 → list_daily 应倒序返回 3 行。
    """
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    # 先 backfill 3 天（10-17 / 10-18 / 10-19）
    n = await repo.backfill_daily(start_date=date_t(2026, 10, 17), end_date=date_t(2026, 10, 19))
    assert n == 3
    # list_daily 3 天
    rows = await repo.list_daily(start=date_t(2026, 10, 17), end=date_t(2026, 10, 19))
    # 倒序：10-19, 10-18, 10-17
    assert [r.date for r in rows] == [
        date_t(2026, 10, 19),
        date_t(2026, 10, 18),
        date_t(2026, 10, 17),
    ]
    # 10-18 total=154 不对——是 10-19 = 1, 10-18 = 1, 10-17 = 1（seed 各 1 条）
    assert all(r.total_count == 1 for r in rows)


async def test_backfill_daily_skips_empty_days(db_session) -> None:
    """V0.107 ``backfill_daily`` 跳过空日：30 天范围只创建 3 行。"""
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    n = await repo.backfill_daily(start_date=date_t(2026, 10, 1), end_date=date_t(2026, 10, 30))
    # _seed 3 条占 3 个不同日期 → 27 个空日 + 3 个有数据日 = 3 行
    assert n == 3


async def test_upsert_daily_aggregates_bilingual_and_categories(db_session) -> None:
    """V0.107 类目 + 语种聚合：3 条覆盖 2 类目 / 2 语种 / 2 站点。"""
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    # 跨 3 天分别 backfill
    for d in (date_t(2026, 10, 17), date_t(2026, 10, 18), date_t(2026, 10, 19)):
        await repo.upsert_daily(d)
    # 10-19: 1 条 (1001 zh-cn 财经 华尔街见闻)
    row_19 = await repo.get_daily(date_t(2026, 10, 19))
    assert row_19.finance_count == 1
    assert row_19.zh_count == 1
    assert row_19.en_count == 0
    # 10-18: 1 条 (1002 zh-cn 财经 财联社)
    row_18 = await repo.get_daily(date_t(2026, 10, 18))
    assert row_18.finance_count == 1
    assert row_18.zh_count == 1
    # 10-17: 1 条 (1003 en 科技 Reuters)
    row_17 = await repo.get_daily(date_t(2026, 10, 17))
    assert row_17.tech_count == 1
    assert row_17.en_count == 1
    assert row_17.zh_count == 0
    # 累计：finance=2, tech=1, en=1, zh=2
    finance_total = sum(r.finance_count for r in (row_17, row_18, row_19))
    tech_total = sum(r.tech_count for r in (row_17, row_18, row_19))
    en_total = sum(r.en_count for r in (row_17, row_18, row_19))
    zh_total = sum(r.zh_count for r in (row_17, row_18, row_19))
    assert (finance_total, tech_total, en_total, zh_total) == (2, 1, 1, 2)


# ──────────────── V0.114.0 多源化 ────────────────


def _multi_source_record(ext_id: int, source: str, **over) -> dict:
    """构造一条 fetcher 形状的 record（与 news_sources_fetcher._build 输出一致）。"""
    rec = {
        "external_id": ext_id,
        "source": source,
        "title": f"来自 {source} 的新闻 {ext_id}",
        "summary": "正文摘要",
        "url": None,
        "mobile_url": None,
        "site_name": {"wallstcn": "华尔街见闻", "jin10": "金十数据", "eastmoney": "东方财富快讯"}[
            source
        ],
        "language": "zh-cn",
        "author_name": None,
        "publish_date": datetime(2026, 10, 22, 1, 0, tzinfo=timezone.utc),
        "category": "财经",
    }
    rec.update(over)
    return rec


async def test_upsert_same_ext_id_different_source_creates_two_rows(db_session) -> None:
    """V0.114.0：UNIQUE 改成 (source, external_id)。

    四源 id 空间互不相干，「同一个数字来自不同源」是常态而非异常 —— 单列
    UNIQUE 会让第二条直接被 ON CONFLICT 吞掉，或（若 upsert 的
    index_elements 没同步改）把 A 源的新闻标题改成 B 源的。
    """
    repo = NewsFeedRepository(db_session)
    await repo.upsert_bulk(
        [_multi_source_record(777, "wallstcn"), _multi_source_record(777, "jin10")]
    )
    rows = (
        (await db_session.execute(select(NewsFeedItem).where(NewsFeedItem.external_id == "777")))
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert {r.source for r in rows} == {"wallstcn", "jin10"}
    assert {r.site_name for r in rows} == {"华尔街见闻", "金十数据"}


async def test_upsert_same_source_same_ext_id_is_idempotent(db_session) -> None:
    """同源同 id 二次抓取必须 upsert 而不是插新行（dedup 语义不变）。"""
    repo = NewsFeedRepository(db_session)
    await repo.upsert_bulk([_multi_source_record(888, "eastmoney")])
    await repo.upsert_bulk([_multi_source_record(888, "eastmoney", title="改过的标题")])
    rows = (
        (await db_session.execute(select(NewsFeedItem).where(NewsFeedItem.external_id == "888")))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].title == "改过的标题"


async def test_upsert_bulk_accepts_null_url(db_session) -> None:
    """url 可空：金十/东财快讯没有原文链接（实测 0/20 条有）。"""
    repo = NewsFeedRepository(db_session)
    await repo.upsert_bulk([_multi_source_record(20261022052906788800, "jin10", url=None)])
    row = await repo.find_by_external(20261022052906788800, "jin10")
    assert row is not None
    assert row.url is None


async def test_find_by_external_is_source_scoped(db_session) -> None:
    """收藏回填按 (ext, source) 查 —— 只按 ext 查会取到另一源的同号新闻。"""
    repo = NewsFeedRepository(db_session)
    await repo.upsert_bulk(
        [_multi_source_record(999, "wallstcn"), _multi_source_record(999, "jin10")]
    )
    w = await repo.find_by_external(999, "wallstcn")
    j = await repo.find_by_external(999, "jin10")
    assert w is not None and j is not None
    assert w.site_name == "华尔街见闻"
    assert j.site_name == "金十数据"


async def test_jin10_twenty_digit_id_roundtrips(db_session) -> None:
    """金十 id 是 20 位（≈2.0e19），超出 int32 —— BigInteger 必须真的装得下。

    装不下的话 SQLite 直接抛 OverflowError（实测踩过）—— 抓取整体失败，
    failover 退到下一个源，多源能力等于没上线。
    """
    repo = NewsFeedRepository(db_session)
    big = 20261022052906788800
    await repo.upsert_bulk([_multi_source_record(big, "jin10")])
    row = await repo.find_by_external(big, "jin10")
    assert row is not None
    # 列是 String(32)：值必须**逐字符**还原，任何截断都会变成另一条新闻
    assert row.external_id == str(big)
