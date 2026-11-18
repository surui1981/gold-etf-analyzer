"""经济危机金价拟合曲线（V0.128.0）。

⚠⚠⚠ **这不是预测，也不是统计回归** —— 它是「**历史形态参照 + 情景假设**」：
把历史危机周期按「距金价阶段高点月数」对齐、以高点归一为 100、逐月**等权平均**成一条模板，
再按当前周期所处的位置缩放（让拟合线**精确穿过当前点**），最后外推未来 N 个月。

算法来源：PM-Evaluator / gold-window-app 的 ``buildCycleFitAverage()``（用户提供的核心逻辑）。
本模块是它在本仓库的**同构实现**（纯 Python、零依赖），并额外加了几条本仓库的纪律：

1. **无前视**：当前周期只用 ≤ 末月的日线；模板只用**历史**周期；
2. **当前周期不得进模板**（自我拟合）—— 用「月份区间重叠」机械判定并剔除；
3. **不合规的周期不修补、直接剔除并告警**（跳月 / 缺高点月 / 口径不明）；
4. **drift 是研究示意假设** ⇒ 接口同时给出 drift=0 的对照终点（页面常驻）；
5. **锚点敏感性**要算出来（锚点月 ±1 的终点差）—— 当前金价在区间上沿时 t0 很小，
   模板最早期主导 ⇒ 不给敏感度就等于藏起了最关键的脆弱点；
6. **数据不足就降级**（available=false + reason），前端画「样本不足」而不是画一条假线。

产物（历史危机周期的月度序列）必须进版本库：
``src/app/assets/forecast/crisis_cycles.json``（``data/`` 被 gitignore）。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "forecast"
CRISIS_CYCLES_FILE = ASSET_DIR / "crisis_cycles.json"

DEFAULT_TARGET = "ny"
DEFAULT_HORIZON_MONTHS = 30
DEFAULT_DRIFT = 0.003

#: 模板至少要有几轮周期才有意义（少于 3 轮 ⇒ 等权均值≈单轮）
MIN_CYCLES = 3

#: 漂移假设的上下界（防止前端传 5 这种把曲线吹上天）
MIN_DRIFT = -0.02
MAX_DRIFT = 0.02


# ────────────────────────────── 月份运算（纯算术，不依赖 datetime 的时区） ──────────────────────────────


def month_index(ym: str) -> int:
    """``"YYYY-MM"`` → 连续月序号（便于做月份加减）。"""
    year_s, month_s = str(ym).split("-")
    return int(year_s) * 12 + (int(month_s) - 1)


def months_between(a: str, b: str) -> int:
    """``b - a`` 的月数（``a`` 在前为正）。"""
    return month_index(b) - month_index(a)


def add_months(ym: str, n: int) -> str:
    """``"YYYY-MM"`` 加 ``n`` 个月 → ``"YYYY-MM"``。"""
    year_s, month_s = str(ym).split("-")
    total = int(year_s) * 12 + (int(month_s) - 1) + int(n)
    return f"{total // 12}-{total % 12 + 1:02d}"


def _is_ym(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 7 or value[4] != "-":
        return False
    head, tail = value[:4], value[5:]
    if not head.isdigit() or not tail.isdigit():
        return False
    return 1 <= int(tail) <= 12


# ────────────────────────────── 当前周期：日线 → 月均价 ──────────────────────────────


@dataclass(frozen=True)
class MonthPoint:
    """某个自然月的月均价。"""

    month: str
    avg: float
    count: int


def aggregate_months(daily_nodes: Sequence[dict]) -> list[MonthPoint]:
    """把日线按自然月聚合成**月均价**（不是月末价 —— 模板是按月对齐的）。

    ⚠ 用月均价而不是月末价：月末价对「月内高低」敏感，等权平均出来的模板会被
    单个极端月末价带偏。口径必须与历史周期序列**一致**（产物里 ``price_basis`` 字段声明）。
    """
    buckets: dict[str, list[float]] = {}
    for node in daily_nodes or []:
        if not isinstance(node, dict):
            continue
        date_s = str(node.get("date") or "")
        if len(date_s) < 7:
            continue
        month = date_s[:7]
        if not _is_ym(month):
            continue
        try:
            value = float(node.get("last"))
        except (TypeError, ValueError):
            continue
        if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
            continue
        buckets.setdefault(month, []).append(value)

    out: list[MonthPoint] = []
    for month in sorted(buckets):
        values = buckets[month]
        avg = sum(values) / len(values)
        out.append(MonthPoint(month=month, avg=avg, count=len(values)))
    return out


def anchor_month_from_days(daily_nodes: Sequence[dict] | None) -> str | None:
    """锚点月 = 日线最高收盘价所在的自然月（算法原口径）。"""
    peak = peak_daily(daily_nodes or [])
    return peak[0][:7] if peak else None


def peak_daily(daily_nodes: Sequence[dict]) -> tuple[str, float] | None:
    """返回日线**最高收盘价**所在的 ``(日期, 价格)``。

    ⚠ 锚点口径必须与算法一致：**日线最高价所在月**（不是「月均价最高的月」——
    两者可能不是同一个月，混用会让「锚点」在页面上说不清）。
    """
    best: tuple[str, float] | None = None
    for node in daily_nodes or []:
        if not isinstance(node, dict):
            continue
        date_s = str(node.get("date") or "")
        if len(date_s) < 7:
            continue
        try:
            value = float(node.get("last"))
        except (TypeError, ValueError):
            continue
        if value != value:  # NaN
            continue
        if best is None or value > best[1]:
            best = (date_s, value)
    return best


# ────────────────────────────── 历史周期 → 模板 ──────────────────────────────


@dataclass
class Cycle:
    """一轮历史危机周期（已通过校验）。"""

    name: str
    short: str
    gold_peak: str
    peak_price: float | None
    series: list[tuple[str, float]]


def make_interpolator(points: Sequence[tuple[float, float]]) -> Callable[[float], float | None]:
    """线性插值器：端点之外做**平台外推**（clamp），不外推斜率。

    ⚠ clamp 而不是线性外推：模板之外的月份没有历史信息，
    外推斜率会让曲线在尾部无根据地继续延伸。
    """
    pts = sorted(points)

    def at(x: float) -> float | None:
        if not pts:
            return None
        if x <= pts[0][0]:
            return pts[0][1]
        if x >= pts[-1][0]:
            return pts[-1][1]
        for i in range(1, len(pts)):
            x0, y0 = pts[i - 1]
            x1, y1 = pts[i]
            if x1 >= x:
                if x1 == x0:
                    return y0
                return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
        return pts[-1][1]

    return at


@dataclass
class Template:
    """等权平均模板 + 逐周期归一路径。

    ⚠ ``names`` 与 ``maps`` **同序** —— 单周期终点要按名字回标，
    放在模板里（而不是模块级全局）⇒ 并发请求不会互相串名。
    """

    template: list[tuple[int, float]]
    maps: list[dict[int, float]] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    counts: list[int] = field(default_factory=list)
    paths: list[list[tuple[int, float]]] = field(default_factory=list)  # 每个 t 由几轮周期平均而来
    at: Callable[[float], float | None] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.at is None:
            self.at = make_interpolator(self.template)


def support_at(counts: Sequence[int], t: int) -> int:
    """模板在第 ``t`` 个月由几轮周期支撑。

    ⚠ 超出模板覆盖范围（``t >= len(counts)``）⇒ 那里是**平台外推** ⇒
    实质上只有**最长那一轮**撑着 ⇒ 记 1（不是 0）。
    """
    if not counts:
        return 0
    if t < 0:
        return int(counts[0])
    if t >= len(counts):
        return 1
    return int(counts[t])


def build_template(cycles: Sequence[Cycle]) -> Template:
    """把每轮周期按「距金价阶段高点月数」对齐、高点归一为 100，逐月**等权平均**。

    - 只取 ``t ≥ 0``（高点之后的部分）；
    - 每期按**可用周期数**平均（不是补 0）—— 缺一轮就少一轮，不该被当成 0；
    - 高点归一用该周期自己的高点价（``gold_peak`` 那一行的价格）。
    """
    maps: list[dict[int, float]] = []
    for cycle in cycles:
        base: float | None = None
        for month, price in cycle.series:
            if month == cycle.gold_peak:
                base = price
                break
        if not base:
            continue
        norm: dict[int, float] = {}
        for month, price in cycle.series:
            t = months_between(cycle.gold_peak, month)
            if t >= 0:
                norm[t] = price / base * 100.0
        if norm:
            maps.append(norm)

    max_t = 0
    for norm in maps:
        if norm:
            max_t = max(max_t, max(norm))

    template: list[tuple[int, float]] = []
    counts: list[int] = []
    for t in range(max_t + 1):
        values = [norm[t] for norm in maps if t in norm]
        if values:
            template.append((t, sum(values) / len(values)))
            counts.append(len(values))

    return Template(
        template=template,
        maps=maps,
        names=[c.short or c.name for c in cycles],
        at=make_interpolator(template),
        counts=counts,
        paths=[sorted(norm.items()) for norm in maps],
    )


# ────────────────────────────── 拟合 ──────────────────────────────


@dataclass
class CycleFit:
    """一次拟合的结果。"""

    meta: dict
    curve: list[dict]
    endpoint: dict | None
    gain_pct: float | None
    cycle_ends: list[dict]


def _fit_once(
    months: Sequence[MonthPoint],
    template: Template,
    anchor_month: str,
    horizon: int,
    drift: float,
) -> CycleFit | None:
    """按给定锚点做一次拟合（E5 的敏感性就是换锚点再跑一次）。"""
    anchor = next((m for m in months if m.month == anchor_month), None)
    if anchor is None or anchor.avg <= 0:
        return None
    last = months[-1]
    t0 = months_between(anchor_month, last.month)
    cur_norm = last.avg / anchor.avg * 100.0
    tpl0 = template.at(t0) if template.at else None
    if tpl0 is None or tpl0 <= 0 or cur_norm != cur_norm:
        return None

    scale = cur_norm / tpl0
    curve: list[dict] = []
    for t in range(t0, t0 + horizon + 1):
        base = template.at(t) if template.at else None
        if base is None:
            continue
        value = base * scale * ((1.0 + drift) ** (t - t0))
        curve.append(
            {
                "t": t,
                "month": add_months(last.month, t - t0),
                "norm": round(value, 1),
                "price": round(anchor.avg * value / 100.0, 0),
            }
        )

    # 单周期终点：每轮周期用自己的路径算相对变化 ⇒ 表达「均值被单轮影响的范围」
    ends: list[dict] = []
    for i, norm_map in enumerate(template.maps):
        own_at = make_interpolator([(float(k), float(v)) for k, v in sorted(norm_map.items())])
        base_now = own_at(t0)
        if not base_now:
            continue
        base_then = own_at(t0 + horizon)
        if not base_then:
            continue
        value = base_then / base_now * cur_norm * ((1.0 + drift) ** horizon)
        name = template.names[i] if i < len(template.names) else f"cycle{i}"
        ends.append(
            {
                "name": name,
                "norm": round(value, 1),
                "price": round(anchor.avg * value / 100.0, 0),
            }
        )

    endpoint = curve[-1] if curve else None
    gain = None
    if endpoint and cur_norm:
        gain = round((endpoint["norm"] / cur_norm - 1) * 100, 1)

    return CycleFit(
        meta={
            "anchor_month": anchor_month,
            "anchor_avg": round(anchor.avg, 2),
            "last_month": last.month,
            "last_avg": round(last.avg, 2),
            "t0": t0,
            "cur_norm": round(cur_norm, 1),
            "horizon": horizon,
            "drift": drift,
        },
        curve=curve,
        endpoint=endpoint,
        gain_pct=gain,
        cycle_ends=ends,
    )


def build_cycle_fit(
    months: Sequence[MonthPoint],
    cycles: Sequence[Cycle],
    daily_nodes: Sequence[dict] | None = None,
    horizon: int = DEFAULT_HORIZON_MONTHS,
    drift: float = DEFAULT_DRIFT,
    anchor_month: str | None = None,
    cycle_names: Sequence[str] | None = None,
) -> CycleFit | None:
    """主拟合：模板 → 对齐当前 → 缩放穿过当前点 → 外推。

    ``anchor_month`` 为空时取**日线最高价所在月**（算法原口径）。
    """
    if not months or not cycles:
        return None
    template = build_template(cycles)
    if len(template.template) < 2:
        return None
    if cycle_names:
        # 调用方显式给了名字 ⇒ 以调用方为准（与 maps 同序）
        template.names = list(cycle_names)

    if anchor_month is None:
        # 锚点 = **日线最高价所在月**（算法原口径）；日线不可用时退回「月均价最高的月」
        anchor_month = anchor_month_from_days(daily_nodes) or max(months, key=lambda m: m.avg).month

    return _fit_once(months, template, anchor_month, horizon, drift)


# ────────────────────────────── 产物加载与校验 ──────────────────────────────


def _read_json(path: Path) -> dict | None:
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load_crisis_cycles(
    target: str = DEFAULT_TARGET,
    horizon: int = DEFAULT_HORIZON_MONTHS,
) -> dict | None:
    """读历史危机周期产物（带 target / horizon 护栏）。

    护栏与 ``price_forecast.load_shape`` 同一套逻辑：**别的标的拿不到 ny 的证据**。
    """
    data = _read_json(CRISIS_CYCLES_FILE)
    if not data:
        return None
    if data.get("target") != target:
        return None
    asset_horizon = data.get("horizon_months")
    if isinstance(asset_horizon, int) and asset_horizon != horizon:
        return None
    return data


def validate_cycles(
    raw_cycles: Any,
    current_months: Iterable[str] | None = None,
) -> tuple[list[Cycle], list[str]]:
    """校验并清洗历史周期：**不合规的不修补，直接剔除并告警**。

    校验项（对应导出契约 §3.1）：

    1. ``series`` 必须是 ``[["YYYY-MM", price], ...]`` 且**按月升序、连续**（跳月 ⇒ 剔除）；
    2. ``goldPeak`` 必须**在 series 里**（归一化的原点）；
    3. 价格必须是有限正数；
    4. **不得与当前周期重叠**（重叠 ⇒ 自我拟合 ⇒ 剔除，证据门 E3）；
    5. ``goldPeak`` 必须是该周期**价格最高的月**（对齐原点错了 ⇒ 形状全错 ⇒ 剔除）。
    """
    warnings: list[str] = []
    out: list[Cycle] = []
    current_set = set(current_months or [])

    if not isinstance(raw_cycles, list):
        return [], ["cycles_not_a_list"]

    for idx, item in enumerate(raw_cycles):
        if not isinstance(item, dict):
            warnings.append(f"cycle#{idx}: 不是对象")
            continue
        name = str(item.get("name") or f"cycle#{idx}")
        short = str(item.get("short") or name)
        gold_peak = item.get("goldPeak")
        series_raw = item.get("series")

        if not _is_ym(gold_peak):
            warnings.append(f"{name}: goldPeak 缺失或格式不对")
            continue
        if not isinstance(series_raw, list) or not series_raw:
            warnings.append(f"{name}: series 缺失")
            continue

        series: list[tuple[str, float]] = []
        broken = False
        for pair in series_raw:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                broken = True
                break
            month, price = pair[0], pair[1]
            if not _is_ym(month):
                broken = True
                break
            try:
                value = float(price)
            except (TypeError, ValueError):
                broken = True
                break
            if value <= 0 or value != value:
                broken = True
                break
            series.append((str(month), value))
        if broken:
            warnings.append(f"{name}: series 有非法项（月份格式 / 价格）")
            continue

        months_seq = [m for m, _ in series]
        if months_seq != sorted(months_seq):
            warnings.append(f"{name}: series 未按月升序")
            continue
        # 连续性：相邻两行必须正好差 1 个月
        gaps = [
            months_between(months_seq[i - 1], months_seq[i])
            for i in range(1, len(months_seq))
            if months_between(months_seq[i - 1], months_seq[i]) != 1
        ]
        if gaps:
            warnings.append(f"{name}: series 跳月（{len(gaps)} 处）—— 距高点月数会错位")
            continue

        peak_rows = [p for m, p in series if m == gold_peak]
        if not peak_rows:
            warnings.append(f"{name}: goldPeak 不在 series 里")
            continue
        peak_price = peak_rows[0]
        actual_peak_month = max(series, key=lambda kv: kv[1])[0]
        if actual_peak_month != gold_peak:
            warnings.append(f"{name}: goldPeak 不是该周期最高月（最高在 {actual_peak_month}）")
            continue

        if current_set and current_set.intersection(months_seq):
            warnings.append(f"{name}: 与当前周期月份重叠 —— 自我拟合，剔除")
            continue

        out.append(
            Cycle(
                name=name,
                short=short,
                gold_peak=str(gold_peak),
                peak_price=peak_price,
                series=series,
            )
        )

    return out, warnings


# ────────────────────────────── 对外：一次完整的服务调用 ──────────────────────────────


@dataclass
class CrisisFitResult:
    """接口层的完整结果（含降级信息）。"""

    available: bool
    reason: str | None = None
    target: str = DEFAULT_TARGET
    horizon_months: int = DEFAULT_HORIZON_MONTHS
    drift: float = DEFAULT_DRIFT
    fit: CycleFit | None = None
    fit_drift0: CycleFit | None = None
    sensitivity: dict | None = None
    anchor_month: str | None = None
    anchor_avg: float | None = None
    peak_date: str | None = None
    peak_price: float | None = None
    last_month: str | None = None
    last_avg: float | None = None
    t0: int | None = None
    cur_norm: float | None = None
    template: list[tuple[int, float]] = field(default_factory=list)
    template_counts: list[int] = field(default_factory=list)  # 每个 t 由几轮周期平均而来
    cycle_paths: list[dict] = field(default_factory=list)  # 拟合集每轮周期的归一路径（均值的原料）
    reference_paths: list[dict] = field(
        default_factory=list
    )  # 参照集（更早的周期）的归一路径，只展示
    fit_window: dict = field(default_factory=dict)  # 拟合窗口（哪段历史参与等权平均）
    reference_window: dict = field(default_factory=dict)  # 参照窗口（只展示、不进拟合）
    support_at_horizon: int | None = None  # 外推终点处由几轮周期支撑（薄了必须让页面看见）
    template_max_t: int | None = None
    template_max_t: int | None = None
    provenance: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def build_crisis_fit(
    daily_nodes: Sequence[dict],
    target: str = DEFAULT_TARGET,
    horizon: int = DEFAULT_HORIZON_MONTHS,
    drift: float = DEFAULT_DRIFT,
    asset: dict | None = None,
) -> CrisisFitResult:
    """完整流程：日线 → 月均价 → 校验周期 → 模板 → 拟合（含 0% 对照与锚点敏感性）。

    ``asset`` 为空时自动读产物（``load_crisis_cycles``）。
    """
    if asset is None:
        asset = load_crisis_cycles(target=target, horizon=horizon)

    if not asset:
        return CrisisFitResult(
            available=False,
            reason="no_crisis_cycles_artifact",
            target=target,
            horizon_months=horizon,
            drift=drift,
        )

    months = aggregate_months(daily_nodes)
    if not months:
        return CrisisFitResult(
            available=False,
            reason="no_price_data",
            target=target,
            horizon_months=horizon,
            drift=drift,
            provenance=asset.get("provenance") or {},
        )

    cycles, warnings = validate_cycles(
        asset.get("cycles"), current_months=[m.month for m in months]
    )
    # ⚠ 参照集（更早的周期）：**只展示、不进模板** —— 用户 2026-11-18 拍板
    #   「拟合只用 2000 年以后，更早的周期放到别的图表显示」。
    #   仍要过同一套校验（不合规的剔除并告警），免得把坏数据画到页面上。
    ref_cycles, ref_warnings = validate_cycles(
        asset.get("reference_cycles") or [], current_months=[m.month for m in months]
    )
    warnings = list(warnings) + list(ref_warnings)
    provenance = asset.get("provenance") or {}

    if len(cycles) < MIN_CYCLES:
        return CrisisFitResult(
            available=False,
            reason="insufficient_cycles",
            target=target,
            horizon_months=horizon,
            drift=drift,
            provenance=provenance,
            warnings=warnings,
        )

    template = build_template(cycles)

    peak = peak_daily(daily_nodes)
    anchor_month = (peak[0][:7] if peak else None) or max(months, key=lambda m: m.avg).month
    fit = _fit_once(months, template, anchor_month, horizon, drift)
    fit0 = _fit_once(months, template, anchor_month, horizon, 0.0)
    if fit is None:
        return CrisisFitResult(
            available=False,
            reason="anchor_not_found",
            target=target,
            horizon_months=horizon,
            drift=drift,
            provenance=provenance,
            warnings=warnings,
        )

    # 锚点敏感性（E5）：锚点月 ±1 时的终点隐含价
    sens_values: list[float] = []
    for shift in (-1, 1):
        alt = add_months(anchor_month, shift)
        alt_fit = _fit_once(months, template, alt, horizon, drift)
        if alt_fit and alt_fit.endpoint:
            sens_values.append(float(alt_fit.endpoint["price"]))
    base_price = float(fit.endpoint["price"]) if fit.endpoint else 0.0
    sensitivity = None
    if sens_values and base_price:
        lo = min([*sens_values, base_price])
        hi = max([*sens_values, base_price])
        sensitivity = {
            "anchor_minus1_price": sens_values[0] if len(sens_values) > 0 else None,
            "anchor_plus1_price": sens_values[1] if len(sens_values) > 1 else None,
            "low": round(lo, 0),
            "high": round(hi, 0),
            "spread_pct": round((hi - lo) / base_price * 100.0, 1) if base_price else None,
        }

    # 参照集的归一路径（各轮各自归一，高点=100）—— 只给第二张图用
    ref_template = build_template(ref_cycles) if ref_cycles else Template(template=[])
    reference_paths = [
        {
            "name": ref_template.names[i] if i < len(ref_template.names) else f"cycle{i}",
            "points": [[int(t), round(float(v), 2)] for t, v in ref_template.paths[i]],
        }
        for i in range(len(ref_template.paths))
    ]

    return CrisisFitResult(
        available=True,
        reason=None,
        target=target,
        horizon_months=horizon,
        drift=drift,
        fit=fit,
        fit_drift0=fit0,
        sensitivity=sensitivity,
        template=template.template,
        reference_paths=reference_paths,
        fit_window=asset.get("fit_window") or {},
        reference_window=asset.get("reference_window") or {},
        support_at_horizon=support_at(template.counts, int(fit.meta.get("t0") or 0) + horizon),
        template_counts=template.counts,
        cycle_paths=[
            {
                "name": template.names[i] if i < len(template.names) else f"cycle{i}",
                "points": [[int(t), round(float(v), 2)] for t, v in template.paths[i]],
            }
            for i in range(len(template.paths))
        ],
        template_max_t=(template.template[-1][0] if template.template else None),
        provenance=provenance,
        warnings=warnings,
        anchor_month=fit.meta.get("anchor_month"),
        anchor_avg=fit.meta.get("anchor_avg"),
        peak_date=peak[0] if peak else None,
        peak_price=round(peak[1], 2) if peak else None,
        last_month=fit.meta.get("last_month"),
        last_avg=fit.meta.get("last_avg"),
        t0=fit.meta.get("t0"),
        cur_norm=fit.meta.get("cur_norm"),
    )


def clear_cache() -> None:  # pragma: no cover - 与 price_forecast 的接口保持一致
    """占位：本服务目前不做进程内缓存（计算量极小）。"""
    return None
