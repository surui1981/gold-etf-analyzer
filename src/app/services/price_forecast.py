"""金价区间预测（V0.127.0）—— 未来 N 个交易日的**统计区间**，不是方向预测。

这个模块只回答一个问题：**以最新收盘价为起点，未来 N 个交易日的金价大致落在什么范围**。
它**不预测涨跌方向** —— 区间中心恒等于最新收盘价（``drift_mode="none"``）。

⚠ **为什么中心不倾斜**
「用综合指数方向偏移区间中心」（Phase B）需要消息面与综合指数的历史深度：
生产库 ``news_scores`` 只有 37 行、``daily_snapshots`` 只有 67 行 ⇒ h=20 的非重叠采样只剩 3 个样本
⇒ 统计上无意义。前置是「回填消息面历史 + point-in-time 重放每日快照」⇒ 独立立项。
详见 ``docs/price-forecast.md``。

⚠ **宽度为什么不取「历史类比」（用户拍板的是「类比为主 + 波动率交叉校验」，实测把这条修正了一半）**
在 2588 行真实 GC 日线上做 walk-forward 实测：

    | 方法                          | 名义 | 训练段实测 | 样本外实测 |
    |-------------------------------|------|-----------|-----------|
    | 类比带 P10–P90（未校准）      | 80%  | 75.0%     | **45.8%** |
    | 类比带 P7–P93（训练段校准）   | 86%  | 78.5%     | **55.4%** |
    | **EWMA 对数正态带 P10–P90**   | 80%  | 76.7%     | **77.9%** |

类比样本自身的分位数**条件于「波动率相近」** ⇒ 它的尾部比整体分布薄
⇒ 系统性低估尾部概率；而且在训练段校准出来的分位**对到样本外就失效**（regime 切换）。
⇒ **宽度取 EWMA（实测跨窗口几乎不变）**。
但类比法的**形状**（短期更胖）跨窗口同向、可靠 ⇒ **形状取类比**。

    形状实测（相对 20 日总宽归一）：k=1 → 0.26 / k=5 → 0.57 / k=20 → 1.00
    对数正态 √k 锥：              k=1 → 0.22 / k=5 → 0.50 / k=20 → 1.00
    ⇒ 短期实际比正态锥胖 1.25–1.31 倍

⚠ **本模块不许 import numpy/pandas**（``scripts/check_deps.py`` 扫 ``src/`` 与 ``tests/``）。
分位数**直接复用** ``services/macro_thresholds.py::_percentile``
（线性插值，与 ``numpy.percentile(method="linear")`` 一致）⇒ 不另写一份。

⚠ **无前视（两条硬约束）**
- E1：算任意基准日 D 的带子时，把 D 之后的数据全部删掉，带子必须**一模一样**；
- E2：参与匹配的相似日 s 必须满足 ``s + horizon <= D``（否则用到了 D 之后的路径）。
两条都由 ``tests/test_services/test_price_forecast.py`` 锁死。

⚠ **降级必须可见**
相似日不足 / 样本太短时**退回纯 EWMA 带**并标 ``method="vol_only"`` + ``reason``，
绝不画一条没有依据的假带（E6）。
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.services.macro_thresholds import _percentile
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ─────────────────────────── 常量 ───────────────────────────

#: EWMA 平滑系数（RiskMetrics 常用值）。实测：宽度口径在 λ=0.94 时跨窗口最稳。
EWMA_LAMBDA = 0.94

DEFAULT_HORIZON = 20
DEFAULT_COVERAGE = 0.80
DEFAULT_TARGET = "ny"

#: 名义覆盖率 → 正态分位 z（双尾）。
#: ⚠ 只认这 4 档 —— 覆盖率是**产品口径**，不是连续参数 ⇒ 避免「随便传个 0.73」导致
#: 界面上出现一个没有校准记录支撑的覆盖率。
COVERAGE_Z: dict[float, float] = {
    0.50: 0.6744897501960817,
    0.80: 1.2815515655446004,
    0.90: 1.6448536269514722,
    0.98: 2.3263478740408408,
}

#: 相似日容忍度：|σ_s / σ_D − 1| ≤ 25%。
SIM_TOLERANCE = 0.25

#: 相似日数量下限。不足 ⇒ 退回纯波动率带（``method="vol_only"``）。
MIN_SIM = 30

#: 两法宽度差异超过此比例 ⇒ 判「口径不一致」（**仅在没有实测分布时**的兜底判据）。
#: ⚠ 实测上「差 > 40%」在 **39% 的日子里都成立**（类比带的尾部系统性比整体薄，
#: 宽度比均值 ≈ 0.615）⇒ 用它当告警判据等于天天告警。
#: ⇒ 正式判据是「比值落在实测分布 [p05, p95] 之外」（见 ``load_cross_check_band``）。
CROSS_CHECK_THRESHOLD = 0.40

#: 口径产物目录（**入版本库** —— 口径是产品的一部分，不是临时产物）。
ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "forecast"
SHAPE_FILE = ASSET_DIR / "shape.json"
CALIBRATION_FILE = ASSET_DIR / "calibration.json"

#: 一年按 252 个交易日（年化波动率换算用）。
TRADING_DAYS_PER_YEAR = 252


# ─────────────────────────── 数据结构 ───────────────────────────


@dataclass(frozen=True)
class BandPoint:
    """带子上的一点（k 个交易日后的上下沿）。"""

    k: int
    lower: float
    upper: float


@dataclass(frozen=True)
class AnalogBand:
    """历史类比带（对数空间的相对路径）。"""

    n_sim: int
    lower_path: tuple[float, ...]
    upper_path: tuple[float, ...]

    @property
    def half_widths(self) -> tuple[float, ...]:
        """每个 k 的半宽（对数空间）。"""
        return tuple((hi - lo) / 2 for lo, hi in zip(self.lower_path, self.upper_path, strict=True))


@dataclass(frozen=True)
class PriceBand:
    """一条金价区间（服务层的结构化输出，schema 层再转成响应体）。"""

    target: str
    base_date: date | None
    base_close: float
    horizon: int
    coverage: float
    z: float
    sigma: float
    method: str
    drift_mode: str = "none"
    shape_source: str = "cone"
    points: tuple[BandPoint, ...] = ()
    ewma_half_width: float | None = None
    analog_half_width: float | None = None
    analog_n_sim: int | None = None
    cross_check: str | None = None
    measured_coverage: float | None = None
    measured_spans: dict[str, float] = field(default_factory=dict)
    reason: str | None = None
    n_bars: int = 0
    first_date: date | None = None
    min_sim: int = MIN_SIM

    @property
    def lower(self) -> float:
        """区间下沿（horizon 处的下边界）。"""
        return self.points[-1].lower if self.points else 0.0

    @property
    def upper(self) -> float:
        """区间上沿（horizon 处的上边界）。"""
        return self.points[-1].upper if self.points else 0.0

    @property
    def sigma_annual(self) -> float:
        """年化波动率（%）。"""
        return self.sigma * math.sqrt(TRADING_DAYS_PER_YEAR) * 100


# ─────────────────────────── 基础量 ───────────────────────────


def log_returns(closes: Sequence[float]) -> list[float]:
    """逐日对数收益（``ln(c_i / c_{i-1})``）。

    非正价格按 0 收益处理（不该出现，但不许因此抛异常把整个接口带崩）。
    """
    out: list[float] = []
    for i in range(1, len(closes)):
        prev, cur = closes[i - 1], closes[i]
        out.append(math.log(cur / prev) if prev > 0 and cur > 0 else 0.0)
    return out


def ewma_sigma_series(closes: Sequence[float], lam: float = EWMA_LAMBDA) -> list[float]:
    """返回与 ``closes`` 等长的 σ 序列；第 i 个元素**只用 r_1..r_i**（因果）。

    定义：``var_1 = r_1²``，``var_i = λ·var_{i-1} + (1-λ)·r_i²``，``σ_i = √var_i``。
    ⚠ **不减均值** —— 日对数收益的均值量级远小于其标准差，de-mean 对 σ 的影响 < 1%，
    而 de-mean 会引入「样本区间」依赖 ⇒ 不做。
    """
    n = len(closes)
    out = [0.0] * n
    var: float | None = None
    for i in range(1, n):
        prev, cur = closes[i - 1], closes[i]
        r = math.log(cur / prev) if prev > 0 and cur > 0 else 0.0
        var = r * r if var is None else lam * var + (1.0 - lam) * r * r
        out[i] = math.sqrt(var)
    return out


def ewma_sigma(closes: Sequence[float], lam: float = EWMA_LAMBDA) -> float:
    """最新一日的 EWMA 波动率（σ，日收益口径）。"""
    if len(closes) < 2:
        return 0.0
    return ewma_sigma_series(closes, lam)[-1]


def cone_shape(horizon: int = DEFAULT_HORIZON) -> list[float]:
    """对数正态 √k 锥（形状的退化基线）。

    ``shape_k = √(k / horizon)`` ⇒ k=horizon 处为 1.0。
    """
    return [math.sqrt(k / horizon) for k in range(1, horizon + 1)]


def project_trading_dates(last_date: date, n: int) -> list[date]:
    """从 ``last_date`` 起外推 n 个交易日（周一至周五）。

    ⚠ **不含美股假日修正** —— 与仓库既有口径一致
    （``utils/market_clock.trading_days_between`` 同样是「周一至周五、不分节假日」）。
    假日的处理是「预测日期可能多一天/少一天」，不影响区间数值本身。
    """
    out: list[date] = []
    d = last_date
    while len(out) < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    return out


# ─────────────────────────── 历史类比 ───────────────────────────


def analog_candidates(
    sigmas: Sequence[float],
    idx: int,
    horizon: int = DEFAULT_HORIZON,
    tol: float = SIM_TOLERANCE,
) -> list[int]:
    """挑出基准日 ``idx`` 的相似日下标。

    两条硬约束：

    - **E2 无前视**：``s + horizon <= idx`` —— 相似日的「未来 20 天」必须整体落在基准日之前，
      否则那条路径里就含了基准日之后的信息（未来函数）；
    - **波动率相近**：``|σ_s / σ_idx − 1| <= tol``。

    ⚠ 单独暴露出来是为了让测试能**直接断言**「候选集不含越界下标」，
    而不是靠「结果恰好没变」这种间接证据（仓库铁律：断言要正面锁住契约）。
    """
    sigma_idx = sigmas[idx] if idx < len(sigmas) else 0.0
    if sigma_idx <= 0:
        return []
    max_s = idx - horizon  # E2：s + horizon <= idx
    if max_s < 1:
        return []
    return [s for s in range(1, max_s + 1) if abs(sigmas[s] / sigma_idx - 1.0) <= tol]


def analog_band(
    closes: Sequence[float],
    sigmas: Sequence[float],
    idx: int,
    horizon: int = DEFAULT_HORIZON,
    coverage: float = DEFAULT_COVERAGE,
    tol: float = SIM_TOLERANCE,
    min_sim: int = MIN_SIM,
) -> AnalogBand | None:
    """在基准日 ``idx`` 上构造历史类比带（对数空间）。

    相似日 ``s`` 的判定：``s + horizon <= idx``（E2 无前视）且
    ``|σ_s / σ_idx − 1| ≤ tol``（波动率相近）。

    Returns:
        ``AnalogBand``；相似日不足 / 数据太短 ⇒ ``None``（调用方据此降级）。
    """
    n = len(closes)
    if idx < 1 or idx >= n:
        return None
    candidates = analog_candidates(sigmas, idx, horizon=horizon, tol=tol)
    if len(candidates) < min_sim:
        return None

    lo_pct = (100.0 - coverage * 100.0) / 2.0
    hi_pct = 100.0 - lo_pct
    per_k: list[list[float]] = [[] for _ in range(horizon)]
    for s in candidates:
        base = closes[s]
        if base <= 0:
            continue
        for k in range(1, horizon + 1):
            idx_s_k = s + k
            if idx_s_k >= n:
                continue
            val = closes[idx_s_k]
            if val <= 0:
                continue
            per_k[k - 1].append(math.log(val / base))

    lower: list[float] = []
    upper: list[float] = []
    for vals in per_k:
        if len(vals) < min_sim:
            return None
        vals.sort()
        lower.append(_percentile(vals, lo_pct))
        upper.append(_percentile(vals, hi_pct))
    return AnalogBand(
        n_sim=len(candidates),
        lower_path=tuple(lower),
        upper_path=tuple(upper),
    )


def analog_shape_at(
    closes: Sequence[float],
    sigmas: Sequence[float],
    idx: int,
    horizon: int = DEFAULT_HORIZON,
    coverage: float = DEFAULT_COVERAGE,
    tol: float = SIM_TOLERANCE,
    min_sim: int = MIN_SIM,
) -> list[float] | None:
    """单个基准日上的类比形状（相对 horizon 处归一）。

    Returns:
        长度 ``horizon`` 的列表，末位为 1.0；相似日不足 ⇒ ``None``。
    """
    band = analog_band(
        closes, sigmas, idx, horizon=horizon, coverage=coverage, tol=tol, min_sim=min_sim
    )
    if band is None:
        return None
    halfs = band.half_widths
    total = halfs[-1] if halfs else 0.0
    if total <= 0:
        return None
    return [h / total for h in halfs]


# ─────────────────────────── 带宽合成 ───────────────────────────


def build_band(
    closes: Sequence[float],
    horizon: int = DEFAULT_HORIZON,
    coverage: float = DEFAULT_COVERAGE,
    shape: Sequence[float] | None = None,
    sigmas: Sequence[float] | None = None,
    base_idx: int | None = None,
    target: str = DEFAULT_TARGET,
    base_date: date | None = None,
    first_date: date | None = None,
    tol: float = SIM_TOLERANCE,
    min_sim: int = MIN_SIM,
    cross_check_band: tuple[float, float] | None = None,
) -> PriceBand:
    """合成最终区间带。

    公式（对数空间）::

        half_k   = half_H · shape_k
        lower_k  = P_D · exp(−half_k)
        upper_k  = P_D · exp(+half_k)
        half_H   = z · σ_D · √H          （EWMA 定宽）
                   ↑ 若类比宽度与之相差 > 40% ⇒ 取更宽的一条

    Args:
        closes: 收盘价序列（**升序**，只含 ≤ 基准日的数据）。
        horizon: 期限（交易日）。
        coverage: 名义覆盖率（0.5 / 0.8 / 0.9 / 0.98）。
        shape: 形状曲线（长度 = horizon，末位 = 1.0）；``None`` ⇒ 用 √k 锥。
        sigmas: 与 ``closes`` 等长的 σ 序列；``None`` ⇒ 现算。
        base_idx: 基准日在 ``closes`` 中的下标；默认取最后一行。
        cross_check_band: 两法宽度比的实测正常区间 ``(p05, p95)``；``None`` ⇒ 退回兜底判据。
    """
    if coverage not in COVERAGE_Z:
        raise ValueError(f"不支持的覆盖率: {coverage}（可用: {sorted(COVERAGE_Z)}）")
    if len(closes) < 2:
        raise ValueError("价格序列不足 2 行，无法计算区间")

    z = COVERAGE_Z[coverage]
    idx = len(closes) - 1 if base_idx is None else base_idx
    if idx < 1:
        raise ValueError("基准日之前没有足够的历史，无法计算区间")
    if sigmas is None:
        sigmas = ewma_sigma_series(closes)

    base_close = float(closes[idx])
    sigma = float(sigmas[idx]) if idx < len(sigmas) else ewma_sigma(closes)

    # ① 宽度：EWMA 对数正态
    ewma_half = z * sigma * math.sqrt(horizon)

    # ② 类比交叉校验（宽度维度）
    analog = analog_band(
        closes, sigmas, idx, horizon=horizon, coverage=coverage, tol=tol, min_sim=min_sim
    )
    analog_half: float | None = None
    if analog is not None:
        halfs = analog.half_widths
        analog_half = halfs[-1] if halfs else None

    reason: str | None = None
    cross_check: str | None = None
    effective_half = ewma_half
    method = "ewma"
    shape_source = "cone"

    if analog_half is not None and ewma_half > 0:
        ratio = analog_half / ewma_half
        if cross_check_band is not None:
            lo, hi = cross_check_band
            if ratio > hi:
                # 类比带异常宽 ⇒ 保守侧取更宽的那条（覆盖率只会更高，不会低于校准值）
                cross_check = "analog_unusually_wide"
                effective_half = max(analog_half, ewma_half)
                method = "ewma_widened"
            elif ratio < lo:
                # 类比带异常窄 ⇒ 仍用 EWMA（它是更宽的一条）
                cross_check = "analog_unusually_narrow"
        else:
            # 没有实测分布时的兜底判据（少用为妙：实测上这个条件经常成立）
            if abs(ratio - 1.0) > CROSS_CHECK_THRESHOLD:
                cross_check = "disagree"
                effective_half = max(analog_half, ewma_half)
                method = "ewma_widened" if analog_half > ewma_half else "ewma"
    elif analog is None:
        reason = "insufficient_analogs"

    # ③ 形状：优先用类比形状曲线；缺失 ⇒ 退回 √k 锥
    shape_used: Sequence[float]
    if shape is not None and len(shape) == horizon:
        shape_used = shape
        shape_source = "analog"
        method = "ewma_shape" if method == "ewma" else method
    else:
        shape_used = cone_shape(horizon)
        shape_source = "cone"
        if method == "ewma":
            method = "vol_only"
        if reason is None:
            reason = "no_shape_artifact"

    points = tuple(
        BandPoint(
            k=k + 1,
            lower=base_close * math.exp(-effective_half * shape_used[k]),
            upper=base_close * math.exp(+effective_half * shape_used[k]),
        )
        for k in range(horizon)
    )

    return PriceBand(
        target=target,
        base_date=base_date,
        base_close=base_close,
        horizon=horizon,
        coverage=coverage,
        z=z,
        sigma=sigma,
        method=method,
        shape_source=shape_source,
        points=points,
        ewma_half_width=ewma_half,
        analog_half_width=analog_half,
        analog_n_sim=analog.n_sim if analog is not None else None,
        cross_check=cross_check,
        reason=reason,
        n_bars=len(closes),
        first_date=first_date,
        min_sim=min_sim,
    )


# ─────────────────────────── 口径产物读写 ───────────────────────────


def _read_json(path: Path) -> dict | None:
    """读 JSON 产物；**任何**异常都当作「没有产物」⇒ 触发降级而不是 500。"""
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("读口径产物失败 %s: %s", path, exc)
        return None
    return data if isinstance(data, dict) else None


def load_shape(horizon: int = DEFAULT_HORIZON, target: str | None = None) -> list[float] | None:
    """读形状曲线；产物缺失 / 口径不符 / 标的不符 / 数据不合法 ⇒ ``None``（退回 √k 锥）。

    ⚠ ``target`` 是**标的维度**的护栏（V0.127.0 新加）：形状曲线是**按标的**离线
    校准出来的（当前产物只覆盖 ``ny``）⇒ 拿 ny 的形状去画 etf / gram 的扇形，
    等于「把别的标的的证据说成这个标的的证据」⇒ 必须挡掉，退回 √k 锥（退化基线）
    并让调用方明示降级。
    """
    data = _read_json(SHAPE_FILE)
    if not data:
        return None
    if int(data.get("horizon", -1)) != horizon:
        logger.warning("形状产物口径不符（horizon=%s ≠ %s）", data.get("horizon"), horizon)
        return None
    if target is not None and data.get("target") != target:
        logger.warning("形状产物标的不符（%s ≠ %s）", data.get("target"), target)
        return None
    raw = data.get("shape")
    if not isinstance(raw, list) or len(raw) != horizon:
        return None
    try:
        vals = [float(v) for v in raw]
    except (TypeError, ValueError):
        return None
    if any(v <= 0 for v in vals):
        return None
    # 防御性单调包络：扇形必须越走越宽（校准脚本已经取过包络，这里再兜一层，
    # 防止手工改坏产物后扇形边缘起毛刺）。
    running = 0.0
    for i, v in enumerate(vals):
        if v < running:
            vals[i] = running
        else:
            running = v
    return vals


def load_cross_check_band(calibration: dict | None) -> tuple[float, float] | None:
    """从校准产物里取两法宽度比的正常区间 ``(p05, p95)``。

    ⚠ 这才是交叉校验的判据 —— **不是**「两法宽度是否相等」：
    实测类比带的尾部系统性比整体薄（宽度比均值 ≈ 0.615），
    「差 > 40%」在 39% 的日子里成立 ⇒ 拿它当告警等于天天告警。
    真正的异常是「今天的比值落在历史分布之外」。
    """
    if not calibration:
        return None
    cc = calibration.get("cross_check")
    if not isinstance(cc, dict):
        return None
    lo, hi = cc.get("p05"), cc.get("p95")
    if not isinstance(lo, (int, float)) or not isinstance(hi, (int, float)):
        return None
    if hi <= lo:
        return None
    return (float(lo), float(hi))


def load_calibration(target: str = DEFAULT_TARGET) -> dict | None:
    """读校准产物；标的不符 ⇒ ``None``。"""
    data = _read_json(CALIBRATION_FILE)
    if not data:
        return None
    if data.get("target") != target:
        return None
    return data


def measured_coverage(calibration: dict | None, coverage: float) -> dict[str, float]:
    """从校准产物里取某档覆盖率的实测值（训练段 / 样本外 / 近段）。

    ⚠ 返回的是**实测值**，不是名义值 —— 界面上必须显示实测值。
    """
    if not calibration:
        return {}
    coverages = calibration.get("coverages")
    if not isinstance(coverages, dict):
        return {}
    entry = coverages.get(str(round(coverage * 100)))
    if not isinstance(entry, dict):
        return {}
    out: dict[str, float] = {}
    for key in ("train", "out_of_sample", "recent"):
        val = entry.get(key)
        if isinstance(val, (int, float)):
            out[key] = float(val)
    return out


def measured_coverage_of(calibration: dict | None, coverage: float) -> float | None:
    """实测覆盖率的主口径值（**样本外**优先，其次近段，最后训练段）。"""
    spans = measured_coverage(calibration, coverage)
    for key in ("out_of_sample", "recent", "train"):
        if key in spans:
            return spans[key]
    return None


# ─────────────────────────── 服务层（带缓存） ───────────────────────────

#: 结果缓存 TTL（秒）。10 分钟 —— 一根日 K 的「当前价」在盘中会动，
#: 但**收盘价**（本功能的基准）一天只变一次 ⇒ 10 分钟足够，且新收盘价进来会立即失效。
CACHE_TTL_SECONDS = 600

_CACHE: dict[tuple[str, int, float, date, float], tuple[PriceForecast, datetime]] = {}


@dataclass(frozen=True)
class PriceForecast:
    """一条完整的区间预测（带子 + 日期 + 校准信息）。"""

    band: PriceBand
    dates: tuple[date, ...]
    measured: dict[str, float]
    measured_source: str
    generated_at: datetime
    notices: tuple[str, ...] = ()


class PriceForecastService:
    """区间预测服务（从价格日历取历史 → 合成带子 → 挂上校准信息）。

    缓存 key = ``(target, horizon, coverage, 最新收盘日, 最新收盘价)`` ⇒
    **新收盘价一进来 key 就变** ⇒ 自动重算（用户要的「不断修正」），且 TTL 到期也会重算。

    ⚠ key 里带**收盘价**（不只是日期）是有意的：数据源会**盘中修订最新一根 K 线**
    （实测同一小时内 3994.0 → 3991.0）⇒ 只用日期做 key 会把修订前的带子留在缓存里。

    ⚠ 基准价取的是**收盘价**（不是盘中实时价）—— 区间是「未来 20 个交易日」的统计推断，
    基准用已收盘的价格才不会让同一个交易日的区间随盘中跳动。
    """

    def __init__(self, session) -> None:
        self._session = session

    async def build(
        self,
        target: str = DEFAULT_TARGET,
        horizon: int = DEFAULT_HORIZON,
        coverage: float = DEFAULT_COVERAGE,
    ) -> PriceForecast:
        """构造区间预测。"""
        from app.repositories.review import GoldPriceRepository

        if coverage not in COVERAGE_Z:
            raise ValueError(f"不支持的覆盖率: {coverage}")

        repo = GoldPriceRepository(self._session)
        last = await repo.latest(target)
        if last is None:
            raise ValueError(f"价格日历里没有 {target} 的数据")
        base_date = last.price_date

        key = (target, horizon, coverage, base_date, float(last.close))
        cached = _CACHE.get(key)
        if cached is not None:
            payload, computed_at = cached
            if (datetime.now(timezone.utc) - computed_at).total_seconds() < CACHE_TTL_SECONDS:
                return payload

        rows = await repo.list_range(target)
        dates = [r.price_date for r in rows]
        closes = [float(r.close) for r in rows]
        if len(closes) < 2:
            raise ValueError(f"价格日历里 {target} 的数据不足 2 行")

        calibration = load_calibration(target)
        shape = load_shape(horizon, target=target)
        band = build_band(
            closes,
            horizon=horizon,
            coverage=coverage,
            shape=shape,
            target=target,
            base_date=base_date,
            first_date=dates[0] if dates else None,
            cross_check_band=load_cross_check_band(calibration),
        )

        measured = measured_coverage(calibration, coverage)
        forecast = PriceForecast(
            band=band,
            dates=tuple(project_trading_dates(base_date, horizon)),
            measured=measured,
            measured_source=(
                "out_of_sample"
                if "out_of_sample" in measured
                else ("calibration" if measured else "")
            ),
            generated_at=datetime.now(timezone.utc),
            notices=(),
        )
        _CACHE[key] = (forecast, forecast.generated_at)
        return forecast


def clear_cache() -> None:
    """清空结果缓存（回填价格日历后要调，否则会拿着旧基准日的带子）。"""
    _CACHE.clear()
