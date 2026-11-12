"""金价区间预测服务（V0.127.0）单元测试 —— 锁死六条证据门。

六条门（计划 §六）在这里逐条落地，**每条都做过反向验证**（改坏 ⇒ 必须变红）：

===========  ==========================================  ==============================
门           断言                                        反向验证（改坏 ⇒ 变红）
===========  ==========================================  ==============================
E1 无前视    截断基准日之后的数据 ⇒ 带子逐字段不变      把 σ 改成全样本 ⇒ 变红
E2 相似日    候选集里没有 ``s + horizon > idx`` 的下标    去掉 ``s + horizon <= idx`` ⇒ 变红
E3 宽度口径  覆盖率档 ↔ z 值一一对应                     改 z 表 ⇒ 变红
E4 实测值    校准产物里的实测值 ≠ 名义值（不许被顶掉）    把实测写成名义值 ⇒ 变红
E5 中心无漂移 中心 == 最新收盘价、``drift_mode="none"``   偷偷加漂移 ⇒ 变红
E6 降级可见  相似日不足 ⇒ 标 ``vol_only`` + 原因          把 ``None`` 当 0 ⇒ 变红
===========  ==========================================  ==============================

⚠ 本文件**不联网、不碰数据库** —— 全部用合成序列（可注入 ``today``，不写死日期）。
"""

from __future__ import annotations

import json
import math

import pytest

from app.services import price_forecast as pf
from app.services.macro_thresholds import _percentile


def _synth(n: int = 600, seed: int = 7, vol: float = 0.012, drift: float = 0.0004):
    """造一段确定性的合成价格序列（含轻微趋势与波动）。"""
    closes = [2000.0]
    state = seed
    for _ in range(n - 1):
        state = (state * 1103515245 + 12345) % (2**31)
        u1 = (state % 100000) / 100000.0 or 0.5
        state = (state * 1103515245 + 12345) % (2**31)
        u2 = (state % 100000) / 100000.0 or 0.5
        # Box-Muller
        z = math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)
        closes.append(closes[-1] * math.exp(drift + vol * z))
    return closes


# ──────────────── E1 无前视 ────────────────


class TestNoLookahead:
    def test_truncating_after_base_day_changes_nothing(self) -> None:
        """E1：把基准日之后的数据全删掉，带子必须**一模一样**。"""
        closes = _synth(400)
        idx = 300
        full = pf.build_band(closes, horizon=20, coverage=0.8, base_idx=idx)
        truncated = pf.build_band(closes[: idx + 1], horizon=20, coverage=0.8)
        assert full.points == truncated.points
        assert full.lower == pytest.approx(truncated.lower)
        assert full.upper == pytest.approx(truncated.upper)
        assert full.sigma == pytest.approx(truncated.sigma)
        assert full.method == truncated.method

    def test_future_data_cannot_change_the_base_close(self) -> None:
        """基准日之后的价格即使暴涨，也不该影响任何输出。"""
        closes = _synth(400)
        idx = 300
        tampered = list(closes)
        tampered[idx + 1 :] = [99999.0] * (len(tampered) - idx - 1)
        a = pf.build_band(closes, horizon=20, coverage=0.8, base_idx=idx)
        b = pf.build_band(tampered, horizon=20, coverage=0.8, base_idx=idx)
        assert a.points == b.points
        assert a.base_close == b.base_close == closes[idx]

    def test_sigma_series_is_causal(self) -> None:
        """σ 序列逐点只依赖历史：截断后前缀必须一致。"""
        closes = _synth(200)
        full = pf.ewma_sigma_series(closes)
        part = pf.ewma_sigma_series(closes[:120])
        assert full[:120] == pytest.approx(part)


# ──────────────── E2 相似日不越界 ────────────────


