"""账本 API 与交易历史 API 集成测试（P1 #6）。

覆盖：
- ``/accounts`` 清单（默认账本自动保障）/ 新建 / 重名 / 校验 / 改名 / 设为默认
- 归档守卫（默认账本不可归档）与恢复
- ``/trades`` 空态、开仓后可查、按账本隔离、参数校验 422
- ``/trades/export`` CSV 输出与附件头
- 账本隔离贯穿持仓 / 收益曲线 / 获利分析
"""

from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from app.dependencies import get_market_data_repository
from app.main import app
from app.repositories.market_data import GoldKline


class FakeMarket:
    """假行情：ETF 历史价固定 10.0（日期覆盖最近 120 天），供曲线/业绩账本隔离用例。"""

    async def get_gold_history(self, days: int = 60):
        today = date.today()
        return [
            GoldKline(
                date=today - timedelta(days=119 - i),
                open=10.0,
                close=10.0,
                high=10.0,
                low=10.0,
                volume=0.0,
            )
            for i in range(120)
        ]

    async def get_gold_etf_quote(self, symbol: str = "518880"):
        return type(
            "Q",
            (),
            {
                "symbol": symbol,
                "price_usd": 10.0,
                "change_pct": 0.0,
                "updated_at": date.today(),
            },
        )()

    async def get_gold_quote(self, symbol: str = "XAU"):
        return type(
            "Q",
            (),
            {
                "symbol": symbol,
                "price_usd": 4349.7,
                "change_pct": 0.0,
                "updated_at": date.today(),
            },
        )()


@pytest.fixture(autouse=True)
def _override_market():
    app.dependency_overrides[get_market_data_repository] = lambda: FakeMarket()
    yield
    app.dependency_overrides.clear()


# ───────────────────────── 账本 API ─────────────────────────
async def test_accounts_list_has_default(client: AsyncClient) -> None:
    """首次访问自动保障默认账本（id=1）。"""
    resp = await client.get("/api/v1/accounts")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["current_account_id"] == 1
    first = body["items"][0]
    assert first["name"] == "默认账户"
    assert first["is_default"] is True
    assert first["stats"]["position_count"] == 0


