"""资金流面滚动分位阈值测试（V0.120.0）。

「资金流面」复用 ``services/macro_thresholds.py::MacroThresholdCalculator``，
但有三处**必须按资金流的节奏走**，否则整套机制是死的：

1. **窗口按因子取**：周频 104 周（728 日）、月频 60 月（1826 日）。
   沿用宏观面的 252 日窗口 ⇒ 周频只装得下 36 个观测、月频只有 8 个
   ⇒ 样本不足 ⇒ 阈值永远退回硬编码（V0.119.0 记过的同一个坑）。
2. **样本门槛按因子取**：每个因子有自己的 ``min_samples``。
3. **方向按符号约定**：`positive=False`（两个中国因子）⇒ best=P10、worst=P90。
   V0.118.0 修过一次「一律 best=P90」把 6 个负相关因子方向搞反的 bug ——
   资金流面若照抄，融资余额涨到天上去反而给 100 分「最利多黄金」。
"""

from __future__ import annotations

from datetime import date, timedelta

from app.services.macro_thresholds import MacroThresholdCalculator
from app.services.money_flow import MONEY_FLOW_FACTOR_RULES

RULE_BY_KEY = {r["key"]: r for r in MONEY_FLOW_FACTOR_RULES}
KEYS = list(RULE_BY_KEY)
TODAY = date(2026, 10, 27)


class _Sample:
    def __init__(self, value: float) -> None:
        self.value = value


class _Repo:
    """记录每个因子被请求的窗口长度。"""

    def __init__(self, samples: dict[str, list[float]] | None = None) -> None:
        self.samples = samples or {}
        self.calls: list[tuple[str, int]] = []

    async def get_window(self, *, target, factor_key, days, end_date):
        self.calls.append((factor_key, days))
        return [_Sample(v) for v in self.samples.get(factor_key, [])]


def _calc(repo) -> MacroThresholdCalculator:
    return MacroThresholdCalculator(
        repo=repo,
        rules=MONEY_FLOW_FACTOR_RULES,
        skip_rolling=frozenset(),
        window_days=252,
        min_samples=40,
    )


def _series(n: int, lo: float, hi: float, key: str) -> list[float]:
    """造 n 个在 [lo, hi] 线性分布的样本。"""
    if n <= 1:
        return [lo]
    step = (hi - lo) / (n - 1)
    return [lo + i * step for i in range(n)]


# ───────────────────── 1. 窗口按因子取 ─────────────────────


async def test_周频因子用728日窗口_月频用1826日():
    repo = _Repo({k: _series(200, 0, 1, k) for k in KEYS})
    calc = _calc(repo)
    await calc.get_or_compute("default", TODAY)
    got = dict(repo.calls)
    for k, r in RULE_BY_KEY.items():
        assert got.get(k) == r["window_days"], f"{k} 窗口应为 {r['window_days']}，实际 {got.get(k)}"


async def test_不沿用宏观面的252日窗口():
    """类级 window_days=252 只是默认值 —— 规则自带窗口必须优先。"""
    repo = _Repo({k: _series(200, 0, 1, k) for k in KEYS})
    calc = _calc(repo)
    await calc.get_or_compute("default", TODAY)
    assert all(days != 252 for _k, days in repo.calls)


# ───────────────────── 2. 样本门槛按因子取 ─────────────────────


async def test_样本不足时回退硬编码阈带():
    """周频 cot_gold_net 的 min_samples=60；只给 10 个样本 ⇒ 必须回退。"""
    repo = _Repo({k: _series(200, 0, 1, k) for k in KEYS if k != "cot_gold_net"})
    repo.samples["cot_gold_net"] = _series(10, 0, 1, "cot_gold_net")
    calc = _calc(repo)
    th = await calc.get_or_compute("default", TODAY)
    rule = RULE_BY_KEY["cot_gold_net"]
    assert th["cot_gold_net"] == (float(rule["best"]), float(rule["worst"]))
    # 其余因子样本充足 ⇒ 用滚动分位
    assert th["gold_etf_flow"] != (
        float(RULE_BY_KEY["gold_etf_flow"]["best"]),
        float(RULE_BY_KEY["gold_etf_flow"]["worst"]),
    )


async def test_样本刚好达标时启用滚动分位():
    repo = _Repo({k: _series(RULE_BY_KEY[k]["min_samples"], 0, 1, k) for k in KEYS})
    calc = _calc(repo)
    th = await calc.get_or_compute("default", TODAY)
    for k in KEYS:
        rule = RULE_BY_KEY[k]
        assert th[k] != (float(rule["best"]), float(rule["worst"])), k


async def test_月频因子的min_samples与周频不同():
    """月频门槛 60/36，周频 60/40 —— 门槛不同 ⇒ 同一份样本数下结论可能不同。"""
    assert RULE_BY_KEY["cn_money_gap"]["min_samples"] == 36
    assert RULE_BY_KEY["cot_gold_net"]["min_samples"] == 60
    assert RULE_BY_KEY["gold_etf_flow"]["min_samples"] == 40


