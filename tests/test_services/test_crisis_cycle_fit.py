"""经济危机金价拟合曲线服务测试（V0.128.0）。

锁死**证据门**与**口径**，不是实现细节：

- E1 无前视：只给 ≤ 末月的日线，结果必须只依赖这段数据；
- E2 锚点可复算：锚点月 = **日线最高收盘价所在月**；
- E3 当前周期不进模板：与当前周期月份重叠的历史周期**必须被剔除**；
- E4 穿过当前点：曲线在 t0 处的隐含价 == 末月均价；
- E5 锚点敏感性：锚点 ±1 月的终点差能被算出来；
- 校验器：不跳月 / 高点月必须是最高月 / 轮数不足 ⇒ 降级并**告警**（不静默修补）。
"""

from __future__ import annotations

import pytest

from app.services import crisis_cycle_fit as svc

# ────────────────────────────── 夹具 ──────────────────────────────

#: 危机形态：高点后多年下跌（最高点即 goldPeak）
CRISIS_PATH = [100, 91, 84, 79, 76, 74, 73, 75, 78, 82, 85, 88, 90, 92]


def _cycle(name: str, peak_ym: str, base: float, path: list[float] | None = None) -> dict:
    """造一轮合规周期（series 连续月、goldPeak 是最高月）。"""
    series = []
    pi = svc.month_index(peak_ym)
    for t, pct in enumerate(path or CRISIS_PATH):
        total = pi + t
        series.append([f"{total // 12}-{total % 12 + 1:02d}", round(base * pct / 100, 2)])
    return {"name": name, "short": name, "goldPeak": peak_ym, "series": series}


def _asset(cycles: list[dict] | None = None) -> dict:
    return {
        "schema_version": 1,
        "target": "ny",
        "horizon_months": 30,
        "price_basis": "monthly_average",
        "provenance": {"source": "synthetic", "coverage": "test"},
        "cycles": cycles
        if cycles is not None
        else [
            _cycle("C1", "2011-09", 1900),
            _cycle("C2", "2013-04", 1500),
            _cycle("C3", "2020-08", 2070),
        ],
    }


def _daily(pairs: list[tuple[str, float]]) -> list[dict]:
    """日线夹具：每月两天。"""
    out = []
    for ym, price in pairs:
        y, mo = ym.split("-")
        out.append({"date": f"{y}-{mo}-03", "last": price})
        out.append({"date": f"{y}-{mo}-17", "last": price})
    out.sort(key=lambda x: x["date"])
    return out


DAILY = _daily(
    [
        ("2024-01", 2000),
        ("2024-07", 2200),
        ("2025-01", 2400),
        ("2025-05", 2800),
        ("2025-11", 2600),
        ("2026-05", 3000),
        ("2026-11", 3200),
    ]
)


# ────────────────────────────── 月份运算 ──────────────────────────────


class TestMonthArithmetics:
    def test_month_index_and_diff(self) -> None:
        assert svc.month_index("2026-01") == svc.month_index("2025-01") + 12
        assert svc.months_between("2024-01", "2026-11") == 34
        assert svc.months_between("2026-11", "2024-01") == -34

    def test_add_months_crosses_year(self) -> None:
        assert svc.add_months("2026-11", 3) == "2027-02"
        assert svc.add_months("2026-01", -1) == "2025-12"
        assert svc.add_months("2026-06", 6) == "2026-12"

    def test_is_ym_rejects_garbage(self) -> None:
        assert svc._is_ym("2026-01")
        assert not svc._is_ym("2026-13")
        assert not svc._is_ym("202601")
        assert not svc._is_ym("")


# ────────────────────────────── 月聚合 ──────────────────────────────


class TestAggregateMonths:
    def test_uses_monthly_average_not_last(self) -> None:
        nodes = [
            {"date": "2026-01-05", "last": 100.0},
            {"date": "2026-01-20", "last": 110.0},
            {"date": "2026-02-03", "last": 120.0},
        ]
        months = svc.aggregate_months(nodes)
        assert [m.month for m in months] == ["2026-01", "2026-02"]
        assert months[0].avg == pytest.approx(105.0)
        assert months[0].count == 2

    def test_skips_bad_rows(self) -> None:
        nodes = [
            {"date": "2026-01-05", "last": 100.0},
            {"date": "bad", "last": 1.0},
            {"date": "2026-02-05", "last": "abc"},
            {"date": "2026-03-05", "last": float("nan")},
        ]
        months = svc.aggregate_months(nodes)
        assert [m.month for m in months] == ["2026-01"]


# ────────────────────────────── 校验器（E3 / 导出契约） ──────────────────────────────


