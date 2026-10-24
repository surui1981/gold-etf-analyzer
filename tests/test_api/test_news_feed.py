"""今日要闻 REST 端点 单测（V0.102 / V0.105 类目 / V0.107 按日聚合）"""

from __future__ import annotations

from datetime import date as date_t
from datetime import datetime, time, timedelta, timezone

import pytest

from app.models.news_feed import NewsFeedItem
from app.repositories.news_feed import NewsFeedRepository
from app.repositories.news_sources_fetcher import NewsFetchResult

# ──────────────── 公共 fixture：DB seed ────────────────
#
# ⚠ **seed 日期锚定在「今天（UTC）」，不写死绝对日期**（V0.116.1 修 CI 预存红）
#
# 写死 `2026-10-19` 这类常量会**随日历腐烂**：``list_items(days=N)`` 的 cutoff 是
# ``datetime.now(timezone.utc) - timedelta(days=N)``（相对当下），
# 而 seed 是绝对日期 —— 两者一旦拉开距离，``days=1`` 就返回 0 条，
# 用例断言 ``total == 2`` 直接变红（V0.116.1 修的就是这个）。
#
# 三个日期刻意落在**三个不同的 UTC 日**（今天 / 昨天 / 3 天前），
# date 模式（含 tz 偏移）的用例才能验证「某一天只命中某一条」。
# 时刻统一取 **12:00 UTC** —— 距 UTC 日界 12 小时，
# 跨午夜运行时 ``days`` 边界仍有余量（不会因为差几分钟就翻转）。
_TODAY = datetime.now(timezone.utc).date()
_D0 = _TODAY  # 1001：今天 12:00 UTC
_D1 = _TODAY - timedelta(days=1)  # 1002：昨天 12:00 UTC
_D2 = _TODAY - timedelta(days=3)  # 1003：3 天前 12:00 UTC
_D_EMPTY = _TODAY - timedelta(days=4)  # 早于全部 seed 的空日


def _at_noon(d: date_t) -> datetime:
    """把某个 UTC 日期锚到当天 12:00（tz-aware UTC）。"""
    return datetime.combine(d, time(12, 0), tzinfo=timezone.utc)


async def _seed(db) -> None:
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
            publish_date=_at_noon(_D0),
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
            publish_date=_at_noon(_D1),
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
            publish_date=_at_noon(_D2),
            source="readhub",
            category="科技",
        ),
    ]
    for r in rows:
        db.add(r)
    await db.commit()


# ──────────────── 列表 / 筛选 ────────────────


async def test_list_items_default(client, db_session) -> None:
    """GET /items 不带参数 → 全量（按 publish_date 倒序）。"""
    await _seed(db_session)
    r = await client.get("/api/v1/news-feed/items")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 3
    assert len(data["items"]) == 3
    # 倒序：1001（10-19） > 1002（10-18） > 1003（10-17）
    assert [it["external_id"] for it in data["items"]] == [1001, 1002, 1003]


async def test_list_items_filter_days(client, db_session) -> None:
    """``days=2`` → 仅今天 / 昨天两条（3 天前那条被 cutoff 过滤）。

    seed 3 条：今天 / 昨天 / 3 天前（均 12:00 UTC）；cutoff = now - 2d，
    3 天前那条 < cutoff 被排除。

    ⚠ 用 ``days=2`` 而不是 ``days=1``：cutoff 是**相对当下**的
    ``now - timedelta(days=days)``，而「昨天 12:00」与 ``now - 24h``
    只差几个小时 —— 凌晨跑（now 的时刻 < 12:00）就会把「昨天那条」也切掉。
    ``days=2`` 留出 12 小时余量，**任何时刻跑结果都一样**。
    """
    await _seed(db_session)
    r = await client.get("/api/v1/news-feed/items?days=2")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    assert all(it["external_id"] in (1001, 1002) for it in data["items"])


async def test_list_items_filter_site(client, db_session) -> None:
    """``site_name=财联社`` → 仅 1 条。"""
    await _seed(db_session)
    r = await client.get("/api/v1/news-feed/items?site_name=财联社")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["external_id"] == 1002


async def test_list_items_filter_language(client, db_session) -> None:
    """``language=en`` → 仅 Reuters 1 条。"""
    await _seed(db_session)
    r = await client.get("/api/v1/news-feed/items?language=en")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["site_name"] == "Reuters"


