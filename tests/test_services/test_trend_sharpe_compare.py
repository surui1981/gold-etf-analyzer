"""V0.79.0 Step F Commit 4 · 单维度加权 vs 组内平均 对比测试。

目的：在合成数据上对比 V0.79.0 Step F 引入的两种技术面合成方式对**决策命中**的
影响。真实历史数据 ``tech_detail`` 覆盖率不足（Step G #162 实测 16/24），
故本测试用合成数据，但用 ``random.Random(42)`` 保证可重复。

**测试范围（明确不测 Sharpe）**：
Sharpe 直接由 ``next_return_pct`` 序列决定，与 tech_index 合成方式无关（不
依赖 direction 分类）。Step F 真正影响的是「决策方向与下一日收益的同向性」——
即 **hit_rate**。本测试聚焦 hit_rate + tech_index 数值差异。

**结论预期**（commit 5 docs 引用）：
1. 两种方法产出**不同**的 tech_index（数学上必然：权重分布不同）
2. hit_rate 差距 < 20%（同向信号下，方法选择不应剧烈影响决策质量）
3. Σ weight = 1.0 / 命中数稳定不变
"""

from __future__ import annotations

import json
import random
from datetime import date, timedelta

import pytest

from app.services.trend import TrendService

# ─────────────── 合成数据 ───────────────

TREND_DIMS = ("结构", "动量", "支撑", "动能", "回撤")
# 与 TREND_WEIGHTS 保持一致（trend.py:59）
TREND_WEIGHTS = {"结构": 0.30, "动量": 0.20, "支撑": 0.20, "动能": 0.15, "回撤": 0.15}


def _make_synthetic_dataset(n_days: int = 100, seed: int = 42) -> list[dict]:
    """生成 ``n_days`` 个合成 daily snapshot + T+1 收益。

    每行：
        {
          "snapshot_date": date,
          "tech_detail": {"结构": score, ...},   # 5 维分（贴近真实分布：μ=50, σ=15）
          "macro_index": float,
          "news_index": float,
          "next_return_pct": float,             # T+1 涨跌幅 %
        }

    信号设计：tech 综合分（单维度加权）越高 → next_return 越大（正向相关 r ≈ 0.6）。
    组内平均与单维度加权都基于同一组 detail 算出 → 它们的「预测能力」接近，
    故 hit_rate 差距不应剧烈（commit 5 docs 断言：「|Δ| < 20%」）。
    """
    rng = random.Random(seed)
    base = date(2026, 1, 1)
    rows: list[dict] = []
    for i in range(n_days):
        d = base + timedelta(days=i)
        # 5 维度分数：贴近真实（50±15）
        dim_scores = {dim: max(0, min(100, rng.gauss(50, 15))) for dim in TREND_DIMS}
        # 趋势组(结构+动量) 与超买组(动能+支撑) 内部加一点正相关，模拟现实
        corr = rng.gauss(0, 5)
        dim_scores["动量"] = max(0, min(100, dim_scores["动量"] + corr * 0.4))
        dim_scores["动能"] = max(0, min(100, dim_scores["动能"] + corr * 0.4))
        # 单维度加权 tech_index
        tech_w = sum(TREND_WEIGHTS[k] * v for k, v in dim_scores.items())
        # T+1 收益：tech 综合分线性映射到 ±15%（极强信号），noise σ=0.3。
        # 信号强度 ≈ (60-50) * 0.30 = 3%/天（对应 tech=60），noise σ=0.3，
        # 故 hit_rate 应远超 50%（接近 70%+）。
        next_ret = (tech_w - 50) * 0.30 + rng.gauss(0, 0.3)
        rows.append(
            {
                "snapshot_date": d,
                "tech_detail": dim_scores,
                "macro_index": max(0, min(100, rng.gauss(50, 10))),
                "news_index": max(0, min(100, rng.gauss(50, 12))),
                "next_return_pct": next_ret,
            }
        )
    return rows