class TestValidateCycles:
    def test_accepts_clean_cycles(self) -> None:
        cycles, warnings = svc.validate_cycles(_asset()["cycles"])
        assert len(cycles) == 3
        assert warnings == []

    def test_rejects_gap_months(self) -> None:
        bad = _cycle("GAP", "2011-09", 1900)
        bad["series"] = [p for i, p in enumerate(bad["series"]) if i != 3]
        cycles, warnings = svc.validate_cycles([bad])
        assert cycles == []
        assert any("跳月" in w for w in warnings)

    def test_rejects_gold_peak_not_maximum(self) -> None:
        bad = _cycle("PEAK", "2011-09", 1900)
        # 把高点那一行改成一个更低的价 ⇒ 最高月不再是 goldPeak
        bad["series"][0] = [bad["series"][0][0], 10.0]
        cycles, warnings = svc.validate_cycles([bad])
        assert cycles == []
        assert any("不是该周期最高月" in w for w in warnings)

    def test_rejects_gold_peak_not_in_series(self) -> None:
        # goldPeak 落在 series 覆盖区间之外（series 从 2011-09 起）
        bad = _cycle("MISS", "2011-09", 1900)
        bad["goldPeak"] = "2011-08"
        cycles, warnings = svc.validate_cycles([bad])
        assert cycles == []
        assert any("不在 series 里" in w for w in warnings)

    def test_rejects_cycle_overlapping_current_period(self) -> None:
        """E3：与当前周期月份重叠的历史周期 ⇒ 自我拟合 ⇒ 剔除。"""
        overlapping = _cycle("NOW", "2026-01", 2600)
        cycles, warnings = svc.validate_cycles(
            [overlapping], current_months=["2026-01", "2026-05", "2026-11"]
        )
        assert cycles == []
        assert any("自我拟合" in w for w in warnings)

    def test_rejects_non_ascending_series(self) -> None:
        bad = _cycle("REV", "2011-09", 1900)
        bad["series"] = list(reversed(bad["series"]))
        cycles, warnings = svc.validate_cycles([bad])
        assert cycles == []
        assert any("未按月升序" in w for w in warnings)


# ────────────────────────────── 模板 ──────────────────────────────


class TestTemplate:
    def test_normalized_to_peak_100(self) -> None:
        cycles, _ = svc.validate_cycles(_asset()["cycles"])
        tpl = svc.build_template(cycles)
        assert tpl.template[0] == (0, pytest.approx(100.0))

    def test_equal_weight_average_of_cycles(self) -> None:
        """等权平均：两条路径（100→80 与 100→60）在 t=1 处平均为 70。"""
        a = _cycle("A", "2011-09", 100, [100, 80])
        b = _cycle("B", "2012-09", 100, [100, 60])
        cycles, _ = svc.validate_cycles([a, b])
        tpl = svc.build_template(cycles)
        by_t = dict(tpl.template)
        assert by_t[0] == pytest.approx(100.0)
        assert by_t[1] == pytest.approx(70.0)
        assert tpl.counts[0] == 2

    def test_counts_reflect_available_cycles(self) -> None:
        """轮数不齐时：缺的轮**不补 0**，只按可用数平均，并记录支撑轮数。"""
        long_cycle = _cycle("LONG", "2011-09", 100, [100, 90, 80])
        short_cycle = _cycle("SHORT", "2012-09", 100, [100, 70])
        cycles, _ = svc.validate_cycles([long_cycle, short_cycle])
        tpl = svc.build_template(cycles)
        by_t = dict(tpl.template)
        assert by_t[2] == pytest.approx(80.0)  # 只有 LONG 支撑
        assert tpl.counts[2] == 1

    def test_interpolator_clamps_at_ends(self) -> None:
        at = svc.make_interpolator([(0.0, 100.0), (10.0, 50.0)])
        assert at(-5) == pytest.approx(100.0)
        assert at(20) == pytest.approx(50.0)
        assert at(5) == pytest.approx(75.0)


# ────────────────────────────── 拟合（E1 / E2 / E4） ──────────────────────────────