async def test_list_items_limit(client, db_session) -> None:
    """``limit=1`` → 仅 1 条。"""
    await _seed(db_session)
    r = await client.get("/api/v1/news-feed/items?limit=1")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1


async def test_list_items_invalid_days_returns_422(client) -> None:
    """``days=0`` 违反 ge=1 → 422。"""
    r = await client.get("/api/v1/news-feed/items?days=0")
    assert r.status_code == 422


# ──────────────── V0.104 · 单日模式 ────────────────


async def test_list_items_by_date_returns_only_that_day(client, db_session) -> None:
    """V0.104 ``date=昨天&tz_offset_minutes=0`` → 仅 1002（昨天 UTC）。

    seed 3 条：1001(今天 12:00 UTC) / 1002(昨天 12:00 UTC) / 1003(3 天前 12:00 UTC)。
    date 模式 + tz=0 → [昨天 00:00 UTC, 今天 00:00 UTC) 半开 → 命中 1002。
    """
    await _seed(db_session)
    r = await client.get(
        "/api/v1/news-feed/items",
        params={"date": _D1.isoformat(), "tz_offset_minutes": 0},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["external_id"] == 1002
    assert data["current_date"] == _D1.isoformat()
    # 今天在 day_end 之后，3 天前在 day_start 之前 → 都 True
    assert data["has_older"] is True
    assert data["has_newer"] is True


async def test_list_items_date_with_tz_offset_shifts_boundary(client, db_session) -> None:
    """V0.104 时区偏移：date=昨天 + tz=+480 (BJT) 命中昨天 BJT 当天。

    1001 是今天 12:00 UTC = 今天 20:00 BJT（不在昨天当天）
    1002 是昨天 12:00 UTC = 昨天 20:00 BJT（昨天当天 ✅）
    1003 是 3 天前 12:00 UTC = 3 天前 20:00 BJT（不在昨天当天）
    """
    await _seed(db_session)
    r = await client.get(
        "/api/v1/news-feed/items",
        params={"date": _D1.isoformat(), "tz_offset_minutes": 480},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["external_id"] == 1002
    # BJT 昨天之前还有 3 天前（更早）= has_older True
    # BJT 昨天之后还有今天 20:00 BJT（更新）= has_newer True
    assert data["has_older"] is True
    assert data["has_newer"] is True


async def test_list_items_date_no_neighbours(client, db_session) -> None:
    """V0.104 单日模式：选择最新一天（今天）→ has_older=True, has_newer=False。

    seed 中今天是最新，没有更新的 → has_newer=False。
    """
    await _seed(db_session)
    r = await client.get(
        "/api/v1/news-feed/items",
        params={"date": _D0.isoformat(), "tz_offset_minutes": 0},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["external_id"] == 1001
    assert data["has_older"] is True
    assert data["has_newer"] is False


async def test_list_items_date_empty_day(client, db_session) -> None:
    """V0.104 单日模式：选一个没有数据的日期 → total=0 + has_older/has_newer 都 True。"""
    await _seed(db_session)
    r = await client.get(
        "/api/v1/news-feed/items",
        params={"date": _D_EMPTY.isoformat(), "tz_offset_minutes": 0},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["items"] == []
    assert data["current_date"] == _D_EMPTY.isoformat()
    # 4 天前之前（3 天前 / 昨天 / 今天都在之后）→ has_older=False（更早没有）
    # 4 天前之后有 3 天前 / 昨天 / 今天 → has_newer=True
    assert data["has_older"] is False
    assert data["has_newer"] is True


async def test_list_items_days_mode_has_no_date_fields(client, db_session) -> None:
    """V0.104 days 模式：响应里 current_date=None, has_older/has_newer=False。

    回归保护：确保 days 模式不受 date 模式字段污染。
    """
    await _seed(db_session)
    r = await client.get("/api/v1/news-feed/items?days=7")
    assert r.status_code == 200
    data = r.json()
    assert data["current_date"] is None
    assert data["has_older"] is False
    assert data["has_newer"] is False


async def test_list_items_invalid_date_returns_422(client) -> None:
    """V0.104 ``date=not-a-date`` → 422（FastAPI 自动按 date 解析）。"""
    r = await client.get("/api/v1/news-feed/items?date=not-a-date")
    assert r.status_code == 422


# ──────────────── sites / languages ────────────────


async def test_list_sites(client, db_session) -> None:
    """GET /sites → 出现过的来源站（去重，频次降序）。"""
    await _seed(db_session)
    r = await client.get("/api/v1/news-feed/sites")
    assert r.status_code == 200
    sites = r.json()
    # 3 条不同来源
    assert sorted(sites) == ["Reuters", "华尔街见闻", "财联社"]


async def test_list_languages(client, db_session) -> None:
    """GET /languages → 出现过的语种（去重 + 字典序）。"""
    await _seed(db_session)
    r = await client.get("/api/v1/news-feed/languages")
    assert r.status_code == 200
    langs = r.json()
    assert langs == ["en", "zh-cn"]


# ──────────────── status ────────────────


async def test_get_status_empty(client, db_session) -> None:
    """DB 空 → last_refresh_at=None + 0/0。"""
    r = await client.get("/api/v1/news-feed/status")
    assert r.status_code == 200
    data = r.json()
    assert data["last_refresh_at"] is None
    assert data["total_items"] == 0
    assert data["last_24h_count"] == 0


async def test_get_status_with_data(client, db_session) -> None:
    """DB 有数据 → total=3, last_refresh_at 填 ISO。"""
    await _seed(db_session)
    r = await client.get("/api/v1/news-feed/status")
    assert r.status_code == 200
    data = r.json()
    assert data["total_items"] == 3
    assert data["last_refresh_at"] is not None


# ──────────────── refresh（admin 守卫）──


async def test_refresh_no_auth_in_single_user_mode(client, monkeypatch) -> None:
    """单用户模式（auth_enabled=false）下 refresh 端点直接放行（admin 豁免）。

    注：单测 conftest 已设 ``AUTH_ENABLED`` 未设 → auth_enabled=false；
    monkeypatch ``fetch_readhub_feed`` 走 mock，不连真实网络。
    """
    from app.repositories import readhub_fetcher as rh

    sample = [
        {
            "id": 9999,
            "title": "test news",
            "summary": "summary",
            "url": "https://example.com/9999",
            "mobileUrl": "",
            "siteName": "test-site",
            "language": "zh-cn",
            "authorName": "tester",
            "publishDate": "2026-10-19T08:00:00+08:00",
        }
    ]

    async def _fake_fetch(*, page_size: int = 20, use_cache: bool = True) -> tuple:
        # normalize 一下
        return tuple(rh._normalize(r) for r in sample if rh._normalize(r))

    monkeypatch.setattr(rh, "fetch_readhub_feed", _fake_fetch)
    # clear cache 让 refresh 强制重抓（其实 mock 已用 _fake_fetch，但保险）
    with rh._CACHE_LOCK:
        rh._CACHE.clear()
    r = await client.post("/api/v1/news-feed/refresh")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["upserted"] >= 1
    assert data["error"] is None


# ──────────────── 重定向 alias ────────────────


async def test_root_redirect_to_headlines(client) -> None:
    """GET /headlines → 307 重定向到 /static/headlines.html。"""
    r = await client.get("/headlines", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/static/headlines.html"


# ──────────────── V0.105 · 类目筛选 ────────────────


async def test_list_items_filter_category(client, db_session) -> None:
    """V0.105 ``?category=财经`` → 仅 1001 / 1002（1003 是「科技」）。"""
    await _seed(db_session)
    r = await client.get("/api/v1/news-feed/items?category=财经")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    assert sorted([it["external_id"] for it in data["items"]]) == [1001, 1002]
    # 响应里每条都带 category 字段
    assert all(it["category"] == "财经" for it in data["items"])


async def test_list_items_invalid_category_returns_422(client) -> None:
    """V0.105 ``?category=超过 16 字符的无效字符串`` → 422（max_length=16）。"""
    r = await client.get(
        "/api/v1/news-feed/items",
        params={"category": "x" * 17},
    )
    assert r.status_code == 422


async def test_list_items_category_combined_with_date(client, db_session) -> None:
    """V0.105 × V0.104 联动：date + category 正交叠加。

    date=昨天 + category=科技 → 0 条（昨天只有 1002，是财经）
    date=昨天 + category=财经 → 1 条（1002）
    """
    await _seed(db_session)
    r1 = await client.get(
        "/api/v1/news-feed/items",
        params={"date": _D1.isoformat(), "tz_offset_minutes": 0, "category": "科技"},
    )
    assert r1.status_code == 200
    assert r1.json()["total"] == 0

    r2 = await client.get(
        "/api/v1/news-feed/items",
        params={"date": _D1.isoformat(), "tz_offset_minutes": 0, "category": "财经"},
    )
    assert r2.status_code == 200
    assert r2.json()["total"] == 1
    assert r2.json()["items"][0]["external_id"] == 1002


async def test_list_items_category_orthogonal_to_days(client, db_session) -> None:
    """V0.105 ``days=90 + category=科技`` → 仅 1003。"""
    await _seed(db_session)
    r = await client.get("/api/v1/news-feed/items?days=90&category=科技")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["external_id"] == 1003


async def test_list_categories_endpoint(client, db_session) -> None:
    """V0.105 ``GET /api/v1/news-feed/categories`` → 频次降序：财经(2) > 科技(1)。"""
    await _seed(db_session)
    r = await client.get("/api/v1/news-feed/categories")
    assert r.status_code == 200
    cats = r.json()
    assert cats == ["财经", "科技"]


async def test_list_items_includes_category_field(client, db_session) -> None:
    """V0.105 NewsFeedItemOut 增加 category 字段（回归：现有 items 字段不丢）。"""
    await _seed(db_session)
    r = await client.get("/api/v1/news-feed/items")
    assert r.status_code == 200
    data = r.json()
    # 3 条 items 都应有 category 字段
    for it in data["items"]:
        assert "category" in it
    # 倒序：1001(财经) > 1002(财经) > 1003(科技)
    assert data["items"][0]["category"] == "财经"
    assert data["items"][1]["category"] == "财经"
    assert data["items"][2]["category"] == "科技"


# ──────────────── V0.107 · 按日聚合 ────────────────


async def test_get_daily_returns_aggregate_for_seeded_day(client, db_session) -> None:
    """V0.107 ``GET /api/v1/news-feed/daily?date=今天``：返回当日聚合。

    seed 3 条跨 3 日（今天 / 昨天 / 3 天前），先 backfill 再查今天：
    - total=1（1001）
    - finance=1, tech=0
    - zh=1, en=0
    - unique_sites=1（华尔街见闻）

    ⚠ ``upsert_daily`` 的日界是 **BJT**（UTC+8），seed 的时刻是 12:00 UTC
    ⇒ 落在 BJT 当天 20:00，三天的聚合各只含 1 条（互不串日）。
    """
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    for d in (_D2, _D1, _D0):
        await repo.upsert_daily(d)

    r = await client.get(f"/api/v1/news-feed/daily?date={_D0.isoformat()}")
    assert r.status_code == 200
    data = r.json()
    assert data is not None
    assert data["date"] == _D0.isoformat()
    assert data["total_count"] == 1
    assert data["finance_count"] == 1
    assert data["tech_count"] == 0
    assert data["zh_count"] == 1
    assert data["en_count"] == 0
    assert data["unique_sites_count"] == 1
    # last_refresh_at 是 ISO 字符串
    assert "T" in data["last_refresh_at"]


async def test_get_daily_returns_null_for_empty_day(client, db_session) -> None:
    """V0.107 空日不创建行：``GET .../daily?date=<4 天前>`` → null。"""
    await _seed(db_session)
    r = await client.get(f"/api/v1/news-feed/daily?date={_D_EMPTY.isoformat()}")
    assert r.status_code == 200
    assert r.json() is None


async def test_list_daily_returns_range_in_desc_order(client, db_session) -> None:
    """V0.107 ``GET /api/v1/news-feed/daily/list?start=...&end=...``：闭区间 + 倒序。"""
    await _seed(db_session)
    repo = NewsFeedRepository(db_session)
    for d in (_D2, _D1, _D0):
        await repo.upsert_daily(d)

    r = await client.get(
        f"/api/v1/news-feed/daily/list?start={_D2.isoformat()}&end={_D0.isoformat()}"
    )
    assert r.status_code == 200
    data = r.json()
    # 3 条（空日不创建行）
    assert data["total"] == 3
    assert data["start"] == _D2.isoformat()
    assert data["end"] == _D0.isoformat()
    # 倒序：今天 → 昨天 → 3 天前
    assert [it["date"] for it in data["items"]] == [
        _D0.isoformat(),
        _D1.isoformat(),
        _D2.isoformat(),
    ]


async def test_list_daily_rejects_inverted_range(client) -> None:
    """V0.107 ``start > end`` → 400。"""
    r = await client.get("/api/v1/news-feed/daily/list?start=2026-10-19&end=2026-10-17")
    assert r.status_code == 400
    assert "start must be <= end" in r.json()["detail"]


async def test_list_daily_rejects_oversized_range(client) -> None:
    """V0.107 ``end - start > 90 天`` → 400。"""
    r = await client.get("/api/v1/news-feed/daily/list?start=2026-01-01&end=2026-12-31")
    assert r.status_code == 400
    assert "max 90 days" in r.json()["detail"]


async def test_get_daily_requires_date_param(client) -> None:
    """V0.107 ``GET .../daily`` 不带 date → 422（必填）。"""
    r = await client.get("/api/v1/news-feed/daily")
    assert r.status_code == 422


# ──────────────── V0.107.1 · 弃入「其他」+ page_size=50 ────────────────


async def test_list_items_category_other_returns_empty(client, db_session) -> None:
    """V0.107.1：fetcher 已弃入「其他」→ ``?category=其他`` 在新数据中无记录。

    行为不变（V0.105 已支持类目筛选）；V0.107.1 加固保证新写入的新闻
    不会带「其他」类目落到 items 端点。
    """
    await _seed(db_session)
    r = await client.get("/api/v1/news-feed/items?category=其他")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["items"] == []


async def test_list_items_after_v01071_refresh_excludes_other(
    client, db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """V0.107.1：模拟 refresh（mock fetcher）→ 4 类入「其他」不入 DB。

    Patch ``app.services.news_feed.fetch_readhub_feed`` 返 4 条 「财经」+ 2
    条 「其他」；调 refresh endpoint → 验证 DB 只 4 条 「财经」、0 条 「其他」。
    """
    from datetime import datetime, timezone

    from app.services import news_feed as svc_module

    finance_records = (
        {
            "external_id": 8001 + i,
            "title": f"美联储官员暗示 11 月 暂停加息-{i}",
            "summary": "通胀回落速度超预期",
            "url": f"https://wallstreetcn.com/articles/{8001 + i}",
            "mobile_url": None,
            "site_name": "华尔街见闻",
            "language": "zh-cn",
            "author_name": None,
            "publish_date": datetime(2026, 10, 19, 0, 30, tzinfo=timezone.utc),
            "category": "财经",
        }
        for i in range(4)
    )
    other_records = tuple(
        {
            "external_id": 8501 + i,
            "title": f"某地发生交通事故-{i}",
            "summary": "",
            "url": f"https://example.com/{8501 + i}",
            "mobile_url": None,
            "site_name": "地方日报",
            "language": "zh-cn",
            "author_name": None,
            "publish_date": datetime(2026, 10, 19, 0, 30, tzinfo=timezone.utc),
            "category": "其他",
        }
        for i in range(2)
    )

    async def _fake_fetch(**_kwargs):
        # V0.114.0：service 改调 fetch_news_feed，返回 NewsFetchResult(items, source)
        return NewsFetchResult(items=tuple(finance_records) + other_records, source="readhub")

    monkeypatch.setattr(svc_module, "fetch_news_feed", _fake_fetch)

    # 触发 refresh endpoint
    r = await client.post("/api/v1/news-feed/refresh")
    assert r.status_code == 200
    data = r.json()
    # 只 4 条「财经」入 DB
    assert data["ok"] is True
    assert data["upserted"] == 4

    # /items?category=其他 → 0 条（fetcher 已弃入 + service 二次 gate）
    r_other = await client.get("/api/v1/news-feed/items?category=其他")
    assert r_other.status_code == 200
    assert r_other.json()["total"] == 0

    # /items?category=财经 → 4 条
    r_fin = await client.get("/api/v1/news-feed/items?category=财经")
    assert r_fin.status_code == 200
    assert r_fin.json()["total"] == 4
