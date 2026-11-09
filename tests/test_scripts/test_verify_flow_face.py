"""``scripts/verify_flow_face.py`` 的**离线**单元测试（V0.123.0）。

为什么要有这个测试
------------------
``verify_flow_face.py`` 本身依赖外网（CFTC / 上交所 / FRED / Yahoo / 新浪），
**不在 CI 门禁集里** —— 于是它的**分析口径**就成了没人守的地方。
本测试把分析函数拉进 CI：

- 打分口径必须与服务一致（``positive`` 方向、0-100 截断、滚动带窗口）；
- 偏相关必须与 numpy 的标准算法一致；
- 比值判据必须挡住「分母趋零 ⇒ 假通过」；
- 五分位方向统计必须能区分「因子真的前瞻」与「因子没信号」。

⚠ 断言**不联网**，全部用构造出来的合成序列 ⇒ 门禁稳定可重入。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_flow_face.py"


def _load_module():
    """把 ``scripts/verify_flow_face.py`` 当模块加载（它不在包内）。"""
    spec = importlib.util.spec_from_file_location("verify_flow_face", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["verify_flow_face"] = mod
    spec.loader.exec_module(mod)
    return mod


vff = _load_module()


def _daily(n: int = 900, seed: int = 7) -> pd.DataFrame:
    """构造一段日频因子表（6 个因子，各 1 列）。"""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2019-01-01", periods=n)
    data = {}
    for i, key in enumerate(vff.KEYS):
        data[key] = rng.normal(0, 1, n) + i
    return pd.DataFrame(data, index=idx)


# ───────────────────────── 打分口径 ─────────────────────────


def test_打分方向随positive标志翻转() -> None:
    """``positive=True`` ⇒ 值越高分越高；``positive=False`` ⇒ 值越高分越低。

    做法：把因子值做**周期性震荡**（窗口内的分位带因此稳定），
    再取一个值**落在带内**的日期，用「翻转前后分数之和 = 100」这条
    代数恒等式 + 「值在带中点之上则分数在中点之下」来判方向。

    ⚠ 不能拿「首尾分数比大小」当判据：单调斜坡序列的滚动带会跟着一起平移，
    首尾分数落在截断边界上 ⇒ 判据与因子方向无关（V0.123.0 踩过）。
    """
    f = _daily(n=900)
    i = np.arange(900)
    f["cot_gold_net"] = 10.0 + 5.0 * np.sin(2 * np.pi * i / 60.0)  # negative 口径
    f["cot_gold_flow"] = 1000.0 + 500.0 * np.sin(2 * np.pi * i / 60.0)  # positive 口径

    s_now = vff.service_scores(f)
    s_flip = vff.service_scores(f, flip_net=True)

    # 找一天：值严格落在滚动带内部（否则截断会破坏恒等式）
    band_neg = vff.rolling_band(f, "cot_gold_net", positive=False)
    d = None
    for cand in f.index[-200:]:
        if cand not in band_neg.index:
            continue
        b = band_neg.loc[cand]
        v = f["cot_gold_net"].loc[cand]
        if b[0] < v < b[1]:
            d = cand
            break
    assert d is not None, "找不到落在带内部的日期（夹具失效）"

    # ① 翻转前后的分数互为对偶（代数恒等式，与数据无关）
    assert s_now["cot_gold_net"].loc[d] + s_flip["cot_gold_net"].loc[d] == pytest.approx(100.0)
    # ② 负号因子：值在带中点之上 ⇒ 分数在中点之下
    band = band_neg.loc[d]
    mid = (band[0] + band[1]) / 2.0
    v = f["cot_gold_net"].loc[d]
    if v > mid:
        assert s_now["cot_gold_net"].loc[d] < 50.0
    else:
        assert s_now["cot_gold_net"].loc[d] > 50.0
    # ③ 正号因子（cot_gold_flow）：同一套判定，方向相反
    band2 = vff.rolling_band(f, "cot_gold_flow", positive=True).loc[d]
    mid2 = (band2[0] + band2[1]) / 2.0
    v2 = f["cot_gold_flow"].loc[d]
    if v2 > mid2:
        assert s_now["cot_gold_flow"].loc[d] > 50.0
    else:
        assert s_now["cot_gold_flow"].loc[d] < 50.0


def test_静态兜底带不按符号取反() -> None:
    """样本不足 ⇒ 回退 hardcode 带，而 **hardcode 不带符号**。

    服务里 ``hardcode[key] = (rule["best"], rule["worst"])``
    （``macro_thresholds.py:107`` / ``money_flow.py:625``）——
    负号因子的 ``rule["best"]`` 本身就是**低**值（cot_gold_net：6.49 < 34.10）。

    ⚠ V0.123.0 的 bug：脚本曾把静态带也按 ``positive`` 翻一次 ⇒
    负号因子在样本不足段**方向整个反过来**。
    """
    rule = vff.RULES["cot_gold_net"]
    assert rule["best"] < rule["worst"], "负号因子的 best 端必须是低值"
    f = _daily(n=10)  # < min_samples(60) ⇒ 全部走静态带
    f["cot_gold_net"] = float(rule["best"])
    s = vff.service_scores(f)
    assert s["cot_gold_net"].iloc[-1] == pytest.approx(100.0)  # 最好端 ⇒ 100 分
    f["cot_gold_net"] = float(rule["worst"])
    s = vff.service_scores(f)
    assert s["cot_gold_net"].iloc[-1] == pytest.approx(0.0)  # 最坏端 ⇒ 0 分


def test_打分落在0到100之间() -> None:
    """截断口径：任何因子、任何一天，分数都在 [0, 100]。"""
    s = vff.service_scores(_daily())
    for key in vff.KEYS:
        col = s[key].dropna()
        assert col.min() >= 0.0
        assert col.max() <= 100.0


def test_滚动带用日频行而不是去重观测日() -> None:
    """窗口里**含重复值**（真实库是一天一行地重复写）⇒ 带与「去重观测日」不同。

    这条是口径护栏：V0.123.0 复算时踩过 —— 用去重观测日算出来的带
    与服务实际用的带不是一回事。
    """
    f = _daily(n=400)
    f["cot_gold_net"] = 10.0  # 常数 ⇒ 去重后只有 1 个观测
    band_daily = vff.rolling_band(f, "cot_gold_net", positive=False)
    # 常数序列 ⇒ P10 == P90 ⇒ best == worst
    best, worst = band_daily.iloc[-1]
    assert best == pytest.approx(worst)


def test_滚动带方向随positive翻转() -> None:
    """同一份数据，``positive`` 决定 P10/P90 谁当 best。"""
    f = _daily(n=400)
    f["cot_gold_net"] = np.linspace(0, 40, len(f))
    neg = vff.rolling_band(f, "cot_gold_net", positive=False).iloc[-1]
    pos = vff.rolling_band(f, "cot_gold_net", positive=True).iloc[-1]
    assert neg[0] < neg[1]  # negative ⇒ best=P10
    assert pos[0] > pos[1]  # positive  ⇒ best=P90


# ───────────────────────── 统计口径 ─────────────────────────


def test_偏相关与numpy标准算法一致() -> None:
    """控制变量后的偏相关 = 各自回归残差的相关（与手算一致）。"""
    rng = np.random.default_rng(3)
    n = 200
    ctrl = rng.normal(0, 1, n)
    y = 0.8 * ctrl + rng.normal(0, 1, n)
    x = 0.5 * ctrl + rng.normal(0, 1, n)
    r, cnt = vff.partial_corr(pd.Series(x), pd.Series(y), pd.Series(ctrl))
    assert cnt == n
    assert r == pytest.approx(0.0, abs=0.25)
    # 残差里不该再残留 ctrl 的线性成分
    X = np.column_stack([np.ones(n), ctrl])
    rx = x - X @ np.linalg.lstsq(X, x, rcond=None)[0]
    assert np.corrcoef(rx, ctrl)[0, 1] == pytest.approx(0.0, abs=1e-8)


def test_比值判据挡住分母趋零的假通过() -> None:
    """``pc_past ≈ 0`` 时比值会爆表 ⇒ 第②问必须判「不可判」（按不过处理）。"""
    good = {"pc_fwd": 0.30, "pc_past": 0.20, "ratio": 1.5}
    degenerate = {"pc_fwd": 0.30, "pc_past": 0.0004, "ratio": 750.0}
    spans = [0.1, 0.2, 0.3]
    assert vff.three_question_verdict(good, spans)["q2_symmetry"] is True
    v = vff.three_question_verdict(degenerate, spans)
    assert v["ratio_usable"] is False
    assert v["q2_symmetry"] is False
    assert v["passed"] is False


def test_三问需要三段同向() -> None:
    """三段里有反号 ⇒ 第③问不过（哪怕比值很高）。"""
    m = {"pc_fwd": 0.30, "pc_past": 0.10, "ratio": 3.0}
    assert vff.three_question_verdict(m, [0.1, 0.2, 0.3])["q3_spans"] is True
    assert vff.three_question_verdict(m, [0.1, -0.2, 0.3])["q3_spans"] is False
    assert vff.three_question_verdict(m, [0.1, -0.2, 0.3])["passed"] is False


def test_五分位方向统计能区分有信号与无信号() -> None:
    """构造「因子值低 ⇒ 前瞻收益高」的序列 ⇒ Q1−Q5 > 0；反过来则 < 0。

    ⚠ 价格序列必须**按因子反推**，不能拿一条单调上涨的价格凑数：
    单调价 ⇒ 前瞻收益是常数 ⇒ 统计量测的是「价涨了多少」而不是「因子有没有信号」，
    判据与因子无关（V0.123.0 踩过）。
    """
    n = 600
    idx = pd.bdate_range("2020-01-01", periods=n)
    rng = np.random.default_rng(11)
    v = rng.normal(size=n)  # 无趋势的因子
    z = (v - v.mean()) / v.std()
    r = -0.01 * z  # 因子值低 ⇒ 前瞻收益高
    pxv = np.empty(n)
    pxv[-60:] = 100.0  # 末端 60 天任意给定（前瞻收益为 NaN，会被丢掉）
    for i in range(n - 61, -1, -1):
        pxv[i] = pxv[i + 60] / (1.0 + r[i])  # ⇒ px[i+60]/px[i] - 1 == r[i]
    px = pd.Series(pxv, index=idx)
    good = pd.Series(v, index=idx)
    bad = pd.Series(-v, index=idx)
    r_good = vff.quintile_spread(good, px, fwd_days=60)
    r_bad = vff.quintile_spread(bad, px, fwd_days=60)
    assert r_good["n"] > 400
    assert r_good["spread"] > 0
    assert r_bad["spread"] < 0


def test_非重叠采样让样本量随窗口下降() -> None:
    """h 越大 ⇒ 有效样本越少（重叠窗口的机械伪相关正是靠这个压住的）。"""
    idx = pd.bdate_range("2020-01-01", periods=1200)
    series = pd.Series(np.random.default_rng(1).normal(size=1200), index=idx)
    px = pd.Series(100.0 + np.arange(1200) * 0.01, index=idx)
    m20 = vff.measure(series, px, h=20)
    m60 = vff.measure(series, px, h=60)
    assert m60["n"] < m20["n"]


# ───────────────────────── 口径一致性（V0.123.0 新增）─────────────────────────


def test_五分位分组规则与verify_cot_sign一致() -> None:
    """两个脚本必须给出**同一个数字** ⇒ 分组规则要逐条对齐。

    ``n`` 不能被 5 整除时，pandas 的 ``qcut(rank, 5)`` 与「按值排序后按序等分」
    会差 ±1 行 ⇒ 两脚本会给出不同的 Q1−Q5（V0.123.0 对齐过一轮）。
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "verify_cot_sign", _SCRIPT.parent / "verify_cot_sign.py"
    )
    assert spec and spec.loader
    vcs = importlib.util.module_from_spec(spec)
    sys.modules["verify_cot_sign"] = vcs
    spec.loader.exec_module(vcs)

    rng = np.random.default_rng(5)
    for n in (97, 100, 251):  # 97/251 不能被 5 整除
        vals = rng.normal(size=n)
        assert vff._quintile_by_order(vals.tolist()) == vcs._quintile_by_order(vals.tolist())