class TestAnalogCandidates:
    def test_candidates_never_cross_the_base_day(self) -> None:
        """E2：候选日 s 必须满足 s + horizon <= idx。"""
        closes = _synth(500)
        sigmas = pf.ewma_sigma_series(closes)
        for idx in (200, 300, 400):
            cands = pf.analog_candidates(sigmas, idx, horizon=20)
            assert cands, "合成序列上应能找到相似日"
            assert max(cands) + 20 <= idx

    def test_candidate_exactly_at_the_boundary_is_allowed(self) -> None:
        """边界：s + horizon == idx 是**允许**的（路径整体在基准日之前）。"""
        closes = _synth(500)
        sigmas = pf.ewma_sigma_series(closes)
        idx = 300
        cands = pf.analog_candidates(sigmas, idx, horizon=20)
        assert max(cands) == idx - 20 or max(cands) < idx - 20

    def test_boundary_day_is_excluded_when_horizon_grows(self) -> None:
        """反向验证：horizon 变大 ⇒ 可用的相似日变少（越界日被剔除）。"""
        closes = _synth(500)
        sigmas = pf.ewma_sigma_series(closes)
        idx = 300
        c20 = pf.analog_candidates(sigmas, idx, horizon=20)
        c40 = pf.analog_candidates(sigmas, idx, horizon=40)
        assert set(c40) < set(c20)
        assert max(c40) + 40 <= idx

    def test_analog_band_is_none_when_history_is_short(self) -> None:
        closes = _synth(40)
        sigmas = pf.ewma_sigma_series(closes)
        assert pf.analog_band(closes, sigmas, 39, horizon=20, min_sim=30) is None


# ──────────────── E3 覆盖率 ↔ z ────────────────


class TestCoverageZ:
    @pytest.mark.parametrize(
        ("cov", "z"),
        [
            (0.50, 0.6744897501960817),
            (0.80, 1.2815515655446004),
            (0.90, 1.6448536269514722),
            (0.98, 2.3263478740408408),
        ],
    )
    def test_z_values(self, cov: float, z: float) -> None:
        assert pf.COVERAGE_Z[cov] == pytest.approx(z)

    def test_unsupported_coverage_is_rejected(self) -> None:
        closes = _synth(200)
        with pytest.raises(ValueError):
            pf.build_band(closes, coverage=0.73)

    def test_wider_coverage_gives_wider_band(self) -> None:
        """覆盖率越大 ⇒ 带越宽（单调）。"""
        closes = _synth(400)
        widths = [
            pf.build_band(closes, coverage=c, base_idx=300).upper
            - pf.build_band(closes, coverage=c, base_idx=300).lower
            for c in (0.5, 0.8, 0.9, 0.98)
        ]
        assert widths == sorted(widths)
        assert widths[0] < widths[-1]


# ──────────────── E4 实测覆盖率不是名义值 ────────────────


class TestMeasuredCoverage:
    def _calib(self) -> dict:
        return {
            "target": "ny",
            "coverages": {
                "80": {
                    "nominal": 0.8,
                    "train": 0.767,
                    "out_of_sample": 0.779,
                    "recent": 0.771,
                }
            },
        }

    def test_reads_measured_values(self) -> None:
        spans = pf.measured_coverage(self._calib(), 0.8)
        assert spans["out_of_sample"] == pytest.approx(0.779)
        assert spans["train"] == pytest.approx(0.767)

    def test_headline_prefers_out_of_sample(self) -> None:
        assert pf.measured_coverage_of(self._calib(), 0.8) == pytest.approx(0.779)

    def test_measured_value_is_not_replaced_by_nominal(self) -> None:
        """E4：实测值必须原样透出 —— 不能被名义值顶掉。"""
        calib = self._calib()
        got = pf.measured_coverage_of(calib, 0.8)
        assert got != calib["coverages"]["80"]["nominal"]
        assert got == pytest.approx(0.779)

    def test_missing_calibration_returns_none(self) -> None:
        assert pf.measured_coverage_of(None, 0.8) is None
        assert pf.measured_coverage_of({"coverages": {}}, 0.8) is None


# ──────────────── E5 中心无漂移 ────────────────


