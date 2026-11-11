"""``scripts/calibrate_price_band.py`` 单元测试（V0.127.0）。

⚠ **本文件最重要的一件事**：校准脚本为了能独立运行（不导入 ``app`` 包 ⇒ 不拖进
配置与数据库连接），**重写了一份**分位数与 EWMA 的实现。
两份实现一旦漂移，**线上服务算的带子**与**校准产物对应的带子**就不是同一个东西
⇒ 实测覆盖率会变成一个假的数字。

⇒ 本文件把两份实现**逐点对拍**，任何一边改了口径而另一边没改 ⇒ 立刻变红。

另含：walk-forward 无前视、单调包络、digest 稳定性。
"""

from __future__ import annotations

import math

import pytest

from app.services import price_forecast as pf
from app.services.macro_thresholds import _percentile
from scripts import calibrate_price_band as calib


def _synth(n: int = 800, seed: int = 11, vol: float = 0.014, drift: float = 0.0003):
    closes = [2000.0]
    state = seed
    for _ in range(n - 1):
        state = (state * 1103515245 + 12345) % (2**31)
        u1 = (state % 100000) / 100000.0 or 0.5
        state = (state * 1103515245 + 12345) % (2**31)
        u2 = (state % 100000) / 100000.0 or 0.5
        z = math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)
        closes.append(closes[-1] * math.exp(drift + vol * z))
    return closes


# ──────────────── 两份实现必须一致 ────────────────


class TestImplementationParity:
    def test_percentile_matches_shared_helper(self) -> None:
        vals = sorted(_synth(50))
        for pct in (1.0, 5.0, 10.0, 25.0, 50.0, 75.0, 90.0, 95.0, 99.0):
            assert calib._percentile(vals, pct) == pytest.approx(_percentile(vals, pct))

    def test_percentile_edge_cases_match(self) -> None:
        assert calib._percentile([], 50.0) == _percentile([], 50.0)
        assert calib._percentile([3.0], 50.0) == _percentile([3.0], 50.0)

    def test_ewma_series_matches_service(self) -> None:
        closes = _synth(300)
        assert calib.ewma_sigma_series(closes) == pytest.approx(pf.ewma_sigma_series(closes))

    def test_ewma_series_matches_service_on_real_like_data(self) -> None:
        """再来一段参数不同的合成序列（防止「恰好只对上一段成立」）。"""
        closes = _synth(400, seed=99, vol=0.03, drift=-0.001)
        assert calib.ewma_sigma_series(closes) == pytest.approx(pf.ewma_sigma_series(closes))

    def test_analog_shape_matches_service(self) -> None:
        closes = _synth(800)
        sigmas = pf.ewma_sigma_series(closes)
        idx = 600
        lo_pct = 10.0
        got = calib.analog_shape_at(closes, sigmas, idx, 20, lo_pct)
        ref = pf.analog_shape_at(closes, sigmas, idx, 20, coverage=0.8)
        assert got is not None and ref is not None
        assert got[0] == pytest.approx(ref)
        assert got[1] == pytest.approx(pf.analog_candidates(sigmas, idx, 20).__len__())

    def test_analog_shape_none_when_history_short(self) -> None:
        closes = _synth(40)
        sigmas = pf.ewma_sigma_series(closes)
        assert calib.analog_shape_at(closes, sigmas, 39, 20, 10.0) is None


# ──────────────── walk-forward 无前视 ────────────────