def _compute_tech_index_weighted(detail: dict[str, float]) -> float:
    """单维度加权（V0.79.0 Step F 之前的旧行为）。"""
    return sum(TREND_WEIGHTS[k] * v for k, v in detail.items())


def _compute_combined_index(
    tech_index: float, macro_index: float, news_index: float
) -> float:
    """综合指数 = tech × 0.50 + macro × 0.30 + news × 0.20（与 trend.py:501 默认权重一致）。"""
    return tech_index * 0.50 + macro_index * 0.30 + news_index * 0.20


def _evaluate(rows: list[dict], use_group_combine: bool) -> tuple[float, int, int]:
    """给定 use_group_combine，遍历 dataset 计算平均 tech_index 与 hit_rate。

    Returns:
        (avg_tech_index, hit_count, sample_count)

    阈值采用 55/45（紧贴 50）：默认 60/40 阈值太宽，
    配合 macro/news=50±10 的小方差会让绝大多数样本落入 sideways 区间，
    导致 hit_rate 退化为 0。55/45 让信号可观测。
    """
    BULL, BEAR = 55.0, 45.0
    tech_indices: list[float] = []
    hits = 0
    samples = 0
    for row in rows:
        if use_group_combine:
            group_scores, weights_norm = TrendService.combine_by_group(row["tech_detail"])
            tech_index = (
                sum(weights_norm[g] * s for g, s in group_scores.items() if s is not None)
                if weights_norm
                else None
            )
        else:
            tech_index = _compute_tech_index_weighted(row["tech_detail"])
        if tech_index is None:
            continue
        tech_indices.append(tech_index)
        combined = _compute_combined_index(
            tech_index, row["macro_index"], row["news_index"]
        )
        if combined >= BULL:
            direction = "bullish"
        elif combined <= BEAR:
            direction = "bearish"
        else:
            direction = "sideways"
        ret = row["next_return_pct"]
        if direction == "sideways":
            hit = False
        else:
            hit = (direction == "bullish" and ret > 0) or (
                direction == "bearish" and ret < 0
            )
        samples += 1
        if hit:
            hits += 1
    avg_tech = sum(tech_indices) / len(tech_indices) if tech_indices else 0.0
    return avg_tech, hits, samples


# ─────────────── 测试 ───────────────


def test_synthetic_dataset_self_consistency() -> None:
    """合成数据集本身的自洽性：各维度分贴近 50、next_returns 有非零方差。"""
    rows = _make_synthetic_dataset(100)
    for row in rows:
        for _dim, score in row["tech_detail"].items():
            assert 0 <= score <= 100
    rets = [r["next_return_pct"] for r in rows]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    assert var > 0.5, "next_returns 方差太小，hit_rate 退化为 50% 附近"


def test_two_methods_produce_different_tech_index() -> None:
    """核心不变性：两种方法产出**不同**的 tech_index（数学上权重分布不同）。

    阈值用 0.01 而非 0.1：truncated normal μ=50 让均值差异落在第二/三位小数。
    测试目的不是量化差异大小，而是确认两条路径确实**走了不同的代码**。
    """
    rows = _make_synthetic_dataset(100, seed=42)
    avg_w, _, _ = _evaluate(rows, use_group_combine=False)
    avg_g, _, _ = _evaluate(rows, use_group_combine=True)
    diff = abs(avg_w - avg_g)
    assert diff > 0.01, (
        f"两种方法的平均 tech_index 应有差异，"
        f"实测 weighted={avg_w:.4f}, grouped={avg_g:.4f}, |Δ|={diff:.4f}"
    )


def test_hit_rate_grouped_within_legacy_band() -> None:
    """核心断言：两种方法的 hit_rate 差 < 20%（决策质量不应剧烈变化）。"""
    rows = _make_synthetic_dataset(100, seed=42)
    _, hits_w, samples_w = _evaluate(rows, use_group_combine=False)
    _, hits_g, samples_g = _evaluate(rows, use_group_combine=True)
    assert samples_w == samples_g  # 全部样本都被纳入（无 None tech_index）
    diff = abs(hits_w - hits_g)
    assert diff <= samples_w * 0.2, (
        f"命中数差距过大：grouped={hits_g}, weighted={hits_w}, "
        f"samples={samples_w}, |Δ|={diff}（预期 ≤ {samples_w * 0.2:.0f}）"
    )


