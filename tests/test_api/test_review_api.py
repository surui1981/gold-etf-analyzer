"""研判复盘接口测试（V0.66.0）：配置元信息、日志、统计、提示与补录路径。"""

from datetime import date, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.review import GoldPriceRepository


async def _seed_prices(db: AsyncSession, closes: list[float]) -> list[date]:
    today = date.today()
    start = today - timedelta(days=len(closes) - 1)
    bars = [(start + timedelta(days=i), float(c)) for i, c in enumerate(closes)]
    await GoldPriceRepository(db).upsert_many(target="ny", bars=bars, source="test")
    return [b[0] for b in bars]


async def test_meta_lists_targets_and_tags(client: AsyncClient) -> None:
    """复盘配置接口返回可选标的、窗口与预置依据标签。"""
    r = await client.get("/api/v1/review/meta")
    assert r.status_code == 200

    d = r.json()
    assert any(t["key"] == "ny" for t in d["targets"])
    assert d["horizons"] == [1, 3, 5]
    assert "美元指数" in d["basis_tags"]
    assert d["neutral_band_pct"] == 0.3


async def test_journal_and_stats_empty(client: AsyncClient) -> None:
    """无研判、无价格时不报错，返回空结果与提示。"""
    j = await client.get("/api/v1/review/journal?days=30")
    assert j.status_code == 200
    assert j.json()["total"] == 0
    assert j.json()["items"] == []

    s = await client.get("/api/v1/review/stats?days=30")
    assert s.status_code == 200
    body = s.json()
    assert body["evaluated"] == 0
    assert body["hit_rate"] is None
    assert body["sample_warning"] is True
    assert len(body["calibration"]) == 5


async def test_horizons_endpoint(client: AsyncClient) -> None:
    """窗口枚举接口。"""
    r = await client.get("/api/v1/review/horizons")
    assert r.status_code == 200
    assert r.json() == {"horizons": [1, 3, 5], "default": 1}


async def test_hint_endpoint(client: AsyncClient) -> None:
    """打分前提示接口可用（无样本时返回 0 样本而非报错）。"""
    r = await client.get("/api/v1/review/hint?score=70")
    assert r.status_code == 200
    d = r.json()
    assert d["bucket"] == "60-80"
    assert d["samples"] == 0
    assert d["hit_rate"] is None


async def test_hint_rejects_out_of_range(client: AsyncClient) -> None:
    """越界分值被参数校验拦截。"""
    r = await client.get("/api/v1/review/hint?score=140")
    assert r.status_code == 422


async def test_backfill_date_is_marked_and_excluded(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """按历史日期补录 → 记录标记 backfilled，日志可见但统计排除。"""
    dates = await _seed_prices(db_session, [100, 102, 101, 103, 104, 100, 98, 99, 101, 105])
    older = dates[0]
    newer = dates[3]

    # 真实研判（当日打分语义，未标记补录）
    from app.models.news import NewsScore

    db_session.add(
        NewsScore(score_date=older, slot=1, score=70, direction="bullish", notes="真实研判")
    )
    await db_session.commit()

    # 通过接口补录历史日期
    r = await client.put(
        "/api/v1/news-score",
        json={
            "score": 70,
            "direction": "bullish",
            "notes": "事后补录",
            "basis": ["央行购金"],
            "score_date": str(newer),
            "slot": 1,
        },
    )
    assert r.status_code == 200
    assert r.json()["score_date"] == str(newer)
    assert r.json()["slots"][0]["backfilled"] is True
    assert r.json()["slots"][0]["basis"] == ["央行购金"]

    # 日志中两天都在，补录日带标记
    j = await client.get("/api/v1/review/journal?days=30")
    items = {i["score_date"]: i for i in j.json()["items"]}
    assert str(newer) in items and str(older) in items
    assert items[str(newer)]["backfilled"] is True
    assert items[str(older)]["backfilled"] is False

    # 统计排除补录日
    s = await client.get("/api/v1/review/stats?days=30&horizon=1")
    body = s.json()
    assert body["backfilled_excluded"] == 1
    assert body["evaluated"] == 1
    assert body["hits"] == 1
    assert body["hit_rate"] == 100.0


async def test_future_score_date_rejected(client: AsyncClient) -> None:
    """补录日期不能晚于今天。"""
    future = (date.today() + timedelta(days=1)).isoformat()
    r = await client.put(
        "/api/v1/news-score",
        json={"score": 60, "direction": "bullish", "score_date": future},
    )
    assert r.status_code == 400
    assert "不能晚于今天" in r.json()["detail"]


async def test_delete_slot_with_score_date(client: AsyncClient) -> None:
    """撤销支持指定日期（补录记录的回退路径）。"""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    await client.put(
        "/api/v1/news-score",
        json={"score": 60, "direction": "bullish", "score_date": yesterday},
    )

    r = await client.delete(f"/api/v1/news-score/1?score_date={yesterday}")
    assert r.status_code == 200
    assert r.json()["used_slots"] == 0

    # 再撤一次 → 404
    r2 = await client.delete(f"/api/v1/news-score/1?score_date={yesterday}")
    assert r2.status_code == 404


async def test_journal_outcomes_present(client: AsyncClient, db_session: AsyncSession) -> None:
    """有价格时，日志返回 T+1/T+3/T+5 三个窗口的对比结果。"""
    dates = await _seed_prices(db_session, [100, 102, 101, 103, 104, 100, 98, 99, 101, 105])

    from app.models.news import NewsScore

    db_session.add(
        NewsScore(score_date=dates[0], slot=1, score=70, direction="bullish", notes="看多")
    )
    await db_session.commit()

    r = await client.get("/api/v1/review/journal?days=30&horizon=1")
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["price_close"] == 100.0
    outcomes = {o["horizon"]: o for o in item["outcomes"]}
    assert outcomes[1]["change_pct"] == 2.0
    assert outcomes[1]["hit"] is True
    assert outcomes[5]["hit"] is False
