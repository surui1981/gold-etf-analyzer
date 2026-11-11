#!/usr/bin/env python
"""金价区间带的**离线校准**（V0.127.0）—— 产出形状曲线与实测覆盖率。

产出两个**入版本库**的口径产物：

- ``src/app/assets/forecast/shape.json`` —— 扇形形状曲线 ``shape_k``（k=1..H，末位 = 1.0）
  以及它相对对数正态 √k 锥的比值（短端更胖多少）；
- ``src/app/assets/forecast/calibration.json`` —— 每个覆盖率档的**实测**覆盖率
  （训练段 / 样本外 / 近段三个口径）+ 样本量。

为什么必须离线
--------------
线上服务要「秒级」出结果，而覆盖率只能靠 walk-forward 反复回测才测得出
⇒ 离线算好落盘，线上只读。**口径是产品的一部分**，所以产物进版本库（可 review、可 diff）。

⚠ **三条不可退让的约束**
1. **无前视**：算基准日 D 的带子时只能用 ≤ D 的数据；
2. **实测值不是名义值**：名义 80% 实测可能只有 77.9% ⇒ 产物里同时记两者，UI 显示**实测**；
3. **产物缺失不致命**：服务读到缺失会退回 √k 锥（``method="vol_only"``）并标注原因。

用法
----
::

    # 干跑：只打印将要写什么（默认）
    PYTHONPATH=src:. python -m scripts.calibrate_price_band --target ny --horizon 20

    # 真写产物（开发库 = .env 指向的 SQLite）
    PYTHONPATH=src:. python -m scripts.calibrate_price_band --target ny --horizon 20 --apply

    # 生产库口径（.env.mysql 里是 MySQL 库；密钥不进 argv）
    PYTHONPATH=src:. python -m scripts.calibrate_price_band --env-file .env.mysql --apply

    # 校验：重算并与已有产物比对 ⇒ 口径漂移会变红（CI 可跑）
    PYTHONPATH=src:. python -m scripts.calibrate_price_band --verify
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.backfill_price_calendar import inject_database_url

# 口径产物目录（与 src/app/services/price_forecast.py::ASSET_DIR 同一个）
ASSET_DIR = Path(__file__).resolve().parent.parent / "src" / "app" / "assets" / "forecast"
SHAPE_FILE = ASSET_DIR / "shape.json"
CALIBRATION_FILE = ASSET_DIR / "calibration.json"

# 校准窗口（用**下标**而不是写死的日期 ⇒ 数据往前滚时口径自动跟着走）
OOS_SAMPLES = 250  # 样本外：最后 250 个预测日
RECENT_SAMPLES = 120  # 近段：最后 120 个预测日（样本外的子集）
SHAPE_SAMPLES = 300  # 形状曲线：最近 300 个预测日
SHAPE_STABILITY_SAMPLES = 600  # 形状稳定性对照：最近 600 个预测日
CROSS_CHECK_SAMPLES = 300  # 两法交叉校验的统计窗口：最近 300 个预测日
WARMUP = 250  # 预测日之前的最小历史（σ 要稳、类比要有候选）


def _canonical_digest(payload: object) -> str:
    """对产物内容取 sha256（``--verify`` 靠它做**精确**漂移检测）。"""
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _percentile(values: list[float], pct: float) -> float:
    """线性插值分位（与 numpy.percentile(method="linear") 一致）。

    ⚠ 与 ``app.services.macro_thresholds._percentile`` 是同一套口径 ——
    这里**重写一份**是刻意的：校准脚本要能在**不导入 app 包**的情况下独立跑
    （``app.*`` 的导入会把配置与数据库连接一起拖进来）。
    两份实现必须保持一致 ⇒ 由 ``tests/test_scripts/test_calibrate_price_band.py`` 对拍锁死。
    """
    n = len(values)
    if n == 0:
        return 0.0
    if n == 1:
        return float(values[0])
    rank = (pct / 100.0) * (n - 1)
    lower = int(rank)
    upper = min(lower + 1, n - 1)
    frac = rank - lower
    return float(values[lower] * (1 - frac) + values[upper] * frac)


def ewma_sigma_series(closes: list[float], lam: float = 0.94) -> list[float]:
    """与 ``app.services.price_forecast.ewma_sigma_series`` 同口径的 σ 序列（因果）。

    ⚠ 这里同样重写一份，理由同上（独立可跑）；一致性由单测对拍锁死。
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