class TestNoDrift:
    def test_center_equals_latest_close(self) -> None:
        closes = _synth(300)
        band = pf.build_band(closes, horizon=20, coverage=0.8)
        assert band.base_close == closes[-1]
        assert band.drift_mode == "none"

    def test_band_is_symmetric_in_log_space_around_base_close(self) -> None:
        closes = _synth(300)
        band = pf.build_band(closes, horizon=20, coverage=0.8)
        for pt in band.points:
            assert pt.lower * pt.upper == pytest.approx(band.base_close**2, rel=1e-9)

    def test_horizon_endpoint_is_lower_upper(self) -> None:
        closes = _synth(300)
        band = pf.build_band(closes, horizon=20, coverage=0.8)
        assert band.points[-1].k == 20
        assert band.lower == band.points[-1].lower
        assert band.upper == band.points[-1].upper

    def test_points_count_equals_horizon(self) -> None:
        closes = _synth(300)
        band = pf.build_band(closes, horizon=20, coverage=0.8)
        assert len(band.points) == 20
        assert [p.k for p in band.points] == list(range(1, 21))


# ──────────────── E6 降级可见 ────────────────


class TestDegradation:
    def test_insufficient_analogs_falls_back_to_vol_only(self) -> None:
        """历史太短 ⇒ 相似日不足 ⇒ 标 vol_only + 给出原因（不是画假带）。"""
        closes = _synth(60)
        band = pf.build_band(closes, horizon=20, coverage=0.8)
        assert band.method == "vol_only"
        assert band.reason
        assert band.shape_source == "cone"

    def test_missing_shape_falls_back_to_cone(self) -> None:
        """形状曲线缺失 ⇒ 用 √k 锥，并标注来源。"""
        closes = _synth(300)
        band = pf.build_band(closes, horizon=20, coverage=0.8, shape=None)
        assert band.shape_source == "cone"
        assert band.method in {"vol_only", "ewma"}

    def test_shape_present_is_used(self) -> None:
        closes = _synth(300)
        shape = pf.cone_shape(20)
        band = pf.build_band(closes, horizon=20, coverage=0.8, shape=shape)
        assert band.shape_source == "analog"

    def test_too_short_series_raises(self) -> None:
        with pytest.raises(ValueError):
            pf.build_band([100.0])

    def test_base_idx_without_history_raises(self) -> None:
        closes = _synth(100)
        with pytest.raises(ValueError):
            pf.build_band(closes, base_idx=0)


# ──────────────── 形状曲线 ────────────────


class TestShape:
    def test_cone_shape_normalized(self) -> None:
        cone = pf.cone_shape(20)
        assert len(cone) == 20
        assert cone[-1] == pytest.approx(1.0)
        assert cone[0] == pytest.approx(math.sqrt(1 / 20))

    def test_analog_shape_normalized_to_one(self) -> None:
        closes = _synth(500)
        sigmas = pf.ewma_sigma_series(closes)
        shape = pf.analog_shape_at(closes, sigmas, 400, horizon=20)
        assert shape is not None
        assert shape[-1] == pytest.approx(1.0)
        assert all(v > 0 for v in shape)
        # 短期不应比长期更宽
        assert shape[0] < shape[-1]

    def test_shape_widens_with_horizon(self) -> None:
        """带子必须越走越宽（否则「导航线」是反的）。"""
        closes = _synth(300)
        band = pf.build_band(closes, horizon=20, coverage=0.8)
        widths = [pt.upper - pt.lower for pt in band.points]
        assert widths == sorted(widths)


# ──────────────── 分位数复用 ────────────────


class TestPercentileReuse:
    def test_uses_shared_percentile_helper(self) -> None:
        """类比带的分位必须与 ``macro_thresholds._percentile`` 同口径。"""
        closes = _synth(300)
        sigmas = pf.ewma_sigma_series(closes)
        band = pf.analog_band(closes, sigmas, 280, horizon=20, coverage=0.8)
        assert band is not None

        cands = pf.analog_candidates(sigmas, 280, horizon=20)
        vals = sorted(
            math.log(closes[s + 20] / closes[s])  # 每个相似日的 20 日相对路径
            for s in cands
            if closes[s] > 0 and closes[s + 20] > 0
        )
        assert band.lower_path[-1] == pytest.approx(_percentile(vals, 10.0))
        assert band.upper_path[-1] == pytest.approx(_percentile(vals, 90.0))


# ──────────────── 交易日外推 ────────────────


