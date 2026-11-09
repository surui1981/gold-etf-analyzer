"""宏观因子历史回填（V0.118.0）。

为什么需要
----------
V0.79.0 Step E 造了「近 252 个交易日滚动 90/10 分位」的动态阈值机制，但**从未真正
生效**：``daily_macro_factors`` 表在 2026-10-25 只有 **18 天**样本，而
``MacroThresholdCalculator`` 要求单因子 ≥ ``min_samples``（60）才肯切动态阈值。

后果是全部因子都钉死在 2020-2023 的硬编码 ``best/worst`` 上，而那些阈值在
2024-2026 的市场结构下早已越界：

===========  ==========  ==========  ==============================
因子          当前值      硬编码阈值   友好度
===========  ==========  ==========  ==============================
``us10y``     4.96%      3.5 / 4.5   **0 分**（触底）
``us30y``     5.29%      4.0 / 5.0   **0 分**（触底）
===========  ==========  ==========  ==============================

两个因子的合计权重 35% 贡献恒为 0 —— 宏观面 40%、综合指数 40%，
等于综合指数的 **14% 是死重**（``docs/parameter-evaluation.md`` §3.2 两版前
提出过这个问题，一直没做）。

怎么修
------
**数据一直都在，只是没被采集。** 三个源都自带多年历史：

- 美联储 H.15 CSV：1976 年至今，13148 个有 2Y/10Y/30Y 的交易日；
- FRED ``DFII10``（实际利率）：2003 年至今；
- FRED ``VIXCLS``：1990 年至今；
- Yahoo ``DX-Y.NYB``（DXY）：2 年日线（约 610 个点）。

把它们回填进 ``daily_macro_factors``，滚动分位立刻就有 ≥252 个样本可用，
阈值自动跟随市场 —— 不再需要手工维护 ``best/worst``。

**幂等**：按 ``(target, snapshot_date, factor_key)`` 覆盖写，重复跑不会产生脏数据。
**只补缺口**：已达 ``min_samples`` 的因子直接跳过，日常调度调用它几乎零成本。
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import date, timedelta

from app.repositories.macro_factor_history import MacroFactorHistoryRepository
from app.services.macro_history import (
    FRED_PERIODIC_FACTORS,
    Observation,
    Row,
    asof_rows,
    build_observations,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: 回填时每个因子至少要有的样本数（低于此值说明历史缺口大，补）
DEFAULT_MIN_SAMPLES = 60

#: 默认回填窗口（交易日）。滚动分位窗口本身就是 252 日，取同样的长度最自然。
DEFAULT_WINDOW_DAYS = 252


async def backfill_macro_history(
    repo: MacroFactorHistoryRepository,
    *,
    target: str = "default",
    days: int = DEFAULT_WINDOW_DAYS,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    today: date | None = None,
    force: bool = False,
) -> dict[str, int]:
    """把 H.15 / FRED / Yahoo 的自带历史回填进 ``daily_macro_factors``。

    返回 ``{factor_key: 写入行数}``。

    参数
    ----
    - ``days``：回填窗口（自然日）；实际写入的是该窗口内**有数据的交易日**。
    - ``min_samples``：某因子窗口内已有样本 ≥ 此值则**跳过**（避免每天重拉全量历史）。
    - ``force``：忽略 ``min_samples`` 检查，强制重写窗口内所有可得数据。

    只回填**有真实行情源**的因子。``cb_gold``（央行季度购金）没有可回填的日频历史
    —— 它本来就是季度合计，``MacroThresholdCalculator`` 对它显式跳过滚动。
    """
    end = today or date.today()
    start = end - timedelta(days=days)

    # ── 1. 哪些因子需要补 ──
    need: set[str] = set()
    for key in ("dxy", "us2y", "us10y", "us30y", "curve_10y2y", "real10y", "vix"):
        if force:
            need.add(key)
            continue
        count = await repo.count_samples(target, key, days, end_date=end)
        if count < min_samples:
            logger.info("宏观因子 %s 历史仅 %d 样本（<%d），需要回填", key, count, min_samples)
            need.add(key)

    if not need:
        logger.info("宏观因子历史充足（≥%d 样本），跳过回填", min_samples)
        return {}

    # ── 2. 并发取历史 ──
    h15_hist, fred_hist, yahoo_hist = await asyncio.gather(
        _fetch_h15_history(),
        _fetch_fred_history(),
        _fetch_yahoo_history(),
        return_exceptions=True,
    )
    for name, res in (
        ("H.15", h15_hist),
        ("FRED", fred_hist),
        ("Yahoo", yahoo_hist),
    ):
        if isinstance(res, BaseException):
            logger.warning("%s 历史取数失败: %s", name, res)

    h15_hist = h15_hist if not isinstance(h15_hist, BaseException) else []
    fred_hist = fred_hist if not isinstance(fred_hist, BaseException) else {}
    yahoo_hist = yahoo_hist if not isinstance(yahoo_hist, BaseException) else {}

    # ── 3. 组装成 (snapshot_date, factor_key, value, data_date, source) 行 ──
    rows: list[tuple[date, str, float, str, str]] = []

    # H.15 → us2y / us10y / us30y / curve_10y2y（派生）
    for d, v2y, v10, v30 in h15_hist:
        if not (start <= d <= end):
            continue
        iso = d.isoformat()
        if "us2y" in need and v2y is not None:
            rows.append((d, "us2y", v2y, iso, "美联储 H.15"))
        if "us10y" in need:
            rows.append((d, "us10y", v10, iso, "美联储 H.15"))
        if "us30y" in need:
            rows.append((d, "us30y", v30, iso, "美联储 H.15"))
        if "curve_10y2y" in need and v2y is not None:
            rows.append((d, "curve_10y2y", round(v10 - v2y, 3), iso, "派生 10Y-2Y"))

    # FRED → real10y (DFII10) / vix (VIXCLS)
    for series_id, factor_key in (("DFII10", "real10y"), ("VIXCLS", "vix")):
        if factor_key not in need:
            continue
        for d, v in fred_hist.get(series_id, []):
            if not (start <= d <= end):
                continue
            rows.append((d, factor_key, v, d.isoformat(), f"FRED {series_id}"))

    # Yahoo → dxy (DX-Y.NYB)
    if "dxy" in need:
        for d, v in yahoo_hist:
            if not (start <= d <= end):
                continue
            rows.append((d, "dxy", v, d.isoformat(), "Yahoo DX-Y.NYB"))

    if not rows:
        logger.warning("宏观因子回填：窗口内没有可用历史数据")
        return {}

    written = await repo.upsert_many(target, rows)

    by_factor: dict[str, int] = {}
    for _, factor_key, *_ in rows:
        by_factor[factor_key] = by_factor.get(factor_key, 0) + 1
    logger.info(
        "宏观因子历史回填完成：%d 行（%s）",
        written,
        "，".join(f"{k}={v}" for k, v in sorted(by_factor.items())),
    )
    return by_factor


# ───────────────────── 各源历史取数 ─────────────────────


async def _fetch_h15_history() -> list[tuple[date, float | None, float, float]]:
    """美联储 H.15 全量历史 → ``[(日期, us2y, us10y, us30y), ...]``。

    ⚠️ **必须带浏览器 UA** —— H.15 的 WAF 对不发 UA 的请求直接回 403
    （与 Yahoo 同一套规则；FRED 才是相反的那套）。见 ``macro_sources._http_text``
    docstring 里的三源 UA 实测表。
    """
    from app.config import get_settings
    from app.repositories.macro_sources import BROWSER_UA, _http_text
    from app.repositories.market_data import parse_h15_history

    cfg = get_settings()
    text = await asyncio.to_thread(_http_text, cfg.h15_csv_url, 30, BROWSER_UA)
    return parse_h15_history(text)


async def _fetch_fred_history() -> dict[str, list[tuple[date, float]]]:
    """FRED 全量历史 → ``{series_id: [(日期, 值), ...]}``。"""
    from app.config import get_settings
    from app.repositories.macro_sources import fetch_fred_series

    cfg = get_settings()
    out: dict[str, list[tuple[date, float]]] = {}
    for series_id in ("DFII10", "VIXCLS"):
        out[series_id] = await fetch_fred_series(series_id, base_url=cfg.fred_csv_url)
    return out


async def _fetch_yahoo_history() -> list[tuple[date, float]]:
    """Yahoo DXY 日线 → ``[(日期, 收盘价), ...]``。"""
    from app.config import get_settings
    from app.repositories.macro_sources import fetch_yahoo_daily

    cfg = get_settings()
    return await fetch_yahoo_daily("DX-Y.NYB", base_url=cfg.yahoo_chart_url, range_="2y")


# ═══════════════════════════════════════════════════════════════
# V0.124.0 · 深回填（11 因子 × 多年 × 日历日，point-in-time）
# ═══════════════════════════════════════════════════════════════

#: 深回填默认窗口（自然日）—— 5 年。
#:
#: 为什么是 5 年：roadmap §三·C6 要求「≥ 3 年」；5 年给 252 日滚动窗口
#: 留了两次余量，也给「三个子区间各 ~1.7 年」的检验留了空间。
#: 11 因子 × 1826 日历日 ≈ **2 万行**（SQLite 无压力）。
DEEP_WINDOW_DAYS = 1825

#: 深回填覆盖的 11 个因子（= ``MACRO_FACTOR_RULES`` 的全部 key）。
DEEP_DAILY_FACTORS = (
    "dxy",
    "us2y",
    "us10y",
    "us30y",
    "curve_10y2y",
    "real10y",
    "vix",
)
DEEP_LOWFREQ_FACTORS = ("cb_gold", "us_gov_debt", "cn_gov_debt", "eu_gov_debt")
DEEP_FACTORS = DEEP_DAILY_FACTORS + DEEP_LOWFREQ_FACTORS

#: 低频因子的 FRED 序列 → (观测期类型)。与 ``macro_sources.FRED_PERIODIC_SERIES`` 同源。
#:
#: ⚠ 真源在 ``services/macro_history.py::FRED_PERIODIC_FACTORS`` ——
#: 生产回填与证据脚本共用同一份映射（V0.124.0 抽出来，避免各抄一份必然腐化）。
_DEEP_FRED_PERIODIC = FRED_PERIODIC_FACTORS


async def _fetch_yahoo_dxy_deep(start: date, end: date) -> list[tuple[date, float]]:
    """Yahoo DXY **日线**深历史（区间端点）→ ``[(日期, 收盘价), ...]``。

    ⚠ 不用 ``range`` 参数：``range="max"`` 会被 Yahoo 自动降频成月线级
    （实测只回 169 根）；``period1``/``period2`` 才是日线级深历史
    （实测可回 1999-12-31、8232 根）。
    """
    from app.config import get_settings
    from app.repositories.macro_sources import fetch_yahoo_daily_period

    cfg = get_settings()
    return await fetch_yahoo_daily_period(
        "DX-Y.NYB",
        base_url=cfg.yahoo_chart_period_url,
        start=start,
        end=end,
    )


#: Yahoo DXY 取数的**回看余量**（自然日）。
#:
#: ⚠ **V0.124.0 的实测教训**：Yahoo 是**唯一一个按窗口取数**的源
#: （H.15 / FRED / Eurostat 都是全量历史）⇒ 窗口第一天的「当时能拿到的最新读数」
#: 必须来自**窗口之前**的一次观测 ⇒ 若不预留回看，窗口第一天的 DXY 会**整行缺失**
#: （实测：脚本重建有 ``2021-11-10 dxy``，生产回填没有 ⇒ X1 差 1 行）。
#: 回看量要盖住「Yahoo 发布时滞（B+1 天）」+「长假」⇒ 取 30 天。
YAHOO_LOOKBACK_DAYS = 30


async def _fetch_eurostat_deep() -> list[tuple[date, float]]:
    """Eurostat 季度一般政府债务/GDP **全历史** → ``[(期末日, 值), ...]``。"""
    from app.config import get_settings
    from app.repositories.macro_sources import fetch_eurostat_gov_debt_history

    cfg = get_settings()
    return await fetch_eurostat_gov_debt_history(base_url=cfg.eurostat_stats_url)


async def _fetch_fred_periodic_history() -> dict[str, list[tuple[date, float]]]:
    """FRED **低频**序列（政府债务类）全量历史。

    → ``{series_id: [(观测期初日, 值), ...]}``。
    ⚠ FRED 的季度/年度序列用**期初**日期标注观测 ⇒ 调用方要再用
    ``fred_period_end`` 归一到期末（那才是 point-in-time 的可得日）。
    """
    from app.config import get_settings
    from app.repositories.macro_sources import fetch_fred_series

    cfg = get_settings()
    out: dict[str, list[tuple[date, float]]] = {}
    for series_id in _DEEP_FRED_PERIODIC:
        out[series_id] = await fetch_fred_series(series_id, base_url=cfg.fred_csv_url)
    return out


async def _fetch_cb_gold_quarters() -> list[tuple[str, float]]:
    """WGC **全球合计行**的季度序列 → ``[(季度标签, 吨), ...]``。

    数据来自生产库 ``central_bank_purchases`` 表（本地，不用联网）。
    """
    from app.repositories.central_bank import CentralBankPurchaseRepository
    from app.repositories.db import async_session_factory

    async with async_session_factory() as session:
        repo = CentralBankPurchaseRepository(session)
        return await repo.aggregate_quarter_series()


async def backfill_macro_history_deep(
    repo: MacroFactorHistoryRepository,
    *,
    target: str = "default",
    days: int = DEEP_WINDOW_DAYS,
    end: date | None = None,
    dry_run: bool = False,
    cb_quarters: list[tuple[str, float]] | None = None,
    factors: Sequence[str] = DEEP_FACTORS,
) -> dict[str, int]:
    """**深回填**：把宏观因子的历史按 point-in-time 重放进历史表。

    与 :func:`backfill_macro_history`（日常补缺口）的区别：

    ==================  ==========================  ==========================
                      ``backfill_macro_history``    ``backfill_macro_history_deep``
    ==================  ==========================  ==========================
    因子                7 个日频                    **11 个**（含 4 个低频）
    行粒度              **交易日**                  **日历日**（与线上采集一致）
    窗口                252 自然日                   1825 自然日（5 年）
    门禁                样本够就跳过                 无条件全量重放
    用途                每天补缺口                   一次性铺历史（证据复测 + 归档）
    ==================  ==========================  ==========================

    ⚠ **行粒度为什么是日历日**：线上 ``daily_capture_loop`` 每天 07:00 触发、
    **无星期过滤** ⇒ 库里每个日历日都有一行（周末也有，值沿用上一交易日）。
    滚动分位窗口是 252 **日历**日 ⇒ 若历史只写交易日，窗口里的样本数
    会与线上不一致 ⇒ P10/P90 会算出不同的数 ⇒ 「复算」就不是生产口径了。

    ⚠ **point-in-time**：低频因子按**观测期末**判定可得
    （见 ``services/macro_history.py`` 的口径说明）⇒ 相对真实发布滞后
    （WGC 约 1~2 个月、FRED 债务约 1 个季度）**乐观了最多一个观测期**
    ⇒ 该偏差只会**高估**低频因子的前瞻力 ⇒ 若低频组实测不过三问，
    结论是保守且安全的。

    ⚠ **H.15 的 1 个工作日发布时滞**：本函数把 H.15 观测按其**观测日**当天
    即可得（与既有 ``backfill_macro_history`` 同一约定）⇒ 相对真实发布
    乐观 1 个工作日。对滚动分位与前瞻测量都无实质影响（已记录）。

    ``factors`` 可指定要写的因子子集（默认全部 11 个）——
    只写低频 4 个时（``DEEP_LOWFREQ_FACTORS``）仍然走同一套 point-in-time 口径，
    但**不必**再拉 H.15 / FRED 日频 / Yahoo（省 3 次网络请求）。

    ``dry_run=True`` 时**只统计不写库**，返回 ``{因子: 行数}``。
    """
    end_day = end or date.today()
    start = end_day - timedelta(days=days)
    wanted = tuple(f for f in factors if f in DEEP_FACTORS)
    need_daily = any(f in DEEP_DAILY_FACTORS for f in wanted)
    need_lowfreq = any(f in DEEP_LOWFREQ_FACTORS for f in wanted)

    # ── 1. 取原始序列（各源互相独立 ⇒ 某源挂掉不影响其它源）──
    h15_hist: object = []
    fred_hist: object = {}
    yahoo_hist: object = []
    if need_daily:
        h15_hist, fred_hist, yahoo_hist = await asyncio.gather(
            _fetch_h15_history(),
            _fetch_fred_history(),
            # ⚠ Yahoo 是唯一按窗口取数的源 ⇒ 必须留回看余量，
            # 否则窗口第一天拿不到「窗口之前的最后一次收盘」⇒ 该行整行缺失。
            _fetch_yahoo_dxy_deep(start - timedelta(days=YAHOO_LOOKBACK_DAYS), end_day),
            return_exceptions=True,
        )
    euro_hist: object = []
    fred_periodic: object = {}
    if need_lowfreq:
        euro_hist, fred_periodic = await asyncio.gather(
            _fetch_eurostat_deep(),
            _fetch_fred_periodic_history(),
            return_exceptions=True,
        )

    def _ok(obj: object, name: str) -> bool:
        if isinstance(obj, BaseException):
            logger.warning("%s 历史取数失败: %s", name, obj)
            return False
        return True

    h15_ok = _ok(h15_hist, "H.15")
    fred_ok = _ok(fred_hist, "FRED")
    yahoo_ok = _ok(yahoo_hist, "Yahoo DXY")
    euro_ok = _ok(euro_hist, "Eurostat")
    fred_periodic_ok = _ok(fred_periodic, "FRED 低频")

    quarters = cb_quarters
    if need_lowfreq and quarters is None:
        try:
            quarters = await _fetch_cb_gold_quarters()
        except Exception as exc:  # pragma: no cover - 本地库异常
            logger.warning("WGC 合计行读取失败: %s", exc)
            quarters = []

    # ── 2. 组装成「观测」序列（观测日 = 这个读数最早可得的日期）──
    #
    # ⚠ **映射逻辑只有一份**（``services/macro_history.py::build_observations``）——
    # 生产回填与证据脚本（``scripts/verify_macro_face.py``）共用它 ⇒ 口径不会漂。
    #
    # ⚠ **不要按窗口起点过滤观测**：窗口第一天（如 2021-11-10）需要知道
    # 「窗口之前最近的一次观测」才能还原线上真实值（线上每个日历日都写一行，
    # 值是「当时能拿到的最新读数」）⇒ 窗口前的观测必须**保留**，由 ``asof_rows``
    # 自己挑「可得日 ≤ 该天的最后一条」。
    # 只过滤**可得日晚于窗口终点**的观测（未来数据，point-in-time 禁止使用）。
    all_observations = build_observations(
        h15=h15_hist if h15_ok else [],
        fred=fred_hist if fred_ok else {},
        yahoo=yahoo_hist if yahoo_ok else [],
        eurostat=euro_hist if euro_ok else {},
        fred_periodic=fred_periodic if fred_periodic_ok else {},
        cb_quarters=quarters or [],
        end=end_day,
    )
    observations: dict[str, list[Observation]] = {k: all_observations.get(k, []) for k in wanted}

    # ── 3. 展开成「每天一行」并写库 ──
    rows: list[Row] = []
    for key in wanted:
        rows.extend(asof_rows(observations[key], factor_key=key, start=start, end=end_day))

    by_factor: dict[str, int] = {}
    for _, factor_key, *_ in rows:
        by_factor[factor_key] = by_factor.get(factor_key, 0) + 1

    if dry_run:
        logger.info("深回填 dry-run：%d 行（%s）", len(rows), by_factor)
        return by_factor

    if not rows:
        logger.warning("宏观因子深回填：窗口内没有可用历史数据")
        return {}

    written = await repo.upsert_many(target, rows)
    logger.info(
        "宏观因子深回填完成：%d 行（%s）",
        written,
        "，".join(f"{k}={v}" for k, v in sorted(by_factor.items())),
    )
    return by_factor
