"""经济危机金价拟合曲线接口测试（V0.128.0）。

锁死接口层的**契约**：

- **没有周期产物 ⇒ available=false + 明确 reason**（不是 500，也不是画一条假线）；
- 有产物时：``curve`` 穿过当前点、``endpoint_drift0`` 必须给出（drift 是假设 ⇒ 要有对照）、
  ``cycle_ends`` 给出离散区间、``provenance`` 透传、``warnings`` 透传；
- 参数越界 ⇒ 422；标的非法 ⇒ 422；
- ⚠ 响应里**不得**出现「看多/看空/目标价」这类语义字段（方向性判断不属于本接口）。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.review import GoldPriceRepository
from app.services import crisis_cycle_fit as svc

CRISIS_PATH = [100, 91, 84, 79, 76, 74, 73, 75, 78, 82, 85, 88, 90, 92]


def _cycle(name: str, peak_ym: str, base: float) -> dict:
    series = []
    pi = svc.month_index(peak_ym)
    for t, pct in enumerate(CRISIS_PATH):
        total = pi + t
        series.append([f"{total // 12}-{total % 12 + 1:02d}", round(base * pct / 100, 2)])
    return {"name": name, "short": name, "goldPeak": peak_ym, "series": series}


ASSET = {
    "schema_version": 1,
    "target": "ny",
    "horizon_months": 30,
    "provenance": {"source": "synthetic", "coverage": "2011-01 → 2021-12"},
    "cycles": [
        _cycle("C1", "2011-09", 1900),
        _cycle("C2", "2013-04", 1500),
        _cycle("C3", "2020-08", 2070),
    ],
}


@pytest.fixture()
async def seeded(db_session: AsyncSession) -> None:
    """塞 24 个月的月均价日线（每月两天）。"""
    today = date.today()
    bars = []
    for i in range(24):
        d = date(today.year, today.month, 1) - timedelta(days=30 * i)
        bars.append((d, 2000.0 + i * 20.0))
    await GoldPriceRepository(db_session).upsert_many(target="ny", bars=bars, source="test")


class TestCrisisFitEndpoint:
    async def test_degrades_without_artifact(
        self, client: AsyncClient, seeded, monkeypatch
    ) -> None:
        """没有产物 ⇒ available=false + reason（前端据此显示「待数据」）。

        ⚠ 显式 stub 成「没有产物」，**不要**依赖仓库里恰好没有产物文件 ——
        哪天周期数据入库了，这条用例就会假红。
        """
        monkeypatch.setattr(svc, "load_crisis_cycles", lambda **kw: None)
        r = await client.get("/api/v1/forecast/crisis-fit?target=ny")
        assert r.status_code == 200
        d = r.json()
        assert d["available"] is False
        assert d["reason"]
        assert d["curve"] == []

    async def test_available_path_contract(self, client: AsyncClient, seeded, monkeypatch) -> None:
        monkeypatch.setattr(svc, "load_crisis_cycles", lambda **kw: ASSET)
        r = await client.get("/api/v1/forecast/crisis-fit?target=ny&horizon=24")
        assert r.status_code == 200
        d = r.json()
        assert d["available"] is True
        assert d["reason"] is None
        assert d["horizon_months"] == 24
        assert len(d["curve"]) == 25
        assert d["curve"][0]["price"] == pytest.approx(d["last_avg"], rel=1e-6)
        # ★ drift 是假设 ⇒ 必须同时给出 drift=0 的对照
        assert d["endpoint_drift0"] is not None
        assert d["endpoint"] is not None
        assert d["endpoint"]["price"] != d["endpoint_drift0"]["price"]
        # 单周期终点区间
        assert len(d["cycle_ends"]) == 3
        # provenance 透传
        assert d["provenance"]["source"] == "synthetic"
        # 模板支撑轮数 + clamp 边界
        assert d["template_max_t"] == len(d["template"]) - 1
        assert len(d["template_counts"]) == len(d["template"])

    async def test_target_guard_blocks_other_targets(
        self, client: AsyncClient, seeded, monkeypatch
    ) -> None:
        """产物是 ny 的 ⇒ 别的标的拿不到（把 ny 的证据说成别的标的的证据 = 说谎）。"""
        monkeypatch.setattr(
            svc, "load_crisis_cycles", lambda **kw: ASSET if kw.get("target") == "ny" else None
        )
        r = await client.get("/api/v1/forecast/crisis-fit?target=etf")
        assert r.status_code == 200
        assert r.json()["available"] is False

    async def test_bad_horizon_is_422(self, client: AsyncClient) -> None:
        assert (await client.get("/api/v1/forecast/crisis-fit?horizon=1")).status_code == 422
        assert (await client.get("/api/v1/forecast/crisis-fit?horizon=999")).status_code == 422

    async def test_bad_drift_is_422(self, client: AsyncClient) -> None:
        assert (await client.get("/api/v1/forecast/crisis-fit?drift=0.5")).status_code == 422
        assert (await client.get("/api/v1/forecast/crisis-fit?drift=-0.5")).status_code == 422

    async def test_bad_target_is_422(self, client: AsyncClient) -> None:
        assert (await client.get("/api/v1/forecast/crisis-fit?target=xxx")).status_code == 422

    async def test_fit_window_excludes_reference_cycles(self, client: AsyncClient, seeded) -> None:
        """★ 拟合窗口收窄（V0.128.1）：模板**只**用拟合窗口内的周期。

        ⚠ 这条断言必须放在**API 用例**里（而不是浏览器门禁）：门禁 mock 了接口 ⇒
        后端混进参照集它看不见（实测踩过：反向验证时门禁照样 46/0 全绿）。
        """
        r = await client.get("/api/v1/forecast/crisis-fit?target=ny&horizon=30")
        assert r.status_code == 200
        d = r.json()
        asset = svc.load_crisis_cycles(target="ny", horizon=30)
        assert asset is not None
        n_fit = len(asset.get("cycles") or [])
        n_ref = len(asset.get("reference_cycles") or [])
        # ⚠ 拟合集现在只有 2 轮（用户 2026-11-19 显式指定）⇒ 下限是 2 不是 3
        assert n_fit >= 2 and n_ref >= 1
        # 模板只由拟合集构成 ⇒ t=0 的支撑轮数 == 拟合轮数（不是拟合+参照）
        assert d["template_counts"][0] == n_fit, (
            f"模板混进了参照集：t=0 支撑 {d['template_counts'][0]} 轮，拟合集只有 {n_fit} 轮"
        )
        assert len(d["cycle_paths"]) == n_fit
        # 参照集单独给出来（只展示，不进模板）
        assert len(d["reference_paths"]) == n_ref
        assert d["fit_window"].get("start")
        assert d["reference_window"].get("start")

    async def test_support_at_horizon_is_reported(self, client: AsyncClient, seeded) -> None:
        """外推终点的支撑轮数必须报出来（薄了页面要能告警）。"""
        r = await client.get("/api/v1/forecast/crisis-fit?target=ny&horizon=30")
        d = r.json()
        assert d["support_at_horizon"] is not None
        assert d["support_at_horizon"] >= 1

    async def test_fit_set_is_explicitly_specified(self, client: AsyncClient, seeded) -> None:
        """★ 拟合集是**显式指定**的那 2 轮（用户 2026-11-19 拍板），不是自动挑的。

        ⚠ 这条断言放在 **API 用例**里（浏览器门禁 mock 了接口 ⇒ 后端混进别的周期它看不见）。
        """
        r = await client.get("/api/v1/forecast/crisis-fit?target=ny&horizon=30")
        assert r.status_code == 200
        d = r.json()
        asset = svc.load_crisis_cycles(target="ny", horizon=30)
        assert asset is not None
        assert d["fit_selection"] == "explicit"
        assert d["fit_anchors"] == ["1999-10", "2008-03"]
        assert d["fit_cycle_count"] == 2
        # 模板只由这 2 轮构成
        assert len(d["cycle_paths"]) == 2
        assert d["template_counts"][0] == 2
        # 锚点与名字都要对得上（页面要显示「拟合的是哪两轮」）
        anchors = [p.get("anchor") for p in d["cycle_paths"]]
        assert anchors == ["1999-10", "2008-03"]
        names = " ".join(p["name"] for p in d["cycle_paths"])
        assert "互联网" in names and "房地产" in names

    async def test_reference_cycles_are_era_labelled(self, client: AsyncClient, seeded) -> None:
        """参照集分两类：2000 年前（参考性最低）与 2000 年后未入选（对照用）。"""
        r = await client.get("/api/v1/forecast/crisis-fit?target=ny&horizon=30")
        d = r.json()
        refs = d["reference_paths"]
        assert refs, "参照集不该为空"
        eras = {p.get("era") for p in refs}
        assert "pre_2000" in eras
        # pre_2000 的必须带「参考性最低」的理由
        weak = [p for p in refs if p.get("era") == "pre_2000"]
        assert all(p.get("reason") for p in weak)
        # 参照集**不进**模板
        assert d["template_counts"][0] == d["fit_cycle_count"]

    async def test_endpoint_beyond_template_is_flagged(self, client: AsyncClient, seeded) -> None:
        """★ 终点落在模板覆盖之外时**必须报出来**（平台外推 ⇒ 那里没有历史信息）。"""
        r = await client.get("/api/v1/forecast/crisis-fit?target=ny&horizon=30")
        d = r.json()
        assert d["template_max_t"] is not None
        end_t = (d["t0"] or 0) + d["horizon_months"]
        expect = end_t > d["template_max_t"]
        assert d["endpoint_beyond_template"] is expect, (
            f"终点 t={end_t} / 模板到 t={d['template_max_t']} ⇒ "
            f"endpoint_beyond_template 应为 {expect}"
        )

    async def test_no_directional_semantics(self, client: AsyncClient, seeded, monkeypatch) -> None:
        """⚠ 接口不得输出方向性判断字段（那是另一个功能的事）。"""
        monkeypatch.setattr(svc, "load_crisis_cycles", lambda **kw: ASSET)
        r = await client.get("/api/v1/forecast/crisis-fit?target=ny")
        keys = set(r.json().keys())
        forbidden = {"signal", "direction", "bullish", "bearish", "target_price", "recommendation"}
        assert not (keys & forbidden)