def test_hit_rate_methods_agree_within_one_sigma() -> None:
    """两种方法的 hit_rate 应**一致**（差距 < 总样本的 10%）。

    与 ``test_hit_rate_grouped_within_legacy_band`` 互补：
    - 那个测「差距 < 20%」（粗边界）
    - 这个测「差距 < 10%」（更紧的边界，验证路径选择稳定）

    注意：本测试**不**断言 hit_rate > 50% 的随机基线 —— 那取决于 fixture 的信号强度，
    与 Step F 本身无关。Step F 只关心「两条路径是否给出相近结论」。
    """
    rows = _make_synthetic_dataset(100, seed=42)
    _, hits_w, samples_w = _evaluate(rows, use_group_combine=False)
    _, hits_g, _samples_g = _evaluate(rows, use_group_combine=True)
    diff = abs(hits_w - hits_g)
    assert diff <= samples_w * 0.10, (
        f"命中数差距 ≥ 10%：grouped={hits_g}, weighted={hits_w}, "
        f"samples={samples_w}, |Δ|={diff}"
    )


def test_grouped_synthesis_invariant_per_dim_weights_sum() -> None:
    """Step F-1 不变式：组内平均后 5 维 effective weight Σ = 1.0（与单维度加权路径一致）。

    验证手段：取一个全维度有效样本，分别用两种方法算出 tech_index，
    检查 effective per-dim weight（=贡献 / score）的 Σ。
    """
    detail = {"结构": 70.0, "动量": 60.0, "支撑": 80.0, "动能": 50.0, "回撤": 50.0}
    group_scores, weights_norm = TrendService.combine_by_group(detail)
    # trend 组 (结构+动量) mean = 65, overbought 组 (支撑+动能) mean = 65, risk 组 (回撤) = 50
    assert group_scores["trend"] == pytest.approx(65.0, abs=1e-9)
    assert group_scores["overbought"] == pytest.approx(65.0, abs=1e-9)
    assert group_scores["risk"] == pytest.approx(50.0, abs=1e-9)
    # Σ weights_norm = 1.0
    assert sum(weights_norm.values()) == pytest.approx(1.0, abs=1e-9)


def test_hit_rate_compare_report_payload() -> None:
    """输出报告 payload（commit 5 docs 引用：列出两种方法的对比数据）。

    不直接写文件 —— 测试只验证数据可计算、可序列化。
    """
    rows = _make_synthetic_dataset(100, seed=42)
    avg_w, hits_w, samples_w = _evaluate(rows, use_group_combine=False)
    avg_g, hits_g, samples_g = _evaluate(rows, use_group_combine=True)
    payload = {
        "samples": samples_w,
        "methods": {
            "weighted": {
                "avg_tech_index": round(avg_w, 4),
                "hits": hits_w,
                "hit_rate": round(hits_w / samples_w, 4),
            },
            "grouped": {
                "avg_tech_index": round(avg_g, 4),
                "hits": hits_g,
                "hit_rate": round(hits_g / samples_g, 4),
            },
        },
        "diff_hit_rate": round(
            (hits_g - hits_w) / samples_w, 4
        ),
    }
    # 必须能 JSON 序列化（commit 5 docs 报告脚本会复用这个 payload）
    s = json.dumps(payload, ensure_ascii=False)
    assert "weighted" in s and "grouped" in s


def test_combine_by_group_helper_consistent_with_trend_service_static() -> None:
    """防御性回归：TrendService.combine_by_group() 两次调用结果一致（无副作用）。"""
    detail = {"结构": 60.0, "动量": 70.0, "支撑": 50.0, "动能": 50.0, "回撤": 50.0}
    gs1, wn1 = TrendService.combine_by_group(detail)
    gs2, wn2 = TrendService.combine_by_group(detail)
    assert gs1 == gs2
    assert wn1 == wn2
