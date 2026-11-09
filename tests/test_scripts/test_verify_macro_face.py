"""``scripts/verify_macro_face.py`` 的**离线**单元测试（V0.124.0）。

为什么要有这个测试
------------------
``verify_macro_face.py`` 依赖外网（H.15 / FRED / Yahoo / Eurostat），
**不在 CI 门禁集里** —— 于是它的**分析口径**就成了没人守的地方。
本测试把口径拉进 CI，守住五条最要命的性质：

1. **脚本重建 ≡ 生产回填**（离线版 X1）：同一批桩数据，
   证据脚本重建出的每一行必须与生产回填写进库的每一行**逐行相等**；
2. **撤销 point-in-time 必须变红**（离线版 X2）：把可得日退回观测日，
   重建结果必须与生产回填**不一致** ⇒ 守卫生效；
3. **打分口径与服务一致**：低频因子恒用静态带、负号因子方向正确、
   静态带不带符号；
4. **候选口径无前视**：尾随 z 分数只用 D 及之前的数据；
5. **三问判决的机械判据**：门槛、退化保护、符号一致性。

⚠ 断言**不联网**，全部用构造出来的合成数据 ⇒ 门禁稳定可重入。
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_macro_face.py"


def _load_module():
    """把 ``scripts/verify_macro_face.py`` 当模块加载（它不在包内）。"""
    spec = importlib.util.spec_from_file_location("verify_macro_face", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["verify_macro_face"] = mod
    spec.loader.exec_module(mod)
    return mod


vmf = _load_module()

DEEP_END = date(2026, 11, 9)

#: 桩数据（与 ``tests/test_services/test_macro_backfill.py`` 的深回填桩同源）
STUB = {
    "h15": [
        (date(2026, 10, 28), 4.05, 4.25, 4.75),
        (date(2026, 11, 3), 4.10, 4.30, 4.80),
        (date(2026, 11, 5), 4.12, 4.32, 4.82),
    ],
    "fred": {
        "DFII10": [(date(2026, 11, 3), 2.10)],
        "VIXCLS": [(date(2026, 11, 3), 15.5)],
    },
    "yahoo": [(date(2026, 11, 5), 100.5)],
    "fred_periodic": {
        "GFDEGDQ188S": [(date(2026, 4, 1), 120.0)],
        "GGGDTACNA188N": [(date(2023, 1, 1), 88.327)],
    },
    "eurostat": [(date(2026, 6, 30), 88.0)],
    "cb_quarters": [
        ("2025Q4", 200.0),
        ("2026Q1", 250.0),
        ("2026Q2", 300.0),
        ("2026Q3", 40.2),
    ],
}


def _cache() -> dict:
    return {
        "built_at": "2026-11-09",
        "asof": DEEP_END.isoformat(),
        "window_days": 800,
        **STUB,
        "gld": [],
        "closes_518880": {},
    }


@pytest.fixture
def repo(db_session: AsyncSession):
    from app.repositories.macro_factor_history import MacroFactorHistoryRepository

    return MacroFactorHistoryRepository(db_session)


@pytest.fixture
def stub_deep_sources(monkeypatch):
    """把深回填用到的 6 个外部源全部打桩。"""
    from app.services import macro_backfill as mb

    async def _fake_h15():
        return STUB["h15"]

    async def _fake_fred():
        return STUB["fred"]

    async def _fake_yahoo(_start, _end):
        return STUB["yahoo"]

    async def _fake_euro():
        return STUB["eurostat"]

    async def _fake_fred_periodic():
        return STUB["fred_periodic"]

    async def _fake_cb():
        return STUB["cb_quarters"]

    monkeypatch.setattr(mb, "_fetch_h15_history", _fake_h15)
    monkeypatch.setattr(mb, "_fetch_fred_history", _fake_fred)
    monkeypatch.setattr(mb, "_fetch_yahoo_dxy_deep", _fake_yahoo)
    monkeypatch.setattr(mb, "_fetch_eurostat_deep", _fake_euro)
    monkeypatch.setattr(mb, "_fetch_fred_periodic_history", _fake_fred_periodic)
    monkeypatch.setattr(mb, "_fetch_cb_gold_quarters", _fake_cb)
    return STUB


# ───────────────────── 离线版 X1：脚本重建 ≡ 生产回填 ─────────────────────


async def test_脚本重建与生产回填逐行相等(repo, stub_deep_sources) -> None:
    """同一批源数据 ⇒ 证据脚本重建的每一行 == 生产回填写进库的每一行。

    这是「脚本量的是生产口径、不是另一套」的最硬的一条断言。
    两侧共用 ``services/macro_history.py::build_observations`` ⇒ 口径不会漂。
    """
    from app.services.macro_backfill import backfill_macro_history_deep

    await backfill_macro_history_deep(repo, target="default", days=800, end=DEEP_END)

    obs = vmf.build_observations_cached(_cache(), end=DEEP_END)
    rebuilt = vmf.reconstruct_rows(obs, start=DEEP_END - timedelta(days=800), end=DEEP_END)
    mine: dict[tuple[date, str], tuple[float, str, str]] = {
        (d, k): (v, dd, s) for d, k, v, dd, s in rebuilt
    }
    assert mine, "脚本应重建出若干行"

    prod: dict[tuple[date, str], tuple[float, str, str]] = {}
    for key in vmf.KEYS:
        rows = await repo.get_window("default", key, 800, end_date=DEEP_END)
        for r in rows:
            prod[(r.snapshot_date, key)] = (r.value, r.data_date, r.source)

    assert prod, "生产回填应写入行"
    assert set(prod) == set(mine), (
        f"行集合不一致：只在生产 {sorted(set(prod) - set(mine))[:5]}，"
        f"只在脚本 {sorted(set(mine) - set(prod))[:5]}"
    )
    for k in prod:
        assert prod[k][0] == pytest.approx(mine[k][0], abs=1e-9), f"值不一致 @ {k}"
        assert prod[k][1] == mine[k][1], f"data_date 不一致 @ {k}"
        assert prod[k][2] == mine[k][2], f"source 不一致 @ {k}"


async def test_撤销point_in_time后必须与生产回填不同(repo, stub_deep_sources) -> None:
    """**X2（离线版）**：把可得日退回观测日 ⇒ 重建结果必须变。

    ⚠ 这是「前视」这个头号风险的守卫：如果改了口径重建结果却不变，
    说明守卫本身失效（或者生产表本来就是前视的）。
    """
    from app.services.macro_backfill import backfill_macro_history_deep

    await backfill_macro_history_deep(repo, target="default", days=800, end=DEEP_END)

    prod: dict[tuple[date, str], float] = {}
    for key in vmf.KEYS:
        for r in await repo.get_window("default", key, 800, end_date=DEEP_END):
            prod[(r.snapshot_date, key)] = r.value
    assert prod

    obs = vmf.build_observations_cached(_cache(), end=DEEP_END)
    start = DEEP_END - timedelta(days=800)
    front = vmf.front_view_rows(obs, start=start, end=DEEP_END)
    mine = {(d, k): v for d, k, v, _dd, _s in front}

    diff = [k for k in prod if k in mine and abs(mine[k] - prod[k]) > 1e-9]
    assert diff, "撤销 point-in-time 后重建结果必须与生产表不同（守卫失效？）"


def test_重建行粒度是日历日() -> None:
    """窗口内**每个日历日**都有一行（含周末），且没有断日。"""
    obs = vmf.build_observations_cached(_cache(), end=DEEP_END)
    start = DEEP_END - timedelta(days=30)
    rows = vmf.reconstruct_rows(obs, start=start, end=DEEP_END)
    dates = sorted({d for d, k, *_ in rows if k == "us10y"})
    assert dates, "应有 us10y 行"
    # 第一条观测之前不写行；之后**每天**都有（含周末）
    expected = [dates[0] + timedelta(days=i) for i in range((dates[-1] - dates[0]).days + 1)]
    assert dates == expected, "日历日粒度断了"
    assert date(2026, 11, 7) in dates  # 周六
    assert date(2026, 11, 8) in dates  # 周日
    # 第一条观测之前**不写行**（不前视、不兜底）
    assert dates[0] > start


def test_低频因子在观测可得前不写行() -> None:
    """``cn_gov_debt`` 的实测滞后 665 天 ⇒ 可得日之前没有任何行。"""
    obs = vmf.build_observations_cached(_cache(), end=DEEP_END)
    rows = vmf.reconstruct_rows(obs, start=DEEP_END - timedelta(days=800), end=DEEP_END)
    cn = sorted({d for d, k, *_ in rows if k == "cn_gov_debt"})
    assert cn, "cn_gov_debt 应有行"
    assert cn[0] >= date(2025, 10, 26), f"可得日早于实测滞后：{cn[0]}"


# ───────────────────── 打分口径 ─────────────────────


def _daily_factors(n: int = 400, seed: int = 3) -> pd.DataFrame:
    """构造一段日频因子表（11 个因子各 1 列，日历日粒度）。"""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    data = {}
    for i, key in enumerate(vmf.KEYS):
        data[key] = rng.normal(0, 1, n) + i
    return pd.DataFrame(data, index=idx)


def test_低频因子恒用静态带() -> None:
    """4 个低频因子在 ``SKIP_ROLLING_FACTORS`` 里 ⇒ 永远走静态带。

    验证方式：把因子值改成静态带的两个端点，分数必须正好是 100 / 0
    （滚动带给出的会是别的数）。
    """
    f = _daily_factors(n=300)
    key = "cb_gold"
    rule = vmf.RULES[key]
    f[key] = float(rule["best"])
    s = vmf.macro_scores(f)
    assert s[key].iloc[-1] == pytest.approx(100.0)
    f[key] = float(rule["worst"])
    s = vmf.macro_scores(f)
    assert s[key].iloc[-1] == pytest.approx(0.0)


def test_日频因子走滚动分位带() -> None:
    """日频因子的分数**随历史窗口移动** ⇒ 说明确实走了滚动带（不是静态带）。

    判据设计：只改**过去** 150 天的历史（不改最后一天的读数）。
    - 走滚动带 ⇒ 窗口内的 P10/P90 变了 ⇒ 最后一天的分数跟着变；
    - 走静态带 ⇒ 分数只取决于当天读数 ⇒ **必须不变**。
    """
    f = _daily_factors(n=300)
    key = "us10y"
    s1 = vmf.macro_scores(f)
    f2 = f.copy()
    f2.iloc[:150, f2.columns.get_loc(key)] += 10.0  # 只动历史，不动最后一天
    s2 = vmf.macro_scores(f2)
    assert f[key].iloc[-1] == f2[key].iloc[-1], "前提：当天读数没变"
    assert s1[key].iloc[-1] != pytest.approx(s2[key].iloc[-1]), "分数应随历史窗口移动"


def test_负号因子方向正确() -> None:
    """``dxy`` 是 ``positive=False`` ⇒ 低值得高分。

    ⚠ 服务里负号因子的静态带本身是 ``best < worst``（dxy：best=94.0 / worst=107.0），
    **静态带不带符号** ⇒ 不能按 ``positive`` 再翻一次（否则方向整个反过来）。
    """
    rule = vmf.RULES["dxy"]
    assert rule["best"] < rule["worst"], "负号因子的 best 端必须是低值"
    f = _daily_factors(n=10)  # < min_samples(60) ⇒ 全走静态带
    f["dxy"] = float(rule["best"])
    s = vmf.macro_scores(f)
    assert s["dxy"].iloc[-1] == pytest.approx(100.0)
    f["dxy"] = float(rule["worst"])
    s = vmf.macro_scores(f)
    assert s["dxy"].iloc[-1] == pytest.approx(0.0)


def test_打分落在0到100之间() -> None:
    """截断口径：任何因子、任何一天，分数都在 [0, 100]。"""
    s = vmf.macro_scores(_daily_factors())
    for key in vmf.KEYS:
        col = s[key].dropna()
        assert col.min() >= 0.0
        assert col.max() <= 100.0


def test_分组composite权重归一化() -> None:
    """子组 composite 用**归一化**后的权重 ⇒ 全 50 分时 composite = 50。"""
    flat = pd.DataFrame(
        50.0, index=pd.date_range("2024-01-01", periods=3, freq="D"), columns=vmf.KEYS
    )
    assert vmf.group_composite(flat, vmf.DAILY).iloc[-1] == pytest.approx(50.0)
    assert vmf.group_composite(flat, vmf.LOWFREQ).iloc[-1] == pytest.approx(50.0)
    assert vmf.group_composite(flat, tuple(vmf.KEYS)).iloc[-1] == pytest.approx(50.0)


def test_三个分组覆盖全部11个因子() -> None:
    """日频 7 + 低频 4 = 11，且与服务的 ``SKIP_ROLLING_FACTORS`` 一致。"""
    assert set(vmf.DAILY) | set(vmf.LOWFREQ) == set(vmf.KEYS)
    assert not (set(vmf.DAILY) & set(vmf.LOWFREQ))
    assert len(vmf.KEYS) == 11
    assert set(vmf.LOWFREQ) == {"cb_gold", "us_gov_debt", "cn_gov_debt", "eu_gov_debt"}


def test_权重合计为1() -> None:
    """服务规则表本身的纪律：11 个因子权重合计 1.0。"""
    total = sum(float(vmf.RULES[k]["weight"]) for k in vmf.KEYS)
    assert total == pytest.approx(1.0)


# ───────────────────── 候选口径（z 分数）无前视 ─────────────────────


def test_尾随z分数不使用未来数据() -> None:
    """z 分数只用 D 及之前 252 日 ⇒ 改动未来数据不影响过去的 z 分数。"""
    f = _daily_factors(n=400)
    z1 = vmf.trailing_zscore(f, "us10y")
    f2 = f.copy()
    f2.iloc[300:, f2.columns.get_loc("us10y")] = 999.0
    z2 = vmf.trailing_zscore(f2, "us10y")
    assert np.allclose(z1.iloc[:300].to_numpy(float), z2.iloc[:300].to_numpy(float), equal_nan=True)


def test_尾随z分数需要足够样本() -> None:
    """样本不足 60 时不给值（不写 0、不写常数）。"""
    f = _daily_factors(n=30)
    z = vmf.trailing_zscore(f, "us10y")
    assert z.dropna().empty


# ───────────────────── 三问判决 ─────────────────────


def _m(pc_fwd: float, pc_past: float, ratio: float) -> dict:
    return {
        "pc_fwd": pc_fwd,
        "p_fwd": 0.01,
        "pc_past": pc_past,
        "p_past": 0.01,
        "ratio": ratio,
        "n": 60,
        "raw_corr": 0.2,
    }


def test_三问全过时通过() -> None:
    v = vmf.core.three_question_verdict(_m(0.20, 0.10, 2.0), [0.2, 0.1, 0.3])
    assert v["q1_power"] and v["q2_symmetry"] and v["q3_spans"]
    assert v["passed"]


def test_三问第一问功效不足则不过() -> None:
    v = vmf.core.three_question_verdict(_m(0.10, 0.05, 2.0), [0.2, 0.1, 0.3])
    assert not v["q1_power"]
    assert not v["passed"]


def test_三问第二问比值不足则不过() -> None:
    v = vmf.core.three_question_verdict(_m(0.50, 0.90, 0.56), [0.2, 0.1, 0.3])
    assert not v["q2_symmetry"]
    assert not v["passed"]


def test_三问第二问分母趋零判不可判() -> None:
    """``|pc_past| < 0.05`` ⇒ 比值爆表是假的 ⇒ 判**不可判**（按不过处理）。"""
    v = vmf.core.three_question_verdict(_m(0.90, 0.01, 90.0), [0.2, 0.1, 0.3])
    assert not v["ratio_usable"]
    assert not v["q2_symmetry"]
    assert not v["passed"]


def test_三问第三问三段不同向则不过() -> None:
    v = vmf.core.three_question_verdict(_m(0.20, 0.10, 2.0), [0.2, -0.1, 0.3])
    assert not v["q3_spans"]
    assert not v["passed"]


def test_三问第三问缺一段样本判不过() -> None:
    """某段样本不足 ⇒ 该段 pc_fwd 是 NaN ⇒ 三段同向**不可判** ⇒ 按不过处理。"""
    v = vmf.core.three_question_verdict(_m(0.20, 0.10, 2.0), [0.2, float("nan"), 0.3])
    assert not v["q3_spans"]
    assert not v["passed"]


# ───────────────────── 测量机器的正/负对照 ─────────────────────


def _synthetic_market(n: int = 3000, seed: int = 7):
    """造一段合成金价（对数随机游走）。"""
    rng = np.random.default_rng(seed)
    px = pd.Series(
        100 * np.exp(np.cumsum(rng.normal(0.0002, 0.012, n))),
        index=pd.date_range("2014-01-01", periods=n, freq="B"),
    )
    return px


def test_正对照_机器能识别真信号() -> None:
    """把「未来 60 日收益」当因子喂进去 ⇒ 机器**必须**判它过三问。

    ⚠ 这是「机器没坏」的守门人：若机器对**真信号**也判不过，
    那么「宏观面全部未通过」就毫无意义（测不出 = 没测）。
    """
    px = _synthetic_market()
    fwd = px.shift(-60) / px - 1.0
    yr = pd.Series(px.index.year, index=px.index)
    fac = fwd - fwd.groupby(yr).transform("mean")
    m = vmf.core.measure(fac, px, h=60)
    spans = vmf.core.measure_spans(fac, px, h=60)
    v = vmf.core.three_question_verdict(m, spans)
    assert m["pc_fwd"] > 0.8
    assert v["passed"], f"真信号应判过：{v}"


def test_负对照_机器不把白噪声当信号() -> None:
    """白噪声因子 ⇒ 必须判不过（否则「全部通过」也只是噪声）。"""
    px = _synthetic_market()
    rng = np.random.default_rng(11)
    noise = pd.Series(rng.normal(0, 1, len(px)), index=px.index)
    m = vmf.core.measure(noise, px, h=60)
    spans = vmf.core.measure_spans(noise, px, h=60)
    v = vmf.core.three_question_verdict(m, spans)
    assert not v["passed"], f"白噪声不该判过：{v}"


# ───────────────────── 不隐式联网 ─────────────────────


def test_缓存不存在时直接退出不联网(monkeypatch) -> None:
    """不给可读的 ``--cache`` ⇒ 立刻退出（**绝不隐式联网**）。"""

    async def _boom(*_a, **_k):  # pragma: no cover - 不该被调用
        raise AssertionError("分析阶段不应联网")

    monkeypatch.setattr(vmf, "fetch_all", _boom)
    assert vmf.main(["--cache", "/nonexistent/macro_face_cache.pkl"]) == 2


def test_只给cache时不会调取数函数(monkeypatch, tmp_path) -> None:
    """只给 ``--cache`` ⇒ 不调用 ``fetch_all``。"""
    called: list[str] = []

    async def _fake_fetch(*_a, **_k):
        called.append("fetch")
        return _cache()

    monkeypatch.setattr(vmf, "fetch_all", _fake_fetch)
    path = tmp_path / "c.pkl"
    vmf.save_cache(path, _cache())
    assert vmf.main(["--cache", str(path)]) == 0
    assert not called