def analog_shape_at(
    closes: list[float],
    sigmas: list[float],
    idx: int,
    horizon: int,
    lo_pct: float,
    tol: float = 0.25,
    min_sim: int = 30,
) -> tuple[list[float], int, float] | None:
    """基准日 ``idx`` 上的类比形状（相对 horizon 归一）+ 相似日数 + horizon 半宽。

    与 ``app.services.price_forecast.analog_shape_at`` 同口径（重写理由同上）。
    """
    n = len(closes)
    if idx < 1 or idx >= n:
        return None
    sigma_idx = sigmas[idx]
    if sigma_idx <= 0:
        return None
    max_s = idx - horizon  # 无前视：s + horizon <= idx
    if max_s < 1:
        return None
    candidates = [s for s in range(1, max_s + 1) if abs(sigmas[s] / sigma_idx - 1.0) <= tol]
    if len(candidates) < min_sim:
        return None

    per_k: list[list[float]] = [[] for _ in range(horizon)]
    for s in candidates:
        base = closes[s]
        if base <= 0:
            continue
        for k in range(1, horizon + 1):
            j = s + k
            if j >= n:
                continue
            val = closes[j]
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
        upper.append(_percentile(vals, 100.0 - lo_pct))
    halfs = [(hi - lo) / 2 for lo, hi in zip(lower, upper, strict=True)]
    total = halfs[-1] if halfs else 0.0
    if total <= 0:
        return None
    return [h / total for h in halfs], len(candidates), total


def _span_stats(
    closes: list[float],
    sigmas: list[float],
    idxs: list[int],
    horizon: int,
    z: float,
) -> tuple[int, int]:
    """返回 (命中数, **实际参与判定的样本数**) —— EWMA 对数正态带在 horizon 处的覆盖率。

    ⚠ 带宽只由 σ 与 z 决定（形状在 horizon 处恒为 1.0）⇒ 覆盖率与形状无关。
    ⚠ 分母必须是「**实际判定过的**样本数」，不是 ``len(idxs)`` ——
    ``i + horizon`` 越界的预测日会被跳过，若把分母写成 ``len(idxs)``，
    覆盖率会被**系统性低估**（分母虚高）⇒ 校准值偏保守但数字是假的。
    """
    hit = 0
    evaluated = 0
    for i in idxs:
        j = i + horizon
        if j >= len(closes):
            continue
        sigma = sigmas[i]
        if sigma <= 0 or closes[i] <= 0 or closes[j] <= 0:
            continue
        half = z * sigma * math.sqrt(horizon)
        lo = closes[i] * math.exp(-half)
        hi = closes[i] * math.exp(+half)
        evaluated += 1
        if lo <= closes[j] <= hi:
            hit += 1
    return hit, evaluated


def _monotone_envelope(shape: list[float]) -> tuple[list[float], int]:
    """把形状曲线取**单调包络**（累计最大）。

    为什么要这一步：形状是「多个预测日的类比形状取平均」⇒ 平均会把逐日的
    微小非单调噪声带进来。扇形图里带子必须**越走越宽**，否则导航线的边缘会起毛刺。
    ⇒ 取累计最大（只会上调个别点，不会压低），并记录被调整了几个点（照实写进产物）。

    ⚠ 只影响 k < H 的中间点；k = H 处恒为 1.0（包络不改变它）⇒ **覆盖率不受影响**
    （覆盖率只看 horizon 处的端点）。
    """
    out: list[float] = []
    running = 0.0
    adjusted = 0
    for v in shape:
        if v < running:
            adjusted += 1
            v = running
        else:
            running = v
        out.append(v)
    if out and out[-1] > 0:
        scale = 1.0 / out[-1]
        out = [v * scale for v in out]
    return out, adjusted


def _avg_shape(
    closes: list[float],
    sigmas: list[float],
    idxs: list[int],
    horizon: int,
    lo_pct: float,
) -> tuple[list[float], int]:
    """把多个预测日的类比形状取平均（逐 k），并归一到末位 = 1.0。"""
    acc = [0.0] * horizon
    used = 0
    for i in idxs:
        got = analog_shape_at(closes, sigmas, i, horizon, lo_pct)
        if got is None:
            continue
        shape = got[0]
        for k in range(horizon):
            acc[k] += shape[k]
        used += 1
    if used == 0:
        return [], 0
    avg = [a / used for a in acc]
    total = avg[-1]
    if total <= 0:
        return [], 0
    return [a / total for a in avg], used