async def test_account_crud_flow(client: AsyncClient) -> None:
    # 新建
    resp = await client.post("/api/v1/accounts", json={"name": "家人账户", "note": "定投"})
    assert resp.status_code == 201
    created = resp.json()
    assert created["name"] == "家人账户"
    assert created["is_default"] is False
    aid = created["id"]

    # 详情
    resp = await client.get(f"/api/v1/accounts/{aid}")
    assert resp.status_code == 200

    # 重名 → 400
    resp = await client.post("/api/v1/accounts", json={"name": "家人账户"})
    assert resp.status_code == 400
    assert "同名账本" in resp.json()["detail"]

    # 名称空白 → 422（Pydantic 校验）
    resp = await client.post("/api/v1/accounts", json={"name": "   "})
    assert resp.status_code == 422

    # 改名
    resp = await client.patch(f"/api/v1/accounts/{aid}", json={"name": "父母账户"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "父母账户"

    # 设为默认 → 旧默认被清除
    resp = await client.patch(f"/api/v1/accounts/{aid}", json={"is_default": True})
    assert resp.status_code == 200
    assert resp.json()["is_default"] is True
    listed = (await client.get("/api/v1/accounts")).json()
    flags = {a["name"]: a["is_default"] for a in listed["items"]}
    assert flags["父母账户"] is True
    assert flags["默认账户"] is False
    assert listed["current_account_id"] == aid

    # 未知账本 → 404
    assert (await client.get("/api/v1/accounts/999")).status_code == 404


async def test_archive_default_rejected(client: AsyncClient) -> None:
    await client.get("/api/v1/accounts")  # 触发默认账本创建
    resp = await client.post("/api/v1/accounts/1/archive")
    assert resp.status_code == 400
    assert "默认账本不可归档" in resp.json()["detail"]


async def test_archive_and_restore_via_api(client: AsyncClient) -> None:
    await client.get("/api/v1/accounts")
    aid = (await client.post("/api/v1/accounts", json={"name": "临时账本"})).json()["id"]

    resp = await client.post(f"/api/v1/accounts/{aid}/archive")
    assert resp.status_code == 200
    assert resp.json()["archived"] is True

    # 默认清单不含归档账本，include_archived=true 时可见
    assert all(a["id"] != aid for a in (await client.get("/api/v1/accounts")).json()["items"])
    with_arch = (await client.get("/api/v1/accounts?include_archived=true")).json()
    assert any(a["id"] == aid for a in with_arch["items"])

    resp = await client.post(f"/api/v1/accounts/{aid}/restore")
    assert resp.status_code == 200
    assert resp.json()["archived"] is False

    # 未归档再次恢复 → 400
    assert (await client.post(f"/api/v1/accounts/{aid}/restore")).status_code == 400


# ───────────────────────── 交易历史 API ─────────────────────────
async def test_trades_empty_state(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/trades")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []
    assert body["summary"]["count"] == 0
    assert body["page_count"] == 1


async def test_trades_after_open_and_account_isolation(client: AsyncClient) -> None:
    await client.get("/api/v1/accounts")  # 保障默认账本
    # 默认账本开仓
    resp = await client.post(
        "/api/v1/positions",
        json={"symbol": "518880", "quantity": 1000, "price": 9.0, "fee": 5.0},
    )
    assert resp.status_code == 201
    assert resp.json()["account_id"] == 1

    # 新账本 + 在该账本开仓（通过 account_id 指定）
    acc2 = (await client.post("/api/v1/accounts", json={"name": "家人账户"})).json()["id"]
    resp = await client.post(
        f"/api/v1/positions?account_id={acc2}",
        json={"symbol": "518880", "quantity": 500, "price": 9.5, "fee": 2.0},
    )
    assert resp.status_code == 201
    assert resp.json()["account_id"] == acc2

    # 全部账本：2 笔流水
    body = (await client.get("/api/v1/trades")).json()
    assert body["total"] == 2
    assert body["summary"]["buy_amount"] == 9000.0 + 4750.0
    assert body["summary"]["total_fee"] == 7.0
    assert {i["account_name"] for i in body["items"]} == {"默认账户", "家人账户"}

    # 单账本隔离
    only2 = (await client.get(f"/api/v1/trades?account_id={acc2}")).json()
    assert only2["total"] == 1
    assert only2["items"][0]["account_name"] == "家人账户"
    assert only2["summary"]["buy_amount"] == 4750.0

    # 持仓列表同样按账本隔离
    assert len((await client.get("/api/v1/positions")).json()) == 2
    assert len((await client.get(f"/api/v1/positions?account_id={acc2}")).json()) == 1

    # 收益曲线 / 获利分析也支持账本
    curve = (await client.get(f"/api/v1/portfolio/equity-curve?days=30&account_id={acc2}")).json()
    assert curve["summary"]["total_invested"] == 4752.0
    perf = (await client.get(f"/api/v1/portfolio/performance?account_id={acc2}")).json()
    assert perf["total_invested"] == 4752.0

    # 非法账本 → 400（开仓解析失败）
    resp = await client.post(
        "/api/v1/positions?account_id=999",
        json={"symbol": "518880", "quantity": 100, "price": 9.0},
    )
    assert resp.status_code == 400


async def test_trades_validation(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/trades?side=xx")).status_code == 422
    assert (await client.get("/api/v1/trades?start=2026-09-10&end=2026-09-01")).status_code == 422
    assert (await client.get("/api/v1/trades?page=0")).status_code == 422
    assert (await client.get("/api/v1/trades?page_size=9999")).status_code == 422


async def test_trades_export_csv(client: AsyncClient) -> None:
    await client.get("/api/v1/accounts")
    await client.post(
        "/api/v1/positions",
        json={"symbol": "518880", "quantity": 1000, "price": 9.0, "fee": 5.0},
    )
    resp = await client.get("/api/v1/trades/export")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert "attachment" in resp.headers["content-disposition"]
    text = resp.text
    assert "交易历史导出" in text
    assert "默认账户" in text
    assert "汇总" in text