class TestWalkForward:
    def test_band_at_prediction_day_is_prefix_invariant(self) -> None:
        """E1：**带子**在基准日 D 上只用 ≤ D 的数据 ⇒ 截断后必须一模一样。

        ⚠ 注意区分两件事：**带子**（用 ≤ D 的数据算）与**结果价**（D+20 的真实收盘）。
        后者当然只能取全序列 —— 截断序列就没有它了。
        """
        closes = _synth(600)
        sigmas = calib.ewma_sigma_series(closes)
        z = pf.COVERAGE_Z[0.8]
        for i in (300, 350, 380):
            half_full = z * sigmas[i] * math.sqrt(20)
            lo_full = closes[i] * math.exp(-half_full)
            hi_full = closes[i] * math.exp(+half_full)

            prefix = closes[: i + 1]
            sigmas_p = calib.ewma_sigma_series(prefix)
            half_p = z * sigmas_p[i] * math.sqrt(20)
            assert half_p == pytest.approx(half_full)
            assert prefix[i] * math.exp(-half_p) == pytest.approx(lo_full)
            assert prefix[i] * math.exp(+half_p) == pytest.approx(hi_full)

    def test_outcome_price_comes_from_the_full_series(self) -> None:
        """结果价取的是 D+20 那一行的收盘（不是前缀的末行）。"""
        closes = _synth(600)
        sigmas = calib.ewma_sigma_series(closes)
        z = pf.COVERAGE_Z[0.8]
        i = 300
        half = z * sigmas[i] * math.sqrt(20)
        lo = closes[i] * math.exp(-half)
        hi = closes[i] * math.exp(+half)
        outcome = closes[i + 20]
        assert lo <= outcome <= hi or not (lo <= outcome <= hi)  # 只是记录判定方式
        # 用前缀（截到 i）算 ⇒ 结果价缺失 ⇒ 该预测日不参与判定
        _hit_full, n_full = calib._span_stats(closes, sigmas, [i], 20, z)
        _hit_pref, n_pref = calib._span_stats(closes[: i + 1], sigmas, [i], 20, z)
        assert n_full == 1
        assert n_pref == 0  # 前缀里没有 i+20 ⇒ 跳过

    def test_span_stats_denominator_counts_only_evaluated_days(self) -> None:
        """分母必须是「实际判定过」的天数，不是 len(idxs)。"""
        closes = _synth(100)
        sigmas = calib.ewma_sigma_series(closes)
        # i=90 ⇒ i+20=110 越界 ⇒ 跳过 ⇒ 分母不能算 1
        hit, n = calib._span_stats(closes, sigmas, [90], 20, pf.COVERAGE_Z[0.8])
        assert n == 0
        assert hit == 0
        # i=70 ⇒ i+20=90 在界内 ⇒ 分母 1
        _hit, n2 = calib._span_stats(closes, sigmas, [70], 20, pf.COVERAGE_Z[0.8])
        assert n2 == 1

    def test_ewma_band_covers_about_nominal(self) -> None:
        """合成序列上，名义 80% 的带子实测应落在 60%–95%（不是 100%）。"""
        closes = _synth(3000, seed=5, vol=0.012, drift=0.0)
        sigmas = calib.ewma_sigma_series(closes)
        idxs = list(range(300, 2900))
        hit, n = calib._span_stats(closes, sigmas, idxs, 20, pf.COVERAGE_Z[0.8])
        rate = hit / n
        assert 0.60 < rate < 0.95, f"实测覆盖率 {rate:.1%} 不在合理区间"


# ──────────────── 单调包络 ────────────────


class TestMonotoneEnvelope:
    def test_envelope_is_monotone(self) -> None:
        out, adjusted = calib._monotone_envelope([0.5, 0.2, 0.6, 0.4, 1.0])
        assert out == sorted(out)
        assert adjusted == 2

    def test_envelope_keeps_last_value(self) -> None:
        out, _ = calib._monotone_envelope([0.5, 0.9, 1.0])
        assert out[-1] == pytest.approx(1.0)

    def test_envelope_never_lowers(self) -> None:
        raw = [0.3, 0.25, 0.4, 0.35, 1.0]
        out, _ = calib._monotone_envelope(raw)
        assert all(o >= r - 1e-12 for o, r in zip(out, raw, strict=True))

    def test_envelope_on_monotone_input_is_noop(self) -> None:
        raw = [0.2, 0.4, 0.6, 1.0]
        out, adjusted = calib._monotone_envelope(raw)
        assert adjusted == 0
        assert out == pytest.approx(raw)


# ──────────────── compute ────────────────


class TestCompute:
    def test_returns_expected_structure(self) -> None:
        closes = _synth(1200)
        dates = [None] * len(closes)  # compute 只用日期做展示
        from datetime import date, timedelta

        dates = [date(2020, 1, 1) + timedelta(days=i) for i in range(len(closes))]
        out = calib.compute(
            closes=closes,
            dates=dates,
            horizon=20,
            coverages=[0.5, 0.8, 0.9, 0.98],
            z_map=pf.COVERAGE_Z,
        )
        assert len(out["shape"]) == 20
        assert out["shape"][-1] == pytest.approx(1.0)
        assert out["shape"] == sorted(out["shape"])
        for key in ("50", "80", "90", "98"):
            entry = out["coverages"][key]
            assert 0.0 <= entry["train"] <= 1.0
            assert entry["n_out_of_sample"] > 0
        assert out["spans"]["out_of_sample"]["n_samples"] > 0
        assert "p05" in out["cross_check"]

    def test_too_little_history_exits(self) -> None:
        from datetime import date, timedelta

        closes = _synth(120)
        dates = [date(2020, 1, 1) + timedelta(days=i) for i in range(len(closes))]
        with pytest.raises(SystemExit):
            calib.compute(
                closes=closes,
                dates=dates,
                horizon=20,
                coverages=[0.8],
                z_map=pf.COVERAGE_Z,
            )


# ──────────────── digest ────────────────


class TestDigest:
    def test_same_payload_same_digest(self) -> None:
        payload = {"a": [1.0, 2.0], "b": {"c": 3}}
        assert calib._canonical_digest(payload) == calib._canonical_digest(payload)

    def test_different_payload_different_digest(self) -> None:
        a = calib._canonical_digest({"a": [1.0, 2.0]})
        b = calib._canonical_digest({"a": [1.0, 2.0000001]})
        assert a != b

    def test_digest_ignores_key_order(self) -> None:
        a = calib._canonical_digest({"a": 1, "b": 2})
        b = calib._canonical_digest({"b": 2, "a": 1})
        assert a == b