class TestProjectTradingDates:
    def test_skips_weekend(self) -> None:
        from datetime import date

        # 2026-11-13 是周五
        out = pf.project_trading_dates(date(2026, 11, 13), 3)
        assert out == [date(2026, 11, 16), date(2026, 11, 17), date(2026, 11, 18)]

    def test_all_weekdays(self) -> None:
        from datetime import date

        out = pf.project_trading_dates(date(2026, 11, 13), 10)
        assert all(d.weekday() < 5 for d in out)
        assert len(out) == 10


# ──────────────── 产物读取的健壮性 ────────────────


class TestArtifactLoading:
    def test_missing_shape_returns_none(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(pf, "SHAPE_FILE", tmp_path / "nope.json")
        assert pf.load_shape(20) is None

    def test_broken_shape_json_returns_none(self, tmp_path, monkeypatch) -> None:
        p = tmp_path / "shape.json"
        p.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(pf, "SHAPE_FILE", p)
        assert pf.load_shape(20) is None

    def test_shape_with_wrong_horizon_rejected(self, tmp_path, monkeypatch) -> None:
        p = tmp_path / "shape.json"
        p.write_text('{"horizon": 10, "shape": [1,2,3]}', encoding="utf-8")
        monkeypatch.setattr(pf, "SHAPE_FILE", p)
        assert pf.load_shape(20) is None

    def test_shape_with_nonpositive_values_rejected(self, tmp_path, monkeypatch) -> None:
        p = tmp_path / "shape.json"
        p.write_text(
            '{"horizon": 20, "shape": ' + str([0.5] * 18 + [0.0, 1.0]) + "}", encoding="utf-8"
        )
        monkeypatch.setattr(pf, "SHAPE_FILE", p)
        assert pf.load_shape(20) is None

    def test_shape_is_forced_monotone(self, tmp_path, monkeypatch) -> None:
        """非单调的形状必须被取包络（扇形要越走越宽）。"""
        p = tmp_path / "shape.json"
        p.write_text(
            '{"horizon": 20, "shape": ' + str([0.5, 0.2] + [0.6] * 17 + [1.0]) + "}",
            encoding="utf-8",
        )
        monkeypatch.setattr(pf, "SHAPE_FILE", p)
        got = pf.load_shape(20)
        assert got is not None
        assert got == sorted(got)

    def test_valid_shape_loaded(self, tmp_path, monkeypatch) -> None:
        p = tmp_path / "shape.json"
        p.write_text('{"horizon": 20, "shape": ' + str([0.3] * 19 + [1.0]) + "}", encoding="utf-8")
        monkeypatch.setattr(pf, "SHAPE_FILE", p)
        got = pf.load_shape(20)
        assert got is not None and got[-1] == 1.0

    def test_shape_of_another_target_is_rejected(self, tmp_path, monkeypatch) -> None:
        """V0.127.0：形状曲线是**按标的**校准的 ⇒ 标的不符必须退回 √k 锥。

        ⚠ 拿 ny 的形状去画 etf / gram 的扇形 = 「把别的标的的证据说成这个标的的证据」。
        """
        p = tmp_path / "shape.json"
        p.write_text(
            '{"target": "ny", "horizon": 20, "shape": ' + str([0.3] * 19 + [1.0]) + "}",
            encoding="utf-8",
        )
        monkeypatch.setattr(pf, "SHAPE_FILE", p)
        assert pf.load_shape(20, target="ny") is not None
        assert pf.load_shape(20, target="etf") is None
        assert pf.load_shape(20, target="gram") is None
        # 不传 target（老调用方）⇒ 不做标的护栏
        assert pf.load_shape(20) is not None

    def test_calibration_target_mismatch_returns_none(self, monkeypatch, tmp_path) -> None:
        p = tmp_path / "calibration.json"
        p.write_text('{"target": "etf"}', encoding="utf-8")
        monkeypatch.setattr(pf, "CALIBRATION_FILE", p)
        assert pf.load_calibration("ny") is None


class TestShapeStability:
    """V0.127.1：跨窗口形状稳定性（页面「已知失效条件」第 4 条的证据来源）。

    ⚠ 页面上的跨窗口倍数以前是**写死**的 ⇒ 产物重算后会静默变成假话。
    现在它由接口给出原始曲线，页面**现算**（shape ÷ cone）。
    """

    @staticmethod
    def _write(tmp_path, monkeypatch, payload: dict) -> None:
        p = tmp_path / "shape.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setattr(pf, "SHAPE_FILE", p)

    @staticmethod
    def _shape(v: float) -> list[float]:
        return [v] * 19 + [1.0]

    def test_loaded_from_artifact(self, tmp_path, monkeypatch) -> None:
        self._write(
            tmp_path,
            monkeypatch,
            {
                "target": "ny",
                "horizon": 20,
                "shape": self._shape(0.3),
                "shape_stability": {
                    "train": {"n_days": 1992, "shape": self._shape(0.22)},
                    "recent_600": {"n_days": 577, "shape": self._shape(0.28)},
                },
            },
        )
        got = pf.load_shape_stability(20, target="ny")
        assert got is not None
        assert set(got) == {"train", "recent_600"}
        assert got["train"]["n_days"] == 1992
        assert len(got["train"]["shape"]) == 20
        assert got["recent_600"]["n_days"] == 577

    def test_missing_block_returns_none(self, tmp_path, monkeypatch) -> None:
        self._write(
            tmp_path,
            monkeypatch,
            {"target": "ny", "horizon": 20, "shape": self._shape(0.3)},
        )
        assert pf.load_shape_stability(20, target="ny") is None

    def test_broken_json_returns_none(self, tmp_path, monkeypatch) -> None:
        p = tmp_path / "shape.json"
        p.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(pf, "SHAPE_FILE", p)
        assert pf.load_shape_stability(20, target="ny") is None

    def test_horizon_guard(self, tmp_path, monkeypatch) -> None:
        self._write(
            tmp_path,
            monkeypatch,
            {
                "target": "ny",
                "horizon": 10,
                "shape": [0.3] * 9 + [1.0],
                "shape_stability": {
                    "train": {"n_days": 5, "shape": [0.3] * 9 + [1.0]},
                },
            },
        )
        assert pf.load_shape_stability(20, target="ny") is None

    def test_target_guard(self, tmp_path, monkeypatch) -> None:
        """⚠ 与 :func:`load_shape` **同一套**标的护栏。

        稳定性证据同样是**按标的**校准出来的 ⇒ 拿 ny 的跨窗口证据去讲 etf 的故事
        = 「把别的标的的证据说成这个标的的证据」。
        """
        self._write(
            tmp_path,
            monkeypatch,
            {
                "target": "ny",
                "horizon": 20,
                "shape": self._shape(0.3),
                "shape_stability": {
                    "train": {"n_days": 1992, "shape": self._shape(0.22)},
                },
            },
        )
        assert pf.load_shape_stability(20, target="ny") is not None
        assert pf.load_shape_stability(20, target="etf") is None
        assert pf.load_shape_stability(20, target="gram") is None
        # 不传 target（老调用方）⇒ 不做标的护栏
        assert pf.load_shape_stability(20) is not None

    def test_bad_window_is_dropped(self, tmp_path, monkeypatch) -> None:
        """某个窗口的 shape 不是数组 / 长度不对 / 有非正值 ⇒ 丢**该窗口**，不影响别的窗口。"""
        self._write(
            tmp_path,
            monkeypatch,
            {
                "target": "ny",
                "horizon": 20,
                "shape": self._shape(0.3),
                "shape_stability": {
                    "train": {"n_days": 1992, "shape": [1, 2, 3]},
                    "bad": {"n_days": 1, "shape": [0.0] * 19 + [1.0]},
                    "recent_600": {"n_days": 577, "shape": self._shape(0.28)},
                },
            },
        )
        got = pf.load_shape_stability(20, target="ny")
        assert got is not None
        assert set(got) == {"recent_600"}

    def test_all_windows_bad_returns_none(self, tmp_path, monkeypatch) -> None:
        self._write(
            tmp_path,
            monkeypatch,
            {
                "target": "ny",
                "horizon": 20,
                "shape": self._shape(0.3),
                "shape_stability": {"train": {"n_days": 1, "shape": [1, 2, 3]}},
            },
        )
        assert pf.load_shape_stability(20, target="ny") is None