def _digest_payload(
    shape: list[float],
    coverages: dict,
    spans: dict,
) -> str:
    """把「口径数值」单独取指纹（不含生成时间 ⇒ 重跑不会因为时间戳而漂移）。"""
    payload = {
        "shape": [round(v, 12) for v in shape],
        "coverages": {
            k: {kk: (round(vv, 12) if isinstance(vv, float) else vv) for kk, vv in v.items()}
            for k, v in coverages.items()
        },
        "spans": spans,
    }
    return _canonical_digest(payload)


def compute(
    closes: list[float],
    dates: list[date],
    horizon: int,
    coverages: list[float],
    z_map: dict[float, float],
    lam: float = 0.94,
    tol: float = 0.25,
    min_sim: int = 30,
) -> dict:
    """算出形状曲线 + 各覆盖率档的实测覆盖率。

    Returns:
        ``{"shape": [...], "coverages": {...}, "spans": {...}, "raw": {...}}``
    """
    sigmas = ewma_sigma_series(closes, lam)
    n = len(closes)
    # 预测日集合：需要足够的预热历史，且 horizon 之后还有真实价格可核对
    idxs = [
        i
        for i in range(WARMUP, n - horizon)
        if sigmas[i] > 0 and closes[i] > 0 and closes[i + horizon] > 0
    ]
    if len(idxs) < 50:
        raise SystemExit(
            f"可用预测日只有 {len(idxs)} 个（需要 ≥ 50）⇒ 数据深度不够，"
            "先跑 scripts/backfill_price_calendar.py --deep"
        )

    oos = idxs[-OOS_SAMPLES:]
    train = idxs[: len(idxs) - len(oos)]
    recent = idxs[-RECENT_SAMPLES:]
    shape_idxs = idxs[-SHAPE_SAMPLES:]
    stability_idxs = idxs[-SHAPE_STABILITY_SAMPLES:]
    cross_check_idxs = idxs[-CROSS_CHECK_SAMPLES:]

    lo_pct = (100.0 - 0.80 * 100.0) / 2.0  # 形状用 80% 档算（宽度口径与展示口径一致）
    shape_raw, n_shape = _avg_shape(closes, sigmas, shape_idxs, horizon, lo_pct)
    shape, n_adjusted = _monotone_envelope(shape_raw)
    shape_600, n_600 = _avg_shape(closes, sigmas, stability_idxs, horizon, lo_pct)
    shape_train, n_train_shape = _avg_shape(closes, sigmas, train, horizon, lo_pct)

    cone = [math.sqrt(k / horizon) for k in range(1, horizon + 1)]

    cov_out: dict[str, dict] = {}
    for cov in coverages:
        z = z_map[cov]
        hit_tr, n_tr = _span_stats(closes, sigmas, train, horizon, z)
        hit_oos, n_oos = _span_stats(closes, sigmas, oos, horizon, z)
        hit_re, n_re = _span_stats(closes, sigmas, recent, horizon, z)
        cov_out[str(round(cov * 100))] = {
            "nominal": cov,
            "z": z,
            "train": hit_tr / n_tr if n_tr else None,
            "out_of_sample": hit_oos / n_oos if n_oos else None,
            "recent": hit_re / n_re if n_re else None,
            "n_train": n_tr,
            "n_out_of_sample": n_oos,
            "n_recent": n_re,
        }

    spans = {
        "train": {
            "from": dates[train[0]].isoformat() if train else None,
            "to": dates[train[-1]].isoformat() if train else None,
            "n_samples": len(train),
        },
        "out_of_sample": {
            "from": dates[oos[0]].isoformat() if oos else None,
            "to": dates[oos[-1]].isoformat() if oos else None,
            "n_samples": len(oos),
        },
        "recent": {
            "from": dates[recent[0]].isoformat() if recent else None,
            "to": dates[recent[-1]].isoformat() if recent else None,
            "n_samples": len(recent),
        },
    }

    # 两法交叉校验的实测统计（最近 CROSS_CHECK_SAMPLES 个预测日）
    #
    # ⚠ **判据不是「两法是否相等」** —— 实测类比带的尾部系统性比整体薄
    # （宽度比均值 0.615），「差 > 40%」在 **39% 的日子里都成立** ⇒ 用它当告警判据
    # 等于天天告警（噪声）。真正的异常是「今天的比值落在历史分布之外」。
    # ⇒ 记录比值的分布，运行时用它判定「异常宽 / 异常窄」。
    disagree = 0
    ratios: list[float] = []
    for i in cross_check_idxs:
        got = analog_shape_at(closes, sigmas, i, horizon, lo_pct)
        if got is None:
            continue
        _shape, _n, analog_half = got
        ewma_half = z_map[0.80] * sigmas[i] * math.sqrt(horizon)
        if ewma_half <= 0:
            continue
        ratio = analog_half / ewma_half
        ratios.append(ratio)
        if abs(ratio - 1.0) > 0.40:
            disagree += 1
    ratios_sorted = sorted(ratios)

    return {
        "shape": shape,
        "cone": cone,
        "shape_over_cone": ([s / c for s, c in zip(shape, cone, strict=True)] if shape else []),
        "shape_stability": {
            "recent_600": {"shape": shape_600, "n_days": n_600},
            "train": {"shape": shape_train, "n_days": n_train_shape},
        },
        "coverages": cov_out,
        "spans": spans,
        "cross_check": {
            "n_samples": len(ratios),
            "disagree_ratio": disagree / len(ratios) if ratios else None,
            "mean_ratio": (sum(ratios) / len(ratios)) if ratios else None,
            "max_ratio": max(ratios) if ratios else None,
            "min_ratio": min(ratios) if ratios else None,
            "p05": _percentile(ratios_sorted, 5) if ratios_sorted else None,
            "p50": _percentile(ratios_sorted, 50) if ratios_sorted else None,
            "p95": _percentile(ratios_sorted, 95) if ratios_sorted else None,
            "note": (
                "比值 = 类比带半宽 ÷ EWMA 带半宽。实测均值 ≈ 0.6（类比带尾部系统性更薄）。"
                "⚠ 「差 > 40%」是常态而非异常 ⇒ 运行时判据是「比值落在 [p05, p95] 之外」，"
                "不是「两法不相等」。"
            ),
        },
        "n_prediction_days": len(idxs),
        "n_shape_days": n_shape,
        "n_monotone_adjusted": n_adjusted,
        "shape_raw": shape_raw,
    }


