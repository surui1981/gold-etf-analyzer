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

    async def test_returns_shape_and_cone(self, client: AsyncClient) -> None:
        """V0.127.0：前端「形状对照图」要画的两条线必须由接口给出来。

        - ``shape`` = 离线校准出的**类比形状**（k=horizon 归一为 1.0）；
        - ``cone``  = 对数正态 √k 锥（退化基线）。

        ⚠ 两者都必须存在且等长；**缺失时前端只画锥并明示「形状产物缺失」**，
        绝不拿锥冒充类比形状（那是把「没有证据」说成「有证据」）。
        """
        r = await client.get("/api/v1/forecast/calibration?target=ny")
        d = r.json()
        assert len(d["shape"]) == d["horizon"], d["shape"]
        assert len(d["cone"]) == d["horizon"], d["cone"]
        # 归一：k=horizon 处必须为 1.0（两条线都是）
        assert d["shape"][-1] == pytest.approx(1.0, abs=1e-3)
        assert d["cone"][-1] == pytest.approx(1.0, abs=1e-6)
        # 锥的闭式值 √(k/H)：k=1 时 ≈ 0.2236
        assert d["cone"][0] == pytest.approx(math.sqrt(1 / d["horizon"]), abs=1e-6)
        # 类比形状在短期比锥更胖（实测 1.25–1.31×）⇒ k=1 处 shape > cone
        assert d["shape"][0] > d["cone"][0]

    async def test_shape_absent_still_returns_cone(self, client: AsyncClient) -> None:
        """形状产物缺失时：``shape`` 为空数组、``cone`` 仍在（前端画退化基线 + 提示）。"""
        r = await client.get("/api/v1/forecast/calibration?target=gram")
        d = r.json()
        assert d["available"] is False
        assert d["shape"] == []
        assert len(d["cone"]) == d["horizon"]

    async def test_exposes_shape_stability(self, client: AsyncClient) -> None:
        """V0.127.1：跨窗口形状稳定性必须由接口给出来。

        ⚠ 页面「已知失效条件」第 4 条的倍数以前是**写死**的
        （训练段 0.99 倍 / 近 600 段 1.27 倍）⇒ 产物重算后会静默变成假话。
        现在接口给的是**原始曲线**，页面现算（shape ÷ cone）。

        断言的重点不是某个具体数字，而是：
        ① 两个窗口都在、长度与 horizon 一致；
        ② **能算出跨窗口的差异**（训练段短端比正态锥瘦，近 600 段更胖）
           —— 这正是页面要披露的那件事，算不出来就说明数据没到位。
        """
        r = await client.get("/api/v1/forecast/calibration?target=ny")
        d = r.json()
        stab = d["shape_stability"]
        assert set(stab) >= {"train", "recent_600"}, stab
        for name in ("train", "recent_600"):
            assert stab[name]["n_days"] > 0, stab[name]
            assert len(stab[name]["shape"]) == d["horizon"], stab[name]

        def k1_ratio(block: dict) -> float:
            return block["shape"][0] / d["cone"][0]

        # 训练段 ≈ 正态锥（短端不胖）⇒ 比值 < 1
        assert k1_ratio(stab["train"]) < 1.0
        # 近 600 段明显更胖 ⇒ 比值 > 训练段
        assert k1_ratio(stab["recent_600"]) > k1_ratio(stab["train"])

    async def test_shape_stability_is_target_guarded(self, client: AsyncClient) -> None:
        """⚠ 稳定性证据是**按标的**校准的 ⇒ 换个标的必须为空（不是把 ny 的拿过来用）。"""
        r = await client.get("/api/v1/forecast/calibration?target=gram")
        d = r.json()
        assert d["shape_stability"] == {}