# ───────────────────── 3. 方向按符号约定 ─────────────────────


async def test_正相关因子best取P90():
    repo = _Repo({k: _series(200, 0, 100, k) for k in KEYS})
    calc = _calc(repo)
    th = await calc.get_or_compute("default", TODAY)
    best, worst = th["cot_gold_net"]
    assert best > worst, "正相关因子：值越高越利多 ⇒ best 必须是大的一端"


async def test_负相关因子best取P10_方向不反():
    """机会成本口径的两个中国因子：best 必须是**小**的一端。

    ⚠ 这是 V0.118.0 修过的 bug 的同款：一旦照抄「一律 best=P90」，
    融资余额涨到历史高位反而给 100 分「最利多黄金」—— 方向整个反了。
    """
    repo = _Repo({k: _series(200, 0, 100, k) for k in KEYS})
    calc = _calc(repo)
    th = await calc.get_or_compute("default", TODAY)
    for k in ("cn_margin_flow", "cn_money_gap"):
        best, worst = th[k]
        assert best < worst, f"{k} 是负相关因子，best 必须是小的一端（实际 best={best}）"


# ───────────────────── 4. 动态/静态整体判定 ─────────────────────


async def test_全部因子动态时is_dynamic_active为真():
    repo = _Repo({k: _series(200, 0, 100, k) for k in KEYS})
    calc = _calc(repo)
    th = await calc.get_or_compute("default", TODAY)
    assert calc.is_dynamic_active(th) is True


async def test_任一因子回退硬编码则整体判False():
    """口径：全部可滚动因子都动态才算动态（不是「过半即算」）。"""
    repo = _Repo({k: _series(200, 0, 100, k) for k in KEYS if k != "us_liq_net"})
    repo.samples["us_liq_net"] = _series(3, 0, 1, "us_liq_net")
    calc = _calc(repo)
    th = await calc.get_or_compute("default", TODAY)
    assert calc.is_dynamic_active(th) is False


async def test_资金流面6个因子全部可滚动():
    """skip_rolling 传空集 ⇒ 6 个因子都进滚动分位（宏观面才有低频跳过）。"""
    repo = _Repo({k: _series(200, 0, 100, k) for k in KEYS})
    calc = _calc(repo)
    th = await calc.get_or_compute("default", TODAY)
    assert set(th) == set(KEYS)
    assert len(calc._skip_rolling) == 0


async def test_滚动带与静态带逐位相同时仍算动态():
    """cn_money_gap 实测：滚动 P10/P90 与静态 best/worst **完全相同**。

    静态带就是拿同一段 5 年历史标定的 ⇒ 两者逐位相同。
    旧判据「阈值 ≠ hardcode」会把它误报成「还在用静态阈值」，
    badge 于是说 5/6、``flow_dynamic=False``，而真相是 6/6 都在滚动分位上。
    """
    repo = _Repo({k: _series(200, 0, 100, k) for k in KEYS})
    # n=61 ⇒ rank = 60×0.1 = 6、60×0.9 = 54 都是整数 ⇒ 无插值误差
    repo.samples["cn_money_gap"] = [-20.0] * 6 + [-11.2] + [-8.0] * 47 + [-3.1] + [0.0] * 6
    calc = _calc(repo)
    th = await calc.get_or_compute("default", TODAY)
    rule = RULE_BY_KEY["cn_money_gap"]
    static_band = (float(rule["best"]), float(rule["worst"]))
    assert th["cn_money_gap"] == static_band, "前提：滚动带与静态带逐位相同"

    # 旧判据（值比较）：cn_money_gap 被当成静态 → 整体 False
    assert calc.is_dynamic_active(th) is False

    # 新判据（用计算器记录的滚动集）：6/6 都走了滚动分位 → True
    assert calc.rolling_keys("default", TODAY) == frozenset(KEYS)
    assert calc.is_dynamic_active(th, target="default", today=TODAY) is True


# ───────────────────── 5. 缓存 ─────────────────────


async def test_同一天重复调用走缓存不重复查表():
    repo = _Repo({k: _series(200, 0, 100, k) for k in KEYS})
    calc = _calc(repo)
    await calc.get_or_compute("default", TODAY)
    n = len(repo.calls)
    await calc.get_or_compute("default", TODAY)
    assert len(repo.calls) == n, "同一天第二次调用应命中缓存"


async def test_换日期缓存失效重新查表():
    repo = _Repo({k: _series(200, 0, 100, k) for k in KEYS})
    calc = _calc(repo)
    await calc.get_or_compute("default", TODAY)
    n = len(repo.calls)
    await calc.get_or_compute("default", TODAY + timedelta(days=1))
    assert len(repo.calls) == n * 2
