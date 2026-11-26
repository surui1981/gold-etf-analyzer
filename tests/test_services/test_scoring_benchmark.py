"""命中率「基准对照」的单测（V0.128.5 · 改进③）。

动机：命中率**单看一个数没有意义**。在一段单边下跌里「恒看跌」能拿 74%，
指数拿 72% 看着也不错，但它其实**不如闭眼猜**。⇒ 必须把基准算出来并排显示。

本文件锁死 ``compute_hit_benchmark`` 的口径：
- 三种常数策略（恒看涨 / 恒看跌 / 恒看平）都只依赖**实际涨跌**，不看指数；
- ``best_constant_rate`` = 三者最大 ⇒「闭眼猜的上限」；
- 样本为空时全部为 None（不返回 0 —— 0 会被读成「命中率 0%」）。
"""

from __future__ import annotations

import pytest

from app.services.scoring_wide import compute_hit_benchmark


class TestComputeHitBenchmark:
    def test_empty_returns_all_none(self) -> None:
        out = compute_hit_benchmark([])
        assert out["sample_size"] == 0
        assert out["always_up_rate"] is None
        assert out["always_down_rate"] is None
        assert out["always_flat_rate"] is None
        assert out["best_constant_rate"] is None
        assert out["best_constant_label"] is None

    def test_all_up(self) -> None:
        out = compute_hit_benchmark([1.0, 2.0, 0.5])
        assert out["sample_size"] == 3
        assert out["always_up_rate"] == pytest.approx(1.0)
        assert out["always_down_rate"] == pytest.approx(0.0)
        assert out["best_constant_rate"] == pytest.approx(1.0)
        assert out["best_constant_label"] == "always_up"

    def test_all_down(self) -> None:
        out = compute_hit_benchmark([-1.0, -2.0])
        assert out["always_down_rate"] == pytest.approx(1.0)
        assert out["best_constant_label"] == "always_down"

    def test_flat_uses_neutral_band(self) -> None:
        """|涨跌幅| ≤ 0.3%（NEUTRAL_BAND_PCT）算「平」——与 ``judge_hit`` 同一口径。

        ⚠ 三个常数策略是**独立的**（不是互斥分区）：
        涨 0.1% 既算「恒看涨」命中（>0）也算「恒看平」命中（|0.1| ≤ 0.3）
        —— 这正是 ``judge_hit`` 的语义 ⇒ 每个策略各自是一个真实可用的下注方式。
        """
        out = compute_hit_benchmark([0.1, -0.2, 0.0, 1.0])
        # 平：0.1 / -0.2 / 0.0 三个在带内
        assert out["always_flat_rate"] == pytest.approx(0.75)
        # 涨：0.1 与 1.0 都 > 0（judge_hit 的看多命中条件就是 > 0）
        assert out["always_up_rate"] == pytest.approx(0.5)
        # 跌：只有 -0.2
        assert out["always_down_rate"] == pytest.approx(0.25)

    def test_best_constant_picks_max(self) -> None:
        out = compute_hit_benchmark([-1.0, -1.0, -1.0, 1.0])
        assert out["always_down_rate"] == pytest.approx(0.75)
        assert out["best_constant_label"] == "always_down"
        assert out["best_constant_rate"] == pytest.approx(0.75)

    def test_strategies_are_independent_not_a_partition(self) -> None:
        """⚠ 三个策略**会重叠**（不是互斥分区）⇒ 三率之和可以 > 1。

        这是刻意的：每个策略各自都是一种真实可用的「闭眼下注方式」，
        ``best_constant_rate`` = 其中最好的那个 = 「闭眼猜的上限」。
        """
        # 0.1 与 0.2 既 > 0（算「恒看涨」命中）又 |c| ≤ 0.3（算「恒看平」命中）
        changes = [0.1, 0.2, -3.0]
        out = compute_hit_benchmark(changes)
        # ⚠ 比率在实现里**四舍五入到 3 位** ⇒ 容差取 1e-3
        assert out["always_up_rate"] == pytest.approx(2 / 3, abs=1e-3)
        assert out["always_flat_rate"] == pytest.approx(2 / 3, abs=1e-3)
        assert out["always_down_rate"] == pytest.approx(1 / 3, abs=1e-3)
        # 两者之和 1.33 > 1 ⇒ 证明**不是**互斥分区
        assert out["always_up_rate"] + out["always_flat_rate"] > 1.0
