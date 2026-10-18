"""今日要闻 REST 端点 单测（V0.102）"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from app.models.news_feed import NewsFeedItem


# ──────────────── 公共 fixture：DB seed ────────────────


async def _seed(db) -> None:  # noqa: ANN001
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
            category="科技",
        ),
    ]
    for r in rows:
        db.add(r)
    await db.commit()


# ──────────────── 列表 / 筛选 ────────────────


async def test_list_items_default(client, db_session) -> None:  # noqa: ANN001
    """GET /items 不带参数 → 全量（按 publish_date 倒序）。"""
    await _seed(db_session)
    r = await client.get("/api/v1/news-feed/items")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 3
    assert len(data["items"]) == 3
    # 倒序：1001（10-19） > 1002（10-18） > 1003（10-17）
    assert [it["external_id"] for it in data["items"]] == [1001, 1002, 1003]


async def test_list_items_filter_days(client, db_session) -> None:  # noqa: ANN001
    """``days=1`` → 仅 10-18 / 10-19 两条（10-17 被 cutoff 过滤）。

    seed 3 条：10-19 / 10-18 / 10-17（与「今天」相对）；cutoff = now - 1d，
    10-17 < cutoff 被排除。
    """
    await _seed(db_session)
    r = await client.get("/api/v1/news-feed/items?days=1")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    assert all(it["external_id"] in (1001, 1002) for it in data["items"])


async def test_list_items_filter_site(client, db_session) -> None:  # noqa: ANN001
    """``site_name=财联社`` → 仅 1 条。"""
    await _seed(db_session)
    r = await client.get("/api/v1/news-feed/items?site_name=财联社")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["external_id"] == 1002


async def test_list_items_filter_language(client, db_session) -> None:  # noqa: ANN001
    """``language=en`` → 仅 Reuters 1 条。"""
    await _seed(db_session)
    r = await client.get("/api/v1/news-feed/items?language=en")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["site_name"] == "Reuters"


async def test_list_items_limit(client, db_session) -> None:  # noqa: ANN001
    """``limit=1`` → 仅 1 条。"""
    await _seed(db_session)
    r = await client.get("/api/v1/news-feed/items?limit=1")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1


async def test_list_items_invalid_days_returns_422(client) -> None:  # noqa: ANN001
    """``days=0`` 违反 ge=1 → 422。"""
    r = await client.get("/api/v1/news-feed/items?days=0")
    assert r.status_code == 422


# ──────────────── V0.104 · 单日模式 ────────────────


async def test_list_items_by_date_returns_only_that_day(client, db_session) -> None:  # noqa: ANN001
    """V0.104 ``date=2026-10-18&tz_offset_minutes=0`` → 仅 1002（10-18 UTC）。

    seed 3 条：1001(10-19 00:30 UTC) / 1002(10-18 08:00 UTC) / 1003(10-17 14:00 UTC)。
    date 模式 + tz=0 → [10-18 00:00 UTC, 10-19 00:00 UTC) 半开 → 命中 1002。
    """
    from datetime import date as date_t

    await _seed(db_session)
    r = await client.get(
        "/api/v1/news-feed/items",
        params={"date": "2026-10-18", "tz_offset_minutes": 0},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["external_id"] == 1002
    assert data["current_date"] == "2026-10-18"
    # 10-19 在 day_end 之后，10-17 在 day_start 之前 → 都 True
    assert data["has_older"] is True
    assert data["has_newer"] is True


async def test_list_items_date_with_tz_offset_shifts_boundary(client, db_session) -> None:  # noqa: ANN001
    """V0.104 时区偏移：date=2026-10-18 + tz=+480 (BJT) 命中 10-18 BJT 当天。

    1001 是 10-19 00:30 UTC = 10-19 08:30 BJT（不在 10-18 当天）
    1002 是 10-18 08:00 UTC = 10-18 16:00 BJT（10-18 当天 ✅）
    1003 是 10-17 14:00 UTC = 10-17 22:00 BJT（不在 10-18 当天）
    """
    from datetime import date as date_t

    await _seed(db_session)
    r = await client.get(
        "/api/v1/news-feed/items",
        params={"date": "2026-10-18", "tz_offset_minutes": 480},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["external_id"] == 1002
    # BJT 10-18 之前还有 10-17（更早）= has_older True
    # BJT 10-18 之后还有 10-19 08:30 BJT（更新）= has_newer True
    assert data["has_older"] is True
    assert data["has_newer"] is True


async def test_list_items_date_no_neighbours(client, db_session) -> None:  # noqa: ANN001
    """V0.104 单日模式：选择最新一天（10-19）→ has_older=True, has_newer=False。

    seed 中 10-19 是最新，没有更新的 → has_newer=False。
    """
    await _seed(db_session)
    r = await client.get(
        "/api/v1/news-feed/items",
        params={"date": "2026-10-19", "tz_offset_minutes": 0},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["external_id"] == 1001
    assert data["has_older"] is True
    assert data["has_newer"] is False


async def test_list_items_date_empty_day(client, db_session) -> None:  # noqa: ANN001
    """V0.104 单日模式：选一个没有数据的日期 → total=0 + has_older/has_newer 都 True。"""
    await _seed(db_session)
    r = await client.get(
        "/api/v1/news-feed/items",
        params={"date": "2026-10-15", "tz_offset_minutes": 0},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["items"] == []
    assert data["current_date"] == "2026-10-15"
    # 10-15 之前（10-17/18/19 都在之后）→ has_older=False（更早没有）
    # 10-15 之后有 10-17/18/19 → has_newer=True
    assert data["has_older"] is False
    assert data["has_newer"] is True


async def test_list_items_days_mode_has_no_date_fields(client, db_session) -> None:  # noqa: ANN001
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


async def test_list_items_invalid_date_returns_422(client) -> None:  # noqa: ANN001
    """V0.104 ``date=not-a-date`` → 422（FastAPI 自动按 date 解析）。"""
    r = await client.get("/api/v1/news-feed/items?date=not-a-date")
    assert r.status_code == 422


# ──────────────── sites / languages ────────────────


async def test_list_sites(client, db_session) -> None:  # noqa: ANN001
    """GET /sites → 出现过的来源站（去重，频次降序）。"""
    await _seed(db_session)
    r = await client.get("/api/v1/news-feed/sites")
    assert r.status_code == 200
    sites = r.json()
    # 3 条不同来源
    assert sorted(sites) == ["Reuters", "华尔街见闻", "财联社"]


async def test_list_languages(client, db_session) -> None:  # noqa: ANN001
    """GET /languages → 出现过的语种（去重 + 字典序）。"""
    await _seed(db_session)
    r = await client.get("/api/v1/news-feed/languages")
    assert r.status_code == 200
    langs = r.json()
    assert langs == ["en", "zh-cn"]


# ──────────────── status ────────────────


async def test_get_status_empty(client, db_session) -> None:  # noqa: ANN001
    """DB 空 → last_refresh_at=None + 0/0。"""
    r = await client.get("/api/v1/news-feed/status")
    assert r.status_code == 200
    data = r.json()
    assert data["last_refresh_at"] is None
    assert data["total_items"] == 0
    assert data["last_24h_count"] == 0


async def test_get_status_with_data(client, db_session) -> None:  # noqa: ANN001
    """DB 有数据 → total=3, last_refresh_at 填 ISO。"""
    await _seed(db_session)
    r = await client.get("/api/v1/news-feed/status")
    assert r.status_code == 200
    data = r.json()
    assert data["total_items"] == 3
    assert data["last_refresh_at"] is not None


# ──────────────── refresh（admin 守卫）──


async def test_refresh_no_auth_in_single_user_mode(client, monkeypatch) -> None:  # noqa: ANN001
    """单用户模式（auth_enabled=false）下 refresh 端点直接放行（admin 豁免）。

    注：单测 conftest 已设 ``AUTH_ENABLED`` 未设 → auth_enabled=false；
    monkeypatch ``fetch_readhub_feed`` 走 mock，不连真实网络。
    """
    from app.repositories import readhub_fetcher as rh

    sample = [{
        "id": 9999,
        "title": "test news",
        "summary": "summary",
        "url": "https://example.com/9999",
        "mobileUrl": "",
        "siteName": "test-site",
        "language": "zh-cn",
        "authorName": "tester",
        "publishDate": "2026-10-19T08:00:00+08:00",
    }]

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


async def test_root_redirect_to_headlines(client) -> None:  # noqa: ANN001
    """GET /headlines → 307 重定向到 /static/headlines.html。"""
    r = await client.get("/headlines", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/static/headlines.html"


# ──────────────── V0.105 · 类目筛选 ────────────────


async def test_list_items_filter_category(client, db_session) -> None:  # noqa: ANN001
    """V0.105 ``?category=财经`` → 仅 1001 / 1002（1003 是「科技」）。"""
    await _seed(db_session)
    r = await client.get("/api/v1/news-feed/items?category=财经")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    assert sorted([it["external_id"] for it in data["items"]]) == [1001, 1002]
    # 响应里每条都带 category 字段
    assert all(it["category"] == "财经" for it in data["items"])


async def test_list_items_invalid_category_returns_422(client) -> None:  # noqa: ANN001
    """V0.105 ``?category=超过 16 字符的无效字符串`` → 422（max_length=16）。"""
    r = await client.get(
        "/api/v1/news-feed/items",
        params={"category": "x" * 17},
    )
    assert r.status_code == 422


async def test_list_items_category_combined_with_date(client, db_session) -> None:  # noqa: ANN001
    """V0.105 × V0.104 联动：date + category 正交叠加。

    date=2026-10-18 + category=科技 → 0 条（10-18 当天 1002 是财经）
    date=2026-10-18 + category=财经 → 1 条（1002）
    """
    await _seed(db_session)
    r1 = await client.get(
        "/api/v1/news-feed/items",
        params={"date": "2026-10-18", "tz_offset_minutes": 0, "category": "科技"},
    )
    assert r1.status_code == 200
    assert r1.json()["total"] == 0

    r2 = await client.get(
        "/api/v1/news-feed/items",
        params={"date": "2026-10-18", "tz_offset_minutes": 0, "category": "财经"},
    )
    assert r2.status_code == 200
    assert r2.json()["total"] == 1
    assert r2.json()["items"][0]["external_id"] == 1002


async def test_list_items_category_orthogonal_to_days(client, db_session) -> None:  # noqa: ANN001
    """V0.105 ``days=90 + category=科技`` → 仅 1003。"""
    await _seed(db_session)
    r = await client.get("/api/v1/news-feed/items?days=90&category=科技")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["external_id"] == 1003


async def test_list_categories_endpoint(client, db_session) -> None:  # noqa: ANN001
    """V0.105 ``GET /api/v1/news-feed/categories`` → 频次降序：财经(2) > 科技(1)。"""
    await _seed(db_session)
    r = await client.get("/api/v1/news-feed/categories")
    assert r.status_code == 200
    cats = r.json()
    assert cats == ["财经", "科技"]


async def test_list_items_includes_category_field(client, db_session) -> None:  # noqa: ANN001
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
