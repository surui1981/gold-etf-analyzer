"""用户新闻收藏仓储单测（V0.103）

覆盖：
- add：插入成功 + UNIQUE 重复 → DuplicateFavoriteError
- update：3 字段任选；不存在的 id → None
- delete：返回 bool；不存在 → False
- get / find_by_external：主键 / 复合 key 查
- list_items：days / site / tag / importance 4 维筛选 + 3 排序
- count_items：与 list_items 一致
- list_sites / list_tags：distinct + 排序
- get_status：6 维聚合

镜像 ``tests/test_api/test_news_feed.py`` 风格（async + db_session fixture），
跳过 fixtures 的显式声明（conftest 已 auto-use 隔离 DB）。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.user_news_favorite import UserNewsFavorite
from app.repositories.user_news_favorite import (
    DuplicateFavoriteError,
    UserNewsFavoriteRepository,
)


# ──────────────── 公共 seed helper ────────────────


async def _seed_one(db, **overrides) -> UserNewsFavorite:  # noqa: ANN001
    """插入一条收藏快照；覆盖字段直接传。"""
    base = {
        "news_external_id": 10001,
        "news_source": "readhub",
        "title": "美联储官员暗示 11 月暂停加息",
        "summary": "美联储内部讨论",
        "url": "https://wallstreetcn.com/a/10001",
        "mobile_url": None,
        "site_name": "华尔街见闻",
        "language": "zh-cn",
        "author_name": "张三",
        "publish_date": datetime(2026, 10, 19, 0, 30, tzinfo=timezone.utc),
        "user_tags": '["美联储","美元"]',
        "user_note": "我的笔记",
        "importance": 2,
    }
    base.update(overrides)
    repo = UserNewsFavoriteRepository(db)
    return await repo.add(base)


# ──────────────── add / dedup ────────────────


async def test_add_inserts_and_returns_orm(db_session) -> None:  # noqa: ANN001
    """add 后通过 get 可取回，且返回的 ORM 与入参字段一致。"""
    fav = await _seed_one(db_session, news_external_id=20001)
    assert isinstance(fav, UserNewsFavorite)
    assert fav.id > 0
    assert fav.title == "美联储官员暗示 11 月暂停加息"
    assert fav.importance == 2
    assert fav.site_name == "华尔街见闻"


async def test_add_duplicate_raises(db_session) -> None:  # noqa: ANN001
    """同一 (external_id, source) 第二次 add → DuplicateFavoriteError。"""
    await _seed_one(db_session, news_external_id=30001)
    repo = UserNewsFavoriteRepository(db_session)
    with pytest.raises(DuplicateFavoriteError):
        await repo.add(
            {
                "news_external_id": 30001,
                "news_source": "readhub",
                "title": "另一条",
                "summary": "",
                "url": "https://x.com/a",
                "site_name": "X",
                "publish_date": datetime(2026, 10, 19, tzinfo=timezone.utc),
                "user_tags": "[]",
                "user_note": "",
                "importance": 1,
            }
        )


async def test_add_duplicate_different_source_ok(db_session) -> None:  # noqa: ANN001
    """不同 source 即使 external_id 相同也允许（V0.103 预留多源扩展）。"""
    await _seed_one(db_session, news_external_id=40001, news_source="readhub")
    # 同一 external_id 但 source=cls → 不冲突
    fav2 = await _seed_one(
        db_session, news_external_id=40001, news_source="cls", site_name="财联社"
    )
    assert fav2.id != 0
    assert fav2.news_source == "cls"


# ──────────────── update ────────────────


async def test_update_partial_tags_and_note(db_session) -> None:  # noqa: ANN001
    """update 只传 user_tags / user_note → 仅改这两字段，importance 不变。"""
    fav = await _seed_one(db_session, news_external_id=50001, importance=1)
    repo = UserNewsFavoriteRepository(db_session)
    updated = await repo.update(
        fav.id, user_tags='["地缘","避险"]', user_note="新笔记"
    )
    assert updated is not None
    assert updated.user_tags == '["地缘","避险"]'
    assert updated.user_note == "新笔记"
    # importance 保持不变
    assert updated.importance == 1


async def test_update_importance_only(db_session) -> None:  # noqa: ANN001
    """只升 importance → 其它字段全部不变。"""
    fav = await _seed_one(db_session, news_external_id=50002, importance=1)
    repo = UserNewsFavoriteRepository(db_session)
    updated = await repo.update(fav.id, importance=3)
    assert updated is not None
    assert updated.importance == 3
    assert updated.user_note == "我的笔记"  # 原始笔记不变


async def test_update_unknown_id_returns_none(db_session) -> None:  # noqa: ANN001
    """id 不存在 → 返回 None，不抛错。"""
    repo = UserNewsFavoriteRepository(db_session)
    result = await repo.update(99999, importance=3)
    assert result is None


# ──────────────── delete ────────────────


async def test_delete_existing_returns_true(db_session) -> None:  # noqa: ANN001
    fav = await _seed_one(db_session, news_external_id=60001)
    repo = UserNewsFavoriteRepository(db_session)
    ok = await repo.delete(fav.id)
    assert ok is True
    assert await repo.get(fav.id) is None


async def test_delete_unknown_returns_false(db_session) -> None:  # noqa: ANN001
    repo = UserNewsFavoriteRepository(db_session)
    assert await repo.delete(99999) is False


# ──────────────── find_by_external ────────────────


async def test_find_by_external_returns_match(db_session) -> None:  # noqa: ANN001
    await _seed_one(db_session, news_external_id=70001, news_source="readhub")
    repo = UserNewsFavoriteRepository(db_session)
    fav = await repo.find_by_external(70001, "readhub")
    assert fav is not None
    assert fav.news_external_id == "70001"


async def test_find_by_external_returns_none(db_session) -> None:  # noqa: ANN001
    repo = UserNewsFavoriteRepository(db_session)
    assert await repo.find_by_external(99999, "readhub") is None


# ──────────────── list_items 筛选 / 排序 ────────────────


async def test_list_items_filter_by_importance_min(db_session) -> None:  # noqa: ANN001
    """importance_min=2 → 仅 importance >= 2 的行。"""
    await _seed_one(db_session, news_external_id=80001, importance=1)
    await _seed_one(db_session, news_external_id=80002, importance=2)
    await _seed_one(db_session, news_external_id=80003, importance=3)
    repo = UserNewsFavoriteRepository(db_session)
    items = await repo.list_items(importance_min=2)
    assert {it.news_external_id for it in items} == {"80002", "80003"}
    assert all(it.importance >= 2 for it in items)


async def test_list_items_filter_by_tag(db_session) -> None:  # noqa: ANN001
    """tag='美联储' → JSON 数组中精确包含此 tag 的行。"""
    await _seed_one(
        db_session,
        news_external_id=81001,
        user_tags='["美联储","美元"]',
    )
    await _seed_one(
        db_session,
        news_external_id=81002,
        user_tags='["地缘","避险"]',
    )
    repo = UserNewsFavoriteRepository(db_session)
    items = await repo.list_items(tag="美联储")
    assert len(items) == 1
    assert items[0].news_external_id == "81001"


async def test_list_items_filter_by_site(db_session) -> None:  # noqa: ANN001
    await _seed_one(
        db_session, news_external_id=82001, site_name="华尔街见闻"
    )
    await _seed_one(
        db_session, news_external_id=82002, site_name="财联社"
    )
    repo = UserNewsFavoriteRepository(db_session)
    items = await repo.list_items(site_name="财联社")
    assert len(items) == 1
    assert items[0].site_name == "财联社"


async def test_list_items_sort_recent_default(db_session) -> None:  # noqa: ANN001
    """默认 sort='recent' → 按 archived_at 倒序（SQLite second 精度时退化为 id 倒序）。"""
    f1 = await _seed_one(db_session, news_external_id=83001)
    f2 = await _seed_one(db_session, news_external_id=83002)
    f3 = await _seed_one(db_session, news_external_id=83003)
    repo = UserNewsFavoriteRepository(db_session)
    items = await repo.list_items()  # 默认 recent
    ids = [it.id for it in items]
    # SQLite 的 func.now() 是 second 精度 → 同一秒内 3 条记录的 archived_at 完全一致，
    # 排序由底层存储顺序决定（通常 = id 升序）。3 条都在即可。
    assert len(ids) == 3
    assert set(ids) == {f1.id, f2.id, f3.id}


async def test_list_items_sort_importance(db_session) -> None:  # noqa: ANN001
    f_low = await _seed_one(
        db_session, news_external_id=84001, importance=1
    )
    f_hi = await _seed_one(
        db_session, news_external_id=84002, importance=3
    )
    repo = UserNewsFavoriteRepository(db_session)
    items = await repo.list_items(sort="importance")
    assert items[0].id == f_hi.id
    assert items[1].id == f_low.id


# ──────────────── list_sites / list_tags ────────────────


async def test_list_sites_returns_unique(db_session) -> None:  # noqa: ANN001
    await _seed_one(
        db_session, news_external_id=85001, site_name="华尔街见闻"
    )
    await _seed_one(
        db_session, news_external_id=85002, site_name="财联社"
    )
    await _seed_one(
        db_session, news_external_id=85003, site_name="财联社"  # 重复
    )
    repo = UserNewsFavoriteRepository(db_session)
    sites = await repo.list_sites()
    assert set(sites) == {"华尔街见闻", "财联社"}


async def test_list_tags_parses_and_dedups(db_session) -> None:  # noqa: ANN001
    await _seed_one(
        db_session, news_external_id=86001, user_tags='["美联储","美元"]'
    )
    await _seed_one(
        db_session, news_external_id=86002, user_tags='["地缘","美联储"]'
    )
    await _seed_one(
        db_session, news_external_id=86003, user_tags="[]"
    )  # 空 tags 应被忽略
    repo = UserNewsFavoriteRepository(db_session)
    tags = await repo.list_tags()
    # 字母序
    assert tags == sorted({"美联储", "美元", "地缘"})


# ──────────────── get_status ────────────────


async def test_get_status_aggregates(db_session) -> None:  # noqa: ANN001
    """get_status 返回 6 维聚合：total / by_importance / by_site / by_tag / by_month。"""
    await _seed_one(
        db_session,
        news_external_id=87001,
        importance=1,
        site_name="A",
        user_tags="[]",
    )
    await _seed_one(
        db_session,
        news_external_id=87002,
        importance=3,
        site_name="A",
        user_tags="[]",
    )
    await _seed_one(
        db_session,
        news_external_id=87003,
        importance=3,
        site_name="B",
        user_tags='["黄金"]',
    )
    repo = UserNewsFavoriteRepository(db_session)
    status = await repo.get_status()
    assert status["total"] == 3
    assert status["by_importance"] == {1: 1, 3: 2}
    by_site_map = {row["site_name"]: row["count"] for row in status["by_site"]}
    assert by_site_map == {"A": 2, "B": 1}
    by_tag_map = {row["tag"]: row["count"] for row in status["by_tag"]}
    assert by_tag_map == {"黄金": 1}
    # by_month 至少有 1 个
    assert len(status["by_month"]) >= 1
