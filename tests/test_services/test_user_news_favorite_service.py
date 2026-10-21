"""收藏 service 单测（V0.114.0 url 可空放宽）

背景
----
V0.102 起 ``url`` 是收藏快照的**必填**字段 —— service 里两处
``missing = [k for k in ("title", "url", "site_name", "publish_date") ...]``
把 url 为空的条目直接 422 挡掉。

V0.114.0 接入金十 / 东方财富快讯后这成了硬伤：这两源的快讯接口**实测
0/20 条提供链接**，于是它们一条都收藏不了。本文件钉住「url 可空」这个
行为变更，以及「真的缺关键字段时仍然要 422」的反向保护。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.news_feed import NewsFeedItem
from app.models.user_news_favorite import UserNewsFavorite
from app.repositories.news_feed import NewsFeedRepository
from app.repositories.user_news_favorite import UserNewsFavoriteRepository
from app.schemas.user_news_favorite import UserNewsFavoriteCreateIn
from app.services.user_news_favorite import UserNewsFavoriteService

_PUB = datetime(2026, 10, 22, 1, 30, tzinfo=timezone.utc)


async def _seed_feed_item(db, **over) -> NewsFeedItem:  # noqa: ANN001
    """插入一条 news_feed_items 行（默认**无 URL**，模拟金十/东财快讯）。"""
    row = NewsFeedItem(
        external_id=over.pop("external_id", 20261022052906788800),
        source=over.pop("source", "jin10"),
        title=over.pop("title", "美联储官员暗示 11 月暂停加息"),
        summary=over.pop("summary", "美联储内部讨论"),
        url=over.pop("url", None),
        mobile_url=None,
        site_name=over.pop("site_name", "金十数据"),
        language="zh-cn",
        author_name=None,
        publish_date=_PUB,
        category="财经",
        **over,
    )
    db.add(row)
    await db.commit()
    return row


def _svc(db) -> UserNewsFavoriteService:  # noqa: ANN001
    return UserNewsFavoriteService(
        UserNewsFavoriteRepository(db), NewsFeedRepository(db)
    )


# ──────────────── url 可空 ────────────────


async def test_favorite_url_less_feed_item_succeeds(db_session) -> None:  # noqa: ANN001
    """金十/东财条目没有原文链接 —— 收藏必须成功，而不是 422。"""
    await _seed_feed_item(db_session, external_id=1, source="jin10")
    payload = UserNewsFavoriteCreateIn(news_external_id=1, news_source="jin10")
    out = await _svc(db_session).add(payload)

    assert out.title == "美联储官员暗示 11 月暂停加息"
    assert out.url is None
    assert out.news_source == "jin10"


async def test_favorite_without_feed_item_and_no_url_422s(db_session) -> None:  # noqa: ANN001
    """⚠ 反向保护：url 不再必填**不等于**其它字段也不必填。

    外部直传场景下 title / site_name / publish_date 缺一仍必须 422 ——
    放宽 url 时顺手把整段校验删掉的话，快照会变成一堆没标题的空卡片。
    """
    payload = UserNewsFavoriteCreateIn(news_external_id=999, news_source="jin10")
    with pytest.raises(HTTPException) as ei:
        await _svc(db_session).add(payload)
    assert ei.value.status_code == 422
    assert "title" in ei.value.detail


async def test_favorite_external_url_still_works(db_session) -> None:  # noqa: ANN001
    """外部 URL 直传（V0.103 场景）不受影响。"""
    payload = UserNewsFavoriteCreateIn(
        news_external_id=555,
        news_source="external",
        title="手动收藏的标题",
        url="https://example.com/a/555",
        site_name="手动",
        publish_date=_PUB,
    )
    out = await _svc(db_session).add(payload)
    assert out.url == "https://example.com/a/555"


# ──────────────── 多源 dedup ────────────────


async def test_same_id_different_source_are_two_favorites(db_session) -> None:  # noqa: ANN001
    """external_id 不再全局唯一 —— (id, source) 才是 dedup 主键。

    页面上两张卡片（华尔街见闻 3182985 / 金十某条）id 相同不代表同一条新闻。
    """
    await _seed_feed_item(db_session, external_id=777, source="wallstcn", url="https://a/777")
    await _seed_feed_item(db_session, external_id=777, source="jin10", url=None)
    svc = _svc(db_session)
    a = await svc.add(UserNewsFavoriteCreateIn(news_external_id=777, news_source="wallstcn"))
    b = await svc.add(UserNewsFavoriteCreateIn(news_external_id=777, news_source="jin10"))
    assert a.id != b.id


async def test_twenty_digit_id_roundtrips_through_favorite(db_session) -> None:  # noqa: ANN001
    """金十 20 位 id 全链路无损：入库 → 收藏 → 读回。

    列是 String(32)（int64 装不下 2.02e19）。任何一处把它转成 int 都会
    触发 OverflowError，或（如果转成 JS Number）静默舍入成另一个 id ——
    后者更糟，因为它不报错，收藏会落到一个不存在的新闻上。
    """
    big = 20261022052906788800
    await _seed_feed_item(db_session, external_id=big, source="jin10")
    out = await _svc(db_session).add(
        UserNewsFavoriteCreateIn(news_external_id=big, news_source="jin10")
    )
    assert out.news_external_id == big

    rows = (
        await db_session.execute(select(UserNewsFavorite))
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].news_external_id == str(big)