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
