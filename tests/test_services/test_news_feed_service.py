"""NewsFeedService 单测（V0.107.1 service 二次 gate）

仅覆盖 V0.107.1 引入的 service 层弃入「其他」filter 逻辑。
完整仓储 / API 测试在 test_repositories/test_news_feed.py 与
tests/test_api/test_news_feed.py。

V0.107.1：service.refresh() 在 fetcher 返回的 records 中再过滤
       category='其他'（defense-in-depth 防 fetcher 改动漏改）。

Patch 注意事项：news_feed.py 用 ``from ... import fetch_readhub_feed``
在模块顶部拉取了局部引用；monkeypatch 必须打在
``app.services.news_feed.fetch_readhub_feed``，否则 service 调的是
原始 fetcher（与 records mock 不生效）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


# ──────────────── 公共 fixture ────────────────


def _make_record(category: str, ext_id: int = 1001) -> dict[str, Any]:
    """构造 1 条 fetcher normalize 出来的 record dict（与 readhub_fetcher._normalize 同 schema）。"""
    return {
        "external_id": ext_id,
        "title": f"测试-{category}",
        "summary": "",
        "url": f"https://example.com/{ext_id}",
        "mobile_url": None,
        "site_name": "测试站点",
        "language": "zh-cn",
        "author_name": None,
        "publish_date": datetime(2026, 10, 19, 0, 0, tzinfo=timezone.utc),
        "category": category,
    }


# ──────────────── V0.107.1 service gate 测试 ────────────────


async def test_refresh_drops_other_records_v01071(monkeypatch: pytest.MonkeyPatch) -> None:
    """V0.107.1：fetcher 返回含「其他」的 records → service.refresh() 二次
    拦截后只有 4 类记录到达 upsert_bulk，「其他」被丢弃。
    """
    from app.repositories import news_feed as nf_repo_module  # noqa: F401
    from app.services import news_feed as svc_module
    from app.services.news_feed import NewsFeedService

    # mock fetcher：返回混合 records（含「其他」）
    mixed_records = (
        _make_record("财经", ext_id=1),
        _make_record("科技", ext_id=2),
        _make_record("创投", ext_id=3),
        _make_record("商业", ext_id=4),
        _make_record("其他", ext_id=5),
        _make_record("其他", ext_id=6),
    )

    async def _fake_fetch_readhub_feed(**_kwargs):
        return mixed_records

    # 注意：patch target 必须是 service 模块里的 import 引用
    monkeypatch.setattr(svc_module, "fetch_readhub_feed", _fake_fetch_readhub_feed)

    # mock 仓储：capture 入参 + 返 n=2（4 类 2 条 + 创投 + 商业）
    repo = MagicMock()
    captured: dict[str, Any] = {}

    async def _fake_upsert_bulk(records):
        captured["records"] = list(records)
        return len(records)

    repo.upsert_bulk = _fake_upsert_bulk

    svc = NewsFeedService(repo)
    out = await svc.refresh(force=True)

    # 断言：4 条记录被 upsert，「其他」2 条被丢弃
    assert out["ok"] is True
    assert out["upserted"] == 4
    assert out["error"] is None
    assert "records" in captured
    categories = {r["category"] for r in captured["records"]}
    assert categories == {"财经", "科技", "创投", "商业"}
    assert "其他" not in categories


async def test_refresh_drops_all_other_records_v01071(monkeypatch: pytest.MonkeyPatch) -> None:
    """V0.107.1：fetcher 全返「其他」 → service.refresh() 当作软失败，
    不调 upsert_bulk，返 ok=False + error='no valid items after category filter'。
    """
    from app.services import news_feed as svc_module
    from app.services.news_feed import NewsFeedService

    async def _fake_fetch_readhub_feed(**_kwargs):
        return (_make_record("其他", ext_id=1), _make_record("其他", ext_id=2))

    monkeypatch.setattr(svc_module, "fetch_readhub_feed", _fake_fetch_readhub_feed)

    repo = MagicMock()
    repo.upsert_bulk = AsyncMock()

    svc = NewsFeedService(repo)
    out = await svc.refresh(force=True)

    # 断言：软失败，upsert_bulk 未被调用
    assert out["ok"] is False
    assert out["upserted"] == 0
    assert "category filter" in out["error"]
    repo.upsert_bulk.assert_not_called()


async def test_refresh_passes_through_valid_records_v01071(monkeypatch: pytest.MonkeyPatch) -> None:
    """V0.107.1：fetcher 全返 4 类有效记录 → service.refresh() 不需过滤，
    全部 upsert。"""
    from app.services import news_feed as svc_module
    from app.services.news_feed import NewsFeedService

    valid_records = (
        _make_record("财经", ext_id=1),
        _make_record("科技", ext_id=2),
        _make_record("创投", ext_id=3),
        _make_record("商业", ext_id=4),
    )

    async def _fake_fetch_readhub_feed(**_kwargs):
        return valid_records

    monkeypatch.setattr(svc_module, "fetch_readhub_feed", _fake_fetch_readhub_feed)

    repo = MagicMock()

    async def _fake_upsert_bulk(records):
        return len(records)

    repo.upsert_bulk = _fake_upsert_bulk

    svc = NewsFeedService(repo)
    out = await svc.refresh(force=True)

    # 断言：全部 4 条 upserted
    assert out["ok"] is True
    assert out["upserted"] == 4


# ──────────────── V0.108.0 service gate：站点黑名单 ────────────────


async def test_refresh_drops_blacklisted_site_v01080(monkeypatch: pytest.MonkeyPatch) -> None:
    """V0.108.0：fetcher 改动漏改时，service gate 仍拦住黑名单站点条目。

    这条模拟「fetcher 的 SITE_BLOCKLIST 检查被漏掉」的场景——records 里
    带 site_name='新浪科技' 的 4 类记录照样到不了 upsert_bulk。
    """
    from app.services import news_feed as svc_module
    from app.services.news_feed import NewsFeedService

    blocked = _make_record("财经", ext_id=10)
    blocked["site_name"] = "新浪科技"
    blocked["title"] = "科创半导体设备 ETF 交投升温"
    mixed_records = (
        _make_record("财经", ext_id=1),
        blocked,
        _make_record("科技", ext_id=3),
    )

    async def _fake_fetch_readhub_feed(**_kwargs):
        return mixed_records

    monkeypatch.setattr(svc_module, "fetch_readhub_feed", _fake_fetch_readhub_feed)

    repo = MagicMock()
    captured: dict[str, Any] = {}

    async def _fake_upsert_bulk(records):
        captured["records"] = list(records)
        return len(records)

    repo.upsert_bulk = _fake_upsert_bulk

    svc = NewsFeedService(repo)
    out = await svc.refresh(force=True)

    assert out["ok"] is True
    assert out["upserted"] == 2  # 新浪科技那条被拦下
    assert {r["external_id"] for r in captured["records"]} == {1, 3}


async def test_refresh_all_blacklisted_is_soft_failure_v01080(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """V0.108.0：整批都是黑名单站点 → 软失败（不调 upsert_bulk），
    UI 走 V0.84「保留末次数据」路径，不返 500。"""
    from app.services import news_feed as svc_module
    from app.services.news_feed import NewsFeedService

    only_blacklisted = (
        {**_make_record("财经", ext_id=1), "site_name": "新浪科技"},
        {**_make_record("科技", ext_id=2), "site_name": "maomu.com"},
    )

    async def _fake_fetch_readhub_feed(**_kwargs):
        return only_blacklisted

    monkeypatch.setattr(svc_module, "fetch_readhub_feed", _fake_fetch_readhub_feed)

    repo = MagicMock()
    repo.upsert_bulk = AsyncMock()

    svc = NewsFeedService(repo)
    out = await svc.refresh(force=True)

    assert out["ok"] is False
    assert out["upserted"] == 0
    assert "category filter" in out["error"]
    repo.upsert_bulk.assert_not_called()
