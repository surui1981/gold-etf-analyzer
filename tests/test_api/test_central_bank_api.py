"""央行购金 REST 端点 单测。"""

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.central_bank import CentralBankPurchase


async def _seed(db: AsyncSession) -> None:
    rows = [
        CentralBankPurchase(
            country_iso="CHN", country_name="中国", quarter="2026Q2",
            tonnes_net=33.0, source="IMF IRFCL", data_date=date(2026, 6, 30),
        ),
        CentralBankPurchase(
            country_iso="POL", country_name="波兰", quarter="2026Q2",
            tonnes_net=51.0, source="IMF IRFCL", data_date=date(2026, 6, 30),
        ),
        CentralBankPurchase(
            country_iso="CHN", country_name="中国", quarter="2025Q4",
            tonnes_net=25.0, source="IMF IRFCL", data_date=date(2025, 12, 31),
        ),
    ]
    for r in rows:
        db.add(r)
    await db.commit()


async def test_get_purchases_full(client, db_session: AsyncSession) -> None:
    """GET /purchases 不带参数 → 全量 + summary + top。"""
    await _seed(db_session)
    r = await client.get("/api/v1/central-bank/purchases")
    assert r.status_code == 200
    data = r.json()
    assert "items" in data and "summary" in data and "top_buyers" in data
    assert len(data["items"]) == 3
    assert data["summary"]["current_quarter"] == "2026Q2"
    assert data["summary"]["country_count"] == 2


async def test_get_purchases_filter_quarter_range(client, db_session: AsyncSession) -> None:
    """GET /purchases?from_q=2026Q1 → 仅 2026Q2 数据。"""
    await _seed(db_session)
    r = await client.get("/api/v1/central-bank/purchases?from_q=2026Q1")
    assert r.status_code == 200
    data = r.json()
    assert len(data["items"]) == 2
    assert all(it["quarter"] == "2026Q2" for it in data["items"])


async def test_get_purchases_filter_country(client, db_session: AsyncSession) -> None:
    """GET /purchases?country=CHN → 仅中国记录。"""
    await _seed(db_session)
    r = await client.get("/api/v1/central-bank/purchases?country=CHN")
    assert r.status_code == 200
    data = r.json()
    assert len(data["items"]) == 2
    assert all(it["country_iso"] == "CHN" for it in data["items"])


async def test_get_purchases_country_uppercased(client, db_session: AsyncSession) -> None:
    """country 参数大小写不敏感：chn → 视作 CHN。"""
    await _seed(db_session)
    r = await client.get("/api/v1/central-bank/purchases?country=chn")
    assert r.status_code == 200
    data = r.json()
    assert all(it["country_iso"] == "CHN" for it in data["items"])


async def test_get_purchases_invalid_quarter_returns_422(client, db_session: AsyncSession) -> None:
    """非法的 from_q 格式 → 422。"""
    r = await client.get("/api/v1/central-bank/purchases?from_q=invalid")
    assert r.status_code == 422


async def test_get_purchases_invalid_country_length(client, db_session: AsyncSession) -> None:
    """country 长度 ≠ 3 → 422。"""
    r = await client.get("/api/v1/central-bank/purchases?country=CH")
    assert r.status_code == 422


async def test_get_top_buyers(client, db_session: AsyncSession) -> None:
    """GET /top-buyers?year=2026&limit=2 → POL 第一、CHN 第二。"""
    await _seed(db_session)
    r = await client.get("/api/v1/central-bank/top-buyers?year=2026&limit=2")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[0]["country_iso"] == "POL"  # 51 > 33
    assert data[0]["rank"] == 1


async def test_get_top_buyers_default_limit(client, db_session: AsyncSession) -> None:
    """GET /top-buyers 不带 limit → 默认 10。"""
    await _seed(db_session)
    r = await client.get("/api/v1/central-bank/top-buyers?year=2026")
    assert r.status_code == 200
    assert r.json()  # 至少 1 个


async def test_get_top_buyers_invalid_year(client, db_session: AsyncSession) -> None:
    """year 超出范围 → 422。"""
    r = await client.get("/api/v1/central-bank/top-buyers?year=1999")
    assert r.status_code == 422
    r = await client.get("/api/v1/central-bank/top-buyers?year=2099")
    assert r.status_code == 422


async def test_get_summary(client, db_session: AsyncSession) -> None:
    """GET /summary → 轻量摘要字段。"""
    await _seed(db_session)
    r = await client.get("/api/v1/central-bank/summary")
    assert r.status_code == 200
    data = r.json()
    assert data["current_quarter"] == "2026Q2"
    assert data["country_count"] == 2
    assert data["latest_data_quarter"] == "2026Q2"


async def test_root_redirect_to_central_bank_page(client) -> None:
    """GET /central-bank → 307 重定向到 /static/central_bank.html（页面存在后生效）。"""
    r = await client.get("/central-bank", follow_redirects=False)
    assert r.status_code in (307, 308)  # FastAPI RedirectResponse 默认 307
    assert r.headers["location"] == "/static/central_bank.html"
