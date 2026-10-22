"""COMEX 黄金库存端点测试：响应 schema、降级态、参数边界、路由不互遮。

``client`` 与 ``db_session`` 指向同一个测试库（都走 ``async_session_factory``），
所以这里直接用 ``db_session`` seed，端点自己的 session 就能读到 ——
不需要 dependency_override，测试也更接近真实链路。
"""

from datetime import date, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.gold_inventory import GoldInventoryDaily
from app.repositories.gold_inventory import GoldInventoryRepository

TODAY = date.today()
URL = "/api/v1/market/gold/inventory"


async def _seed(db: AsyncSession, rows: list[dict]) -> None:
    await GoldInventoryRepository(db).upsert_bulk([GoldInventoryDaily(**r) for r in rows])


def _flat(n: int, start_t: float = 900.0, step: float = 1.0) -> list[dict]:
    """n 天连续观测：最早 start_t，每天降 step。"""
    return [
        {"inv_date": TODAY - timedelta(days=i), "tonnes": start_t - step * i, "ounces": None}
        for i in range(n)
    ]


async def test_inventory_empty_table(client: AsyncClient) -> None:
    """空表 → 200 + ``latest_tonnes=null`` + ``points=[]`` + ``degraded=true``。

    ⚠ 必须是 null 而不是 0：「COMEX 库存 0 吨」是个极强的结论，
    空表时给 0 等于凭空断言交易所仓库被搬空了。
    """
    resp = await client.get(URL, params={"days": 90})
    assert resp.status_code == 200
    d = resp.json()
    assert d["source"] == "COMEX"
    assert d["unit"] == "吨"
    assert d["latest_tonnes"] is None
    assert d["as_of"] is None
    assert d["points"] == []
    assert d["degraded"] is True
    assert [c["window"] for c in d["changes"]] == ["1w", "1m", "3m", "1y"]
    assert all(c["change_pct"] is None for c in d["changes"])


async def test_inventory_with_data(client: AsyncClient, db_session: AsyncSession) -> None:
    """有数据 → 完整响应，四窗口基线齐、points 升序。"""
    await _seed(db_session, _flat(30, start_t=900.0, step=0.5))

    resp = await client.get(URL, params={"days": 90})
    assert resp.status_code == 200
    d = resp.json()
    assert d["latest_tonnes"] is not None
    assert d["as_of"] == TODAY.isoformat()
    assert d["degraded"] is False
    dates = [p["date"] for p in d["points"]]
    assert dates == sorted(dates), "序列必须升序（前端直接画走势）"
    assert len(d["points"]) == 30
    assert [c["window"] for c in d["changes"]] == ["1w", "1m", "3m", "1y"]


async def test_inventory_far_windows_have_baselines(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """400 天历史 → 1w/1m/3m/1y 四个窗口**全部**有基线。

    这是 V0.115.0 修掉的那个 bug 的回归断言：回看起点原先锚在 ``today - 365d``，
    而最新观测常比今天早 2-3 天（交易日频），于是「1 年前」的点被推出查询窗口，
    1y 恒为 null —— 而 1m/3m 看着都正常，只有最长的那个窗口悄悄空着。
    """
    await _seed(db_session, _flat(400, start_t=1100.0, step=0.75))

    resp = await client.get(URL, params={"days": 90})
    d = resp.json()
    for c in d["changes"]:
        assert c["change_pct"] is not None, f"{c['window']} 窗口缺基线"
        assert c["base_date"] is not None


async def test_inventory_short_history_leaves_far_windows_null(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """历史只够 1m → 1w/1m 有值，3m/1y 返回 null（**不是 0**）。

    ⚠ ``_flat(35)`` 不是随手写的：``_flat(n)`` 覆盖的是 ``TODAY-(n-1)`` 到
    ``TODAY``，也就是 **n-1** 天跨度。给 30 就只有 29 天，1m 的基线
    （``TODAY-30``）刚好落在窗口外 —— 第一版就是这么写的，断言红了才发现。
    """
    await _seed(db_session, _flat(35))

    resp = await client.get(URL, params={"days": 90})
    by = {c["window"]: c for c in resp.json()["changes"]}
    assert by["1w"]["change_pct"] is not None
    assert by["1m"]["change_pct"] is not None
    assert by["3m"]["change_pct"] is None
    assert by["1y"]["change_pct"] is None


async def test_inventory_days_param_bounds(client: AsyncClient) -> None:
    """days 越界 → 422（FastAPI Query 校验），不是静默夹到边界。"""
    for bad in (10, 900, 0):
        resp = await client.get(URL, params={"days": bad})
        assert resp.status_code == 422, f"days={bad} 应被拒"


async def test_inventory_days_controls_points_length(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """``days`` 确实截**序列长度**（100 天历史 + days=30 → ≤31 点）。"""
    await _seed(db_session, _flat(100))
    resp = await client.get(URL, params={"days": 30})
    assert resp.status_code == 200
    assert len(resp.json()["points"]) <= 31


async def test_inventory_marks_stale_when_source_stopped(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """最新观测 10 天前 → degraded=true（源停更，页面须能提示）。"""
    rows = [
        {"inv_date": TODAY - timedelta(days=10 + i), "tonnes": 700.0 - i, "ounces": None}
        for i in range(20)
    ]
    await _seed(db_session, rows)
    resp = await client.get(URL, params={"days": 90})
    d = resp.json()
    assert d["degraded"] is True
    assert d["as_of"] == (TODAY - timedelta(days=10)).isoformat()


async def test_inventory_route_does_not_shadow_siblings(client: AsyncClient) -> None:
    """新增 ``/gold/inventory`` 没把邻近的 gold 端点顶掉。

    ⚠ 不是 paranoia：这些都是**字面路径**，同组已有 7 个（``/gold``、
    ``/gold/etf-quote``、``/gold/gram-quote``、``/gold/trend``、``/gold/ny-trend``、
    ``/gold/compare``）。插一条进去若写错顺序，FastAPI 首个匹配即返回，
    症状是「某个老端点突然返回库存字段」，从报错上完全看不出来。
    """
    for path in ("/api/v1/market/gold", "/api/v1/market/gold/gram-quote"):
        r = await client.get(path)
        assert r.status_code == 200, path
        assert "latest_tonnes" not in r.json(), f"{path} 被 inventory 端点遮蔽了"