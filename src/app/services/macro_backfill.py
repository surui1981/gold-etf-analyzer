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
from datetime import date, timedelta

from app.repositories.macro_factor_history import MacroFactorHistoryRepository
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