async def _load_closes(target: str) -> tuple[list[date], list[float]]:
    """从库里取 (日期, 收盘价) 升序序列。"""
    from app.repositories.db import async_session_factory
    from app.repositories.review import GoldPriceRepository

    async with async_session_factory() as session:
        rows = await GoldPriceRepository(session).list_range(target)
    if len(rows) < 100:
        raise SystemExit(f"库内 {target} 只有 {len(rows)} 行，不足以校准（先跑深度回填）")
    dates = [r.price_date for r in rows]
    closes = [float(r.close) for r in rows]
    return dates, closes


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")


def _read(path: Path) -> dict | None:
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="金价区间带离线校准（V0.127.0）")
    parser.add_argument("--target", default="ny", help="标的（默认 ny = COMEX 纽约金）")
    parser.add_argument("--horizon", type=int, default=20, help="期限（交易日，默认 20）")
    parser.add_argument("--apply", action="store_true", help="真的写产物（默认只干跑）")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="重算并与已有产物比对（口径漂移 ⇒ 退出码非 0）",
    )
    parser.add_argument("--env-file", default=None, help="从该文件读 DATABASE_URL（密钥不进 argv）")
    parser.add_argument(
        "--database-url", default=None, help="直接指定 DATABASE_URL（⚠ 口令会进 argv）"
    )
    args = parser.parse_args(argv)

    inject_database_url(sys.argv[1:])

    from app.config import get_settings
    from app.services.price_forecast import COVERAGE_Z

    settings = get_settings()
    print(f"=== 目标数据库：{settings.database_url.split('@')[-1]} ===")

    dates, closes = asyncio.run(_load_closes(args.target))
    print(
        f"数据：{args.target} 共 {len(closes)} 行，{dates[0]} → {dates[-1]}"
        f"（末根收盘 {closes[-1]}）"
    )

    result = compute(
        closes=closes,
        dates=dates,
        horizon=args.horizon,
        coverages=sorted(COVERAGE_Z),
        z_map=COVERAGE_Z,
    )

    shape = result["shape"]
    if not shape:
        print("❌ 相似日不足，算不出形状曲线（类比法在本数据上不适用）")
        return 2

    print(f"预测日样本：{result['n_prediction_days']} 个；形状用 {result['n_shape_days']} 个")
    print("形状（相对 20 日总宽归一）：")
    for k, (s, c, r) in enumerate(
        zip(shape, result["cone"], result["shape_over_cone"], strict=True), start=1
    ):
        print(f"  k={k:2d}  类比 {s:.4f}   √k锥 {c:.4f}   比值 {r:.3f}")
    print("实测覆盖率（EWMA 对数正态带）：")
    for _key, entry in result["coverages"].items():
        print(
            f"  名义 {entry['nominal']:.0%}  训练 {entry['train']:.1%}  "
            f"样本外 {entry['out_of_sample']:.1%}  近段 {entry['recent']:.1%}"
            f"  (n={entry['n_out_of_sample']})"
        )
    cc = result["cross_check"]
    print(
        f"两法交叉校验：近 {cc['n_samples']} 个预测日中，宽度差 >40% 的占 "
        f"{(cc['disagree_ratio'] or 0):.1%}；宽度比均值 {cc['mean_ratio']:.3f}"
    )

    digest = _digest_payload(shape, result["coverages"], result["spans"])
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    source = {
        "table": "gold_price_daily",
        "target": args.target,
        "rows": len(closes),
        "first_date": dates[0].isoformat(),
        "last_date": dates[-1].isoformat(),
    }
    params = {"ewma_lambda": 0.94, "tolerance": 0.25, "min_sim": 30, "horizon": args.horizon}

    shape_payload = {
        "schema": "price-forecast-shape/1",
        "target": args.target,
        "horizon": args.horizon,
        "generated_at": now,
        "generator": "scripts/calibrate_price_band.py",
        "source": source,
        "params": params,
        "shape": [round(v, 6) for v in shape],
        "cone": [round(v, 6) for v in result["cone"]],
        "shape_over_cone": [round(v, 6) for v in result["shape_over_cone"]],
        "shape_stability": {
            "recent_600": {
                "shape": [round(v, 6) for v in result["shape_stability"]["recent_600"]["shape"]],
                "n_days": result["shape_stability"]["recent_600"]["n_days"],
            },
            "train": {
                "shape": [round(v, 6) for v in result["shape_stability"]["train"]["shape"]],
                "n_days": result["shape_stability"]["train"]["n_days"],
            },
        },
        "n_prediction_days": result["n_prediction_days"],
        "n_shape_days": result["n_shape_days"],
        "n_monotone_adjusted": result["n_monotone_adjusted"],
        "shape_raw": [round(v, 6) for v in result["shape_raw"]],
        "digest": digest,
        "notes": [
            "shape_k = 类比带在 k 日处的半宽 ÷ 类比带在 H 日处的半宽；末位恒为 1.0。",
            "shape 是「形状_raw 取单调包络」的结果（累计最大）—— 去掉平均带来的微小非单调噪声；"
            f"本轮调整了 {result['n_monotone_adjusted']} 个点。覆盖率不受影响（只看 horizon 端点）。",
            "shape_over_cone = shape_k ÷ √(k/H)：> 1 表示短期比对数正态更胖。",
            "shape_stability 是同一算法在另两个窗口上的结果 ⇒ 用来判断形状稳不稳。",
        ],
    }
    calib_payload = {
        "schema": "price-forecast-calibration/1",
        "target": args.target,
        "horizon": args.horizon,
        "generated_at": now,
        "generator": "scripts/calibrate_price_band.py",
        "source": source,
        "params": params,
        "method": "ewma_lognormal",
        "spans": result["spans"],
        "coverages": {key: {**entry, "digest": None} for key, entry in result["coverages"].items()},
        "cross_check": result["cross_check"],
        "digest": digest,
        "notes": [
            "覆盖率是 walk-forward 实测值：算基准日 D 的带子时只用 ≤ D 的数据。",
            "out_of_sample = 最后 250 个预测日；train = 其之前；recent = 最后 120 个（样本外的子集）。",
            "⚠ 实测覆盖率低于名义值是常态 —— UI 必须显示实测值，不得显示名义值。",
        ],
    }

    if args.verify:
        ok = True
        for path, payload in ((SHAPE_FILE, shape_payload), (CALIBRATION_FILE, calib_payload)):
            existing = _read(path)
            if existing is None:
                print(f"❌ 产物不存在: {path}")
                ok = False
                continue
            if existing.get("digest") != payload["digest"]:
                print(f"❌ 口径漂移: {path.name}（产物 digest ≠ 重算 digest）")
                print(f"   产物: {existing.get('digest')}")
                print(f"   重算: {payload['digest']}")
                ok = False
            else:
                print(f"✅ 一致: {path.name}")
        return 0 if ok else 1

    if not args.apply:
        print("干跑结束：加 --apply 才会写产物")
        return 0

    _write(SHAPE_FILE, shape_payload)
    _write(CALIBRATION_FILE, calib_payload)
    print(f"已写: {SHAPE_FILE}")
    print(f"已写: {CALIBRATION_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