def test_因子日历与价格日历不同时按价格日历取窗口() -> None:
    """因子在**另一个**日历上 ⇒ 前瞻窗口按**价格日历**数，不是「并集行数」。

    ⚠ 直接 ``pd.DataFrame({"v": f, "px": px})`` 会取并集 ⇒ ``shift(-60)``
    数的是并集行 ⇒ 窗口长度飘忽（V0.123.0 修）。
    """
    n = 500
    px_idx = pd.bdate_range("2020-01-01", periods=n)
    px = pd.Series(100.0 + np.arange(n) * 0.05, index=px_idx)
    dense = pd.date_range(px_idx[0], px_idx[-1], freq="D")  # 更密的另一个日历
    f = pd.Series(np.linspace(0, 1, len(dense)), index=dense)

    aligned = vff._align_to_price(f, px)
    assert len(aligned) == n
    assert aligned.index.equals(px_idx)

    res = vff.quintile_spread(f, px, fwd_days=60)
    assert res["n"] == n - 60  # 末尾 60 个价格交易日没有前瞻收益


def test_观测点是值变化点而不是日频重复() -> None:
    """周频读数在日频表里连续重复 ⇒「观测点」必须是**值变化点**。

    ⚠ 按索引去重等于没去重（索引本来就唯一）⇒ 百分位被「值停留了几天」加权。
    """
    idx = pd.bdate_range("2020-01-01", periods=30)
    s = pd.Series([1.0] * 10 + [2.0] * 10 + [3.0] * 10, index=idx)
    obs = vff._change_points(s)
    assert len(obs) == 3
    assert list(obs.to_numpy()) == [1.0, 2.0, 3.0]