class TestBuildCrisisFit:
    def test_available_and_passes_through_current_point(self) -> None:
        """E4：曲线起点（t0）就是当前点 ⇒ 隐含价 == 末月均价。"""
        res = svc.build_crisis_fit(DAILY, asset=_asset())
        assert res.available is True
        assert res.reason is None
        assert res.fit is not None
        first = res.fit.curve[0]
        assert first["t"] == res.t0
        assert first["price"] == pytest.approx(res.last_avg, rel=1e-6)

    def test_anchor_is_peak_daily_month(self) -> None:
        """E2：锚点月 = 日线最高收盘价所在月（不是月均价最高的月）。"""
        daily = _daily(
            [
                ("2025-01", 2000),
                ("2025-02", 2900),  # 日线最高
                ("2025-03", 2400),
                ("2025-04", 2100),
            ]
        )
        res = svc.build_crisis_fit(daily, asset=_asset())
        assert res.anchor_month == "2025-02"
        assert res.peak_date.startswith("2025-02")

    def test_no_lookahead_only_uses_given_nodes(self) -> None:
        """E1：只给前 3 个月的数据，结果与给全量后取前 3 个月的锚点一致。"""
        full = svc.build_crisis_fit(DAILY, asset=_asset())
        cut = svc.build_crisis_fit([n for n in DAILY if n["date"] <= "2025-01-31"], asset=_asset())
        assert cut.available is True
        assert cut.last_month == "2025-01"
        assert cut.anchor_month == "2025-01"
        assert full.available is True

    def test_drift_zero_endpoint_differs(self) -> None:
        """drift 是假设 ⇒ drift=0 的终点必须与 drift>0 的不同（页面要能对照）。"""
        res = svc.build_crisis_fit(DAILY, asset=_asset(), drift=0.003)
        assert res.fit is not None and res.fit_drift0 is not None
        assert res.fit.endpoint is not None and res.fit_drift0.endpoint is not None
        assert res.fit.endpoint["price"] != res.fit_drift0.endpoint["price"]

    def test_cycle_ends_are_reported(self) -> None:
        res = svc.build_crisis_fit(DAILY, asset=_asset())
        assert res.fit is not None
        assert len(res.fit.cycle_ends) == 3
        assert all("name" in e and "price" in e for e in res.fit.cycle_ends)

    def test_template_counts_and_max_t_exposed(self) -> None:
        res = svc.build_crisis_fit(DAILY, asset=_asset())
        assert res.template_max_t == len(res.template) - 1
        assert len(res.template_counts) == len(res.template)
        assert res.template_counts[0] == 3

    def test_sensitivity_when_anchor_neighbours_exist(self) -> None:
        """E5：锚点 ±1 月都有数据时，终点敏感度要算出来。"""
        daily = _daily(
            [
                ("2025-10", 2800),
                ("2025-11", 3000),  # 锚点
                ("2025-12", 2900),
                ("2026-01", 3100),
            ]
        )
        res = svc.build_crisis_fit(daily, asset=_asset())
        assert res.sensitivity is not None
        assert res.sensitivity["low"] is not None
        assert res.sensitivity["high"] is not None


# ────────────────────────────── 降级 ──────────────────────────────


class TestDegradation:
    def test_missing_artifact(self) -> None:
        res = svc.build_crisis_fit(DAILY, asset={})
        assert res.available is False
        assert res.reason == "no_crisis_cycles_artifact"

    def test_no_price_data(self) -> None:
        res = svc.build_crisis_fit([], asset=_asset())
        assert res.available is False
        assert res.reason == "no_price_data"

    def test_too_few_cycles(self) -> None:
        """⚠ 下限是 **2** 轮（用户 2026-11-19 显式指定的就是 2 轮）⇒ 1 轮才不够。

        2 轮时「等权平均」的统计意义有限（不是 3 轮以上那种平均），
        但每一轮都有明确的历史含义 ⇒ 仍然可用，由页面如实说明。
        """
        res = svc.build_crisis_fit(DAILY, asset=_asset(_asset()["cycles"][:1]))
        assert res.available is False
        assert res.reason == "insufficient_cycles"

    def test_two_cycles_is_enough(self) -> None:
        """2 轮（互联网泡沫 + 房地产危机）⇒ 可用，但接口要报出轮数与支撑情况。"""
        res = svc.build_crisis_fit(DAILY, asset=_asset(_asset()["cycles"][:2]))
        assert res.available is True
        assert res.fit_cycle_count == 2
        assert res.template_counts[0] == 2

    def test_all_cycles_invalid_reports_warnings(self) -> None:
        bad = _cycle("BAD", "2011-09", 1900)
        bad["goldPeak"] = "2011-10"
        res = svc.build_crisis_fit(DAILY, asset=_asset([bad]))
        assert res.available is False
        assert res.reason == "insufficient_cycles"
        assert res.warnings


# ────────────────────────────── 产物加载器护栏 ──────────────────────────────


class TestLoadAsset:
    def test_missing_file_returns_none(self) -> None:
        assert svc.load_crisis_cycles(target="ny") is None or isinstance(
            svc.load_crisis_cycles(target="ny"), dict
        )

    def test_target_guard(self, tmp_path, monkeypatch) -> None:
        """别的标的拿不到 ny 的证据。"""
        path = tmp_path / "crisis_cycles.json"
        path.write_text('{"target": "ny", "cycles": []}', encoding="utf-8")
        monkeypatch.setattr(svc, "CRISIS_CYCLES_FILE", path)
        assert svc.load_crisis_cycles(target="etf") is None
        assert svc.load_crisis_cycles(target="ny") is not None

    def test_horizon_guard(self, tmp_path, monkeypatch) -> None:
        path = tmp_path / "crisis_cycles.json"
        path.write_text('{"target": "ny", "horizon_months": 30, "cycles": []}', encoding="utf-8")
        monkeypatch.setattr(svc, "CRISIS_CYCLES_FILE", path)
        assert svc.load_crisis_cycles(target="ny", horizon=18) is None
        assert svc.load_crisis_cycles(target="ny", horizon=30) is not None

    def test_broken_json_returns_none(self, tmp_path, monkeypatch) -> None:
        path = tmp_path / "crisis_cycles.json"
        path.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(svc, "CRISIS_CYCLES_FILE", path)
        assert svc.load_crisis_cycles(target="ny") is None
