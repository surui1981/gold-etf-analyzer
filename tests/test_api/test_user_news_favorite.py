"""用户新闻收藏 REST 端点 单测（V0.103）

覆盖：
- GET    /items                       列表 + 5 维筛选 + 排序 + 分页
- GET    /items/{id}                  单条
- GET    /sites                       distinct 来源站
- GET    /tags                        distinct tag
- GET    /stats                       6 维聚合
- GET    /exists/{external_id}        幂等检查（UI 按钮态）
- POST   /items                       新增 + UNIQUE 重复 → 409
- PATCH  /items/{id}                  局部更新
- DELETE /items/{id}                  取消

单用户模式：AUTH_ENABLED=false → LEGACY_USER 零配置（V0.97.0 hotfix）
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.news_feed import NewsFeedItem
from app.models.user import LEGACY_USER_ID, ROLE_OWNER, User
from app.models.user_news_favorite import UserNewsFavorite

# ──────────────── autouse fixture：seed LEGACY_USER ────────────────


@pytest.fixture(autouse=True)
async def _seed_legacy(db_session) -> None:
    """每个用例前确保 LEGACY_USER(id=1) 存在 —— 单用户模式 ``require_user`` 兜底依赖。"""
    await _ensure_legacy_user(db_session)


# ──────────────── 公共 seed helpers ────────────────


async def _ensure_legacy_user(db) -> None:
    """conftest 每个用例前 drop_all → LEGACY_USER 不存在 → 手动建 1 行。

    POST / PATCH / DELETE 走 ``Depends(require_user)`` → 单用户模式（auth_enabled=False）
    回退到 LEGACY_USER（id=1）。DB 无该行时回退返回 None → 401。
    显式建行可避免 401。
    """
    from sqlalchemy import select

    existing = (
        await db.execute(select(User).where(User.id == LEGACY_USER_ID))
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            User(
                id=LEGACY_USER_ID,
                email="legacy@test",
                display_name="Legacy",
                password_hash="x",
                role=ROLE_OWNER,
                is_active=True,
                created_at=datetime(2026, 1, 1),
                last_login_at=datetime(2026, 1, 1),
            )
        )
        await db.commit()


async def _seed_news_feed(db) -> NewsFeedItem:
    """在 news_feed_items 插 1 条；POST favorites 时可走 service 端 snapshot 回填。"""
    item = NewsFeedItem(
        external_id=50001,
        title="美联储 11 月暂停加息",
        summary="联储内部讨论",
        url="https://wallstreetcn.com/a/50001",
        mobile_url=None,
        site_name="华尔街见闻",
        language="zh-cn",
        author_name="张三",
        publish_date=datetime(2026, 10, 19, 0, 30, tzinfo=timezone.utc),
        source="readhub",
    )
    db.add(item)
    await db.commit()
    return item


async def _seed_fav(db, **overrides) -> UserNewsFavorite:
    """直接 ORM 插一条 user_news_favorite。"""
    base = {
        "news_external_id": 60001,
        "news_source": "readhub",
        "title": "默认标题",
        "summary": "默认摘要",
        "url": "https://x.com/a/60001",
        "mobile_url": None,
        "site_name": "默认站",
        "language": "zh-cn",
        "author_name": None,
        "publish_date": datetime(2026, 10, 18, tzinfo=timezone.utc),
        "user_tags": "[]",
        "user_note": "",
        "importance": 1,
    }
    base.update(overrides)
    obj = UserNewsFavorite(**base)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


# ──────────────── GET /items 列表 ────────────────


async def test_list_items_empty(client) -> None:
    """无任何收藏 → 200 + 空 items。"""
    r = await client.get("/api/v1/favorites/items")
    assert r.status_code == 200
    data = r.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["limit"] >= 1
    assert data["offset"] == 0


async def test_list_items_default(client, db_session) -> None:
    """3 条全部返回。"""
    await _seed_fav(db_session, news_external_id=70001, title="A")
    await _seed_fav(db_session, news_external_id=70002, title="B")
    await _seed_fav(db_session, news_external_id=70003, title="C")
    r = await client.get("/api/v1/favorites/items")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 3
    assert len(data["items"]) == 3


async def test_list_items_filter_importance_min(client, db_session) -> None:
    await _seed_fav(db_session, news_external_id=71001, importance=1)
    await _seed_fav(db_session, news_external_id=71002, importance=2)
    await _seed_fav(db_session, news_external_id=71003, importance=3)
    r = await client.get("/api/v1/favorites/items?importance_min=2")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    assert {it["importance"] for it in data["items"]} == {2, 3}


async def test_list_items_filter_tag(client, db_session) -> None:
    await _seed_fav(
        db_session,
        news_external_id=72001,
        user_tags='["美联储","美元"]',
    )
    await _seed_fav(db_session, news_external_id=72002, user_tags='["地缘"]')
    r = await client.get("/api/v1/favorites/items?tag=美联储")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert "美联储" in data["items"][0]["user_tags"]


async def test_list_items_filter_site(client, db_session) -> None:
    await _seed_fav(db_session, news_external_id=73001, site_name="华尔街见闻")
    await _seed_fav(db_session, news_external_id=73002, site_name="财联社")
    r = await client.get("/api/v1/favorites/items?site_name=财联社")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["site_name"] == "财联社"


async def test_list_items_sort_importance(client, db_session) -> None:
    await _seed_fav(db_session, news_external_id=74001, importance=1)
    await _seed_fav(db_session, news_external_id=74002, importance=3)
    r = await client.get("/api/v1/favorites/items?sort=importance")
    assert r.status_code == 200
    items = r.json()["items"]
    assert items[0]["importance"] == 3
    assert items[1]["importance"] == 1


async def test_list_items_pagination(client, db_session) -> None:
    for i in range(5):
        await _seed_fav(
            db_session,
            news_external_id=75000 + i,
            title=f"item-{i}",
        )
    r = await client.get("/api/v1/favorites/items?limit=2&offset=0")
    data = r.json()
    assert data["total"] == 5
    assert len(data["items"]) == 2
    assert data["limit"] == 2
    assert data["offset"] == 0


# ──────────────── GET /items/{id} 单条 ────────────────


async def test_get_item_by_id(client, db_session) -> None:
    fav = await _seed_fav(
        db_session,
        news_external_id=76001,
        title="某新闻",
        importance=2,
    )
    r = await client.get(f"/api/v1/favorites/items/{fav.id}")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == fav.id
    assert data["title"] == "某新闻"
    assert data["importance"] == 2


async def test_get_item_not_found(client) -> None:
    r = await client.get("/api/v1/favorites/items/99999")
    assert r.status_code == 404


# ──────────────── GET /sites / /tags / /stats / /exists ────────────────


async def test_list_sites(client, db_session) -> None:
    await _seed_fav(db_session, news_external_id=77001, site_name="华尔街见闻")
    await _seed_fav(db_session, news_external_id=77002, site_name="财联社")
    r = await client.get("/api/v1/favorites/sites")
    assert r.status_code == 200
    sites = r.json()
    assert "华尔街见闻" in sites
    assert "财联社" in sites


async def test_list_tags(client, db_session) -> None:
    await _seed_fav(db_session, news_external_id=78001, user_tags='["美联储","美元"]')
    await _seed_fav(db_session, news_external_id=78002, user_tags='["地缘"]')
    r = await client.get("/api/v1/favorites/tags")
    assert r.status_code == 200
    tags = r.json()
    assert "美联储" in tags
    assert "美元" in tags
    assert "地缘" in tags
    # 字母序
    assert tags == sorted(tags)


async def test_get_stats(client, db_session) -> None:
    await _seed_fav(
        db_session,
        news_external_id=79001,
        importance=1,
        user_tags="[]",
    )
    await _seed_fav(
        db_session,
        news_external_id=79002,
        importance=3,
        user_tags="[]",
    )
    r = await client.get("/api/v1/favorites/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    assert data["by_importance"] == {"1": 1, "3": 1}


async def test_exists_returns_fav_or_null(client, db_session) -> None:
    """GET /exists/{ext} → 命中返回 fav JSON；未命中 → 200 + null（UI 据此切 ⭐/☆）。"""
    await _seed_fav(db_session, news_external_id=80001, news_source="readhub")
    # 命中
    r1 = await client.get("/api/v1/favorites/exists/80001?source=readhub")
    assert r1.status_code == 200
    data = r1.json()
    assert data is not None
    assert data["news_external_id"] == 80001
    # 未命中：200 + null（不 404，UI 按钮态切换用，null = 未收藏）
    r2 = await client.get("/api/v1/favorites/exists/99999?source=readhub")
    assert r2.status_code == 200
    assert r2.json() is None


# ──────────────── POST /items 收藏 ────────────────


async def test_post_uses_news_feed_snapshot(client, db_session) -> None:
    """POST 时若 news_feed_items 命中 → service 自动用源表当前字段回填快照。"""
    await _seed_news_feed(db_session)
    r = await client.post(
        "/api/v1/favorites/items",
        json={"news_external_id": 50001},
    )
    assert r.status_code == 201
    data = r.json()
    assert data["news_external_id"] == 50001
    # source 表回填 → 标题/URL/来源站
    assert data["title"] == "美联储 11 月暂停加息"
    assert data["url"] == "https://wallstreetcn.com/a/50001"
    assert data["site_name"] == "华尔街见闻"
    assert data["author_name"] == "张三"


async def test_post_direct_snapshot_when_no_feed_row(client, db_session) -> None:
    """news_feed_items 没命中 → 客户端直接传 snapshot。"""
    r = await client.post(
        "/api/v1/favorites/items",
        json={
            "news_external_id": 90001,
            "title": "外部直传",
            "url": "https://external.com/a",
            "site_name": "外部站",
            "publish_date": "2026-10-19T00:00:00Z",
            "user_tags": ["美元", "黄金"],
            "user_note": "我的笔记",
            "importance": 2,
        },
    )
    assert r.status_code == 201
    data = r.json()
    assert data["title"] == "外部直传"
    # Python sorted 用 Unicode 码点序 → "美"(U+7F8E) < "黄"(U+9EC4)
    assert data["user_tags"] == ["美元", "黄金"]  # 已按 normalize_tags 排序
    assert data["user_note"] == "我的笔记"
    assert data["importance"] == 2


async def test_post_duplicate_returns_409(client, db_session) -> None:
    """同一 (external_id, source) 第二次 POST → 409 Conflict。"""
    await _seed_news_feed(db_session)
    r1 = await client.post("/api/v1/favorites/items", json={"news_external_id": 50001})
    assert r1.status_code == 201
    # 第二次（先 delete news_feed_items row 强制走 direct snapshot 路径不行；
    # 重复 POST 直接对 UNIQUE 约束 → 409）
    r2 = await client.post("/api/v1/favorites/items", json={"news_external_id": 50001})
    assert r2.status_code == 409


async def test_post_invalid_importance_rejected(client) -> None:
    """importance=4 (超出 1-3) → 422。"""
    r = await client.post(
        "/api/v1/favorites/items",
        json={
            "news_external_id": 91001,
            "title": "t",
            "url": "https://x.com",
            "site_name": "x",
            "publish_date": "2026-10-19T00:00:00Z",
            "importance": 4,
        },
    )
    assert r.status_code == 422


# ──────────────── PATCH /items/{id} 局部更新 ────────────────


async def test_patch_importance(client, db_session) -> None:
    fav = await _seed_fav(db_session, news_external_id=92001, importance=1)
    r = await client.patch(f"/api/v1/favorites/items/{fav.id}", json={"importance": 3})
    assert r.status_code == 200
    data = r.json()
    assert data["importance"] == 3
    # 其它字段不变
    assert data["title"] == "默认标题"


async def test_patch_user_tags_normalized(client, db_session) -> None:
    """tag 列表写入前会自动去重 + 字母序排序。"""
    fav = await _seed_fav(db_session, news_external_id=92002, user_tags="[]")
    r = await client.patch(
        f"/api/v1/favorites/items/{fav.id}",
        json={"user_tags": ["美元", "美联储", "美元", "地缘"]},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["user_tags"] == ["地缘", "美元", "美联储"]


async def test_patch_unknown_id_returns_404(client) -> None:
    r = await client.patch("/api/v1/favorites/items/99999", json={"importance": 3})
    assert r.status_code == 404


# ──────────────── DELETE /items/{id} 取消收藏 ────────────────


async def test_delete_item(client, db_session) -> None:
    fav = await _seed_fav(db_session, news_external_id=93001)
    r = await client.delete(f"/api/v1/favorites/items/{fav.id}")
    assert r.status_code == 204
    # 再 GET 不存在
    r2 = await client.get(f"/api/v1/favorites/items/{fav.id}")
    assert r2.status_code == 404


async def test_delete_unknown_id_returns_404(client) -> None:
    r = await client.delete("/api/v1/favorites/items/99999")
    assert r.status_code == 404
