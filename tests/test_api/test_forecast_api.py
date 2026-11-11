"""金价区间预测接口测试（V0.127.0）。

锁死接口层的**契约**（不是实现细节）：

- ``drift_mode`` 恒为 ``"none"`` —— 接口不做方向预测；
- ``base_close`` 就是区间中心；
- ``measured.out_of_sample`` 是**实测**覆盖率，且**不等于**名义覆盖率；
- 不支持的覆盖率 ⇒ 400（不是 500，也不是悄悄换个值）；
- 数据不足 ⇒ 400 + 明确文案（前端据此显示「样本不足」，而不是画一条假带）。
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.review import GoldPriceRepository


def _closes(n: int = 400, seed: int = 3) -> list[float]:
    """确定性合成价格序列（不用随机数 ⇒ 每次跑结果一致）。"""
    out = [2000.0]
    state = seed
    for _ in range(n - 1):
        state = (state * 1103515245 + 12345) % (2**31)
        u1 = (state % 100000) / 100000.0 or 0.5
        state = (state * 1103515245 + 12345) % (2**31)
        u2 = (state % 100000) / 100000.0 or 0.5
        z = math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)
        out.append(out[-1] * math.exp(0.0003 + 0.013 * z))
    return out


async def _seed(db: AsyncSession, n: int = 400) -> list[date]:
    today = date.today()
    start = today - timedelta(days=n)
    bars = [(start + timedelta(days=i), c) for i, c in enumerate(_closes(n))]
    await GoldPriceRepository(db).upsert_many(target="ny", bars=bars, source="test")
    return [b[0] for b in bars]


@pytest.fixture()
async def seeded(db_session: AsyncSession) -> list[date]:
    return await _seed(db_session)


class TestPriceForecastEndpoint:
    async def test_returns_band(self, client: AsyncClient, seeded: list[date]) -> None:
        r = await client.get("/api/v1/forecast/price?target=ny&horizon=20&coverage=0.8")
        assert r.status_code == 200
        d = r.json()
        assert d["target"] == "ny"
        assert d["horizon"] == 20
        assert d["coverage"] == 0.8
        assert len(d["points"]) == 20
        assert d["lower"] < d["base_close"] < d["upper"]

    async def test_no_drift(self, client: AsyncClient, seeded: list[date]) -> None:
        """E5：中心 = 最新收盘价，且 drift_mode 恒为 none。"""
        r = await client.get("/api/v1/forecast/price")
        d = r.json()
        assert d["drift_mode"] == "none"
        assert d["base_close"] == d["points"][0]["lower"] * 0 + d["base_close"]
        # 上下沿关于基准价对称（对数空间）
        assert d["lower"] * d["upper"] == pytest.approx(d["base_close"] ** 2, rel=1e-3)

    async def test_measured_coverage_is_not_nominal(
        self, client: AsyncClient, seeded: list[date]
    ) -> None:
        """E4：返回的是实测覆盖率，不能是名义值。"""
        r = await client.get("/api/v1/forecast/price?coverage=0.8")
        d = r.json()
        measured = d["measured"]
        assert measured["nominal"] == 0.8
        assert measured["out_of_sample"] is not None
        assert measured["out_of_sample"] != measured["nominal"]
        assert measured["n_out_of_sample"] > 0

    async def test_points_are_widening(self, client: AsyncClient, seeded: list[date]) -> None:
        """扇形必须越走越宽。"""
        r = await client.get("/api/v1/forecast/price")
        widths = [p["upper"] - p["lower"] for p in r.json()["points"]]
        assert widths == sorted(widths)

    async def test_future_dates_are_weekdays(self, client: AsyncClient, seeded: list[date]) -> None:
        r = await client.get("/api/v1/forecast/price")
        dates = [date.fromisoformat(p["date"]) for p in r.json()["points"]]
        assert all(d.weekday() < 5 for d in dates)
        assert dates == sorted(dates)

    @pytest.mark.parametrize("cov", [0.5, 0.8, 0.9, 0.98])
    async def test_supported_coverages(
        self, client: AsyncClient, seeded: list[date], cov: float
    ) -> None:
        r = await client.get(f"/api/v1/forecast/price?coverage={cov}")
        assert r.status_code == 200
        d = r.json()
        assert d["coverage"] == cov
        assert d["lower"] < d["upper"]

    async def test_wider_coverage_is_wider(self, client: AsyncClient, seeded: list[date]) -> None:
        narrow = (await client.get("/api/v1/forecast/price?coverage=0.5")).json()
        wide = (await client.get("/api/v1/forecast/price?coverage=0.9")).json()
        narrow_w = narrow["upper"] - narrow["lower"]
        wide_w = wide["upper"] - wide["lower"]
        assert narrow_w < wide_w

    async def test_unsupported_coverage_is_400(
        self, client: AsyncClient, seeded: list[date]
    ) -> None:
        r = await client.get("/api/v1/forecast/price?coverage=0.73")
        assert r.status_code == 400
        assert "0.8" in r.json()["detail"]

    async def test_unknown_target_is_422(self, client: AsyncClient, seeded: list[date]) -> None:
        r = await client.get("/api/v1/forecast/price?target=xxx")
        assert r.status_code == 422

    async def test_horizon_out_of_range_is_422(
        self, client: AsyncClient, seeded: list[date]
    ) -> None:
        r = await client.get("/api/v1/forecast/price?horizon=999")
        assert r.status_code == 422

    async def test_no_data_is_400_with_reason(self, client: AsyncClient) -> None:
        """没有价格日历时 ⇒ 400 + 说明，不是 500，也不是一条假带。"""
        r = await client.get("/api/v1/forecast/price?target=gram")
        assert r.status_code == 400
        assert "gram" in r.json()["detail"]

    async def test_cross_check_fields_present(
        self, client: AsyncClient, seeded: list[date]
    ) -> None:
        r = await client.get("/api/v1/forecast/price")
        cc = r.json()["cross_check"]
        assert "status" in cc
        assert "ratio" in cc
        assert "normal_band" in cc


class TestCalibrationEndpoint:
    async def test_returns_artifact(self, client: AsyncClient) -> None:
        r = await client.get("/api/v1/forecast/calibration?target=ny")
        assert r.status_code == 200
        d = r.json()
        assert d["available"] is True
        assert "80" in d["coverages"]
        entry = d["coverages"]["80"]
        assert entry["out_of_sample"] is not None
        assert entry["out_of_sample"] != entry["nominal"]
        assert d["cross_check"]["p05"] < d["cross_check"]["p95"]

    async def test_missing_artifact_is_flagged(self, client: AsyncClient) -> None:
        r = await client.get("/api/v1/forecast/calibration?target=gram")
        assert r.status_code == 200
        d = r.json()
        assert d["available"] is False
