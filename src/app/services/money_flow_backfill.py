"""资金流因子历史回填（V0.120.0）。

为什么需要
----------
资金流面的滚动分位窗口按**观测节奏**取（周频 728 日 / 月频 1826 日），
样本门槛 60 / 40 / 36 个观测。冷启动时 ``daily_money_flow_factors`` 一条数据都没有
⇒ 6 个因子全部退回静态阈带（``services/money_flow.py::MONEY_FLOW_FACTOR_RULES``
里实测标定的 best/worst）。静态带能用，但要让它**跟随市场**得有历史。

而这 6 个因子的历史**都在源里自带**（CFTC 年度包 / FRED 全量 CSV /
akshare 全历史 / 上交所按日可查）—— 只是从没被采集过。

观测结构必须与**实时采集**逐条一致
----------------------------------
回填写进去的 ``(观测日, 值)`` 序列，必须和线上每天采到的那一条同口径，
否则滚动分位算出来的分布会与静态带分家：

======================  ==========================================  ==================
因子                     口径                                      节奏
======================  ==========================================  ==================
``cot_gold_net``        CFTC 每周观测的净多占 OI %                 周
``cot_gold_flow``       净多的 4 周变化（窗口**重叠**）              周
``gold_etf_flow``       4 周累计净申赎（亿元）                     周
``us_liq_net``          美元净流动性的 4 周变化（**月末 vs 月末**）    月
``cn_margin_flow``      融资余额月环比（**已过完**的月末观测日）      月
``cn_money_gap``        M1−M2 剪刀差（月末观测日）                  月
======================  ==========================================  ==================

⚠ 采样网格必须与**实时采集**逐条一致，否则两张网格会在历史表里并存：
- 周频（``gold_etf_flow``）锚在 **ISO 周的最后一个交易日**上
  （``week_end_days``）—— 若实时采集用「最新交易日」，每日调度一天写一行，
  相邻几天的 4 周累计窗口几乎是同一个数 ⇒ 同一周被重复计入滚动分位窗口。
- 月频（``cn_margin_flow`` / ``cn_money_gap``）只取**已过完**的月份 ——
  若取「当月至今」，观测日每天推进 ⇒ 一个月会攒 20 来行几乎相同的值，
  且「月内变动」与历史行的「月末 vs 月末」不是同一个量。
- 月频（``us_liq_net``）锚在**日历月末**（``month_end_days``），
  观测值按「该月末当天或之前最近的一条」取值（as-of）——
  ⚠️ **不是**周频：它的值是「4 周变化」，按周采样时相邻两次观测**重叠 3/4**
  ⇒ 有效样本只剩名义值的 1/4（名义 60 个月的位置里塞了 260 行高度重叠的样本
  ⇒ ``min_samples`` 达标是**假象**）。见 ``money_flow_sources.fetch_us_net_liquidity_monthly``。

⚠ 4 周变化的窗口是**重叠**的（每周都算一次「与 4 周前比」）。
标定脚本 ``scripts/calibrate_money_flow_bands.py`` 用的也是重叠窗口，
所以静态带与滚动带口径一致 —— 这里若改成不重叠窗口，两条带就分家了。

⚠ ``us_liq_net`` 的实时采集 / 回填 / 标定**三处共用**同一个
``month_end_days()`` + ``asof_series()``（月末 vs 月末），
不再是「找最接近 28 天前的观测、容差 10 天」那种滑动窗口 ——
滑动窗口按周采样 ⇒ 同一段历史被反复计入。
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

from app.repositories.money_flow_factor_history import MoneyFlowFactorHistoryRepository
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: 各因子的回填窗口（自然日）—— 与 ``MONEY_FLOW_FACTOR_RULES`` 的 ``window_days`` 一致。
#: 窗口取够滚动分位能用的样本即可，多回填是浪费（CFTC 年度包 18MB/个）。
BACKFILL_WINDOW_DAYS: dict[str, int] = {
    "cot_gold_net": 728,
    "cot_gold_flow": 728,
    "gold_etf_flow": 728,
    "us_liq_net": 1826,
    "cn_margin_flow": 1826,
    "cn_money_gap": 1826,
}

#: 回填行元组：``(观测日, factor_key, value, data_date, source)``
Row = tuple[date, str, float, str, str]


def _months_between(start: date, end: date) -> int:
    """``start`` / ``end`` 跨了几个自然年（CFTC 年度包按年下载）。"""
    return end.year - start.year + 1


# ───────────────────── 各因子的历史采集 ─────────────────────


async def _collect_cftc_rows(start: date, end: date) -> list[Row]:
    """CFTC 黄金投机净多：水平（占 OI %）+ 4 周变化。"""
    from app.repositories.money_flow_sources import CFTC_SOURCE, fetch_cftc_gold_history

    # 多取 1 年：窗口起点处的「4 周变化」需要起点之前的观测做基准
    points = await fetch_cftc_gold_history(years=_months_between(start, end) + 1)
    if not points:
        return []
    rows: list[Row] = []
    for p in points:
        if not (start <= p.obs_date <= end):
            continue
        rows.append(
            (
                p.obs_date,
                "cot_gold_net",
                round(p.net_pct_oi, 4),
                p.obs_date.isoformat(),
                CFTC_SOURCE,
            )
        )
    for i in range(4, len(points)):
        d = points[i].obs_date
        if not (start <= d <= end):
            continue
        delta = float(points[i].net_long - points[i - 4].net_long)
        rows.append((d, "cot_gold_flow", delta, d.isoformat(), CFTC_SOURCE))
    return rows


async def _collect_us_liq_rows(start: date, end: date) -> list[Row]:
    """美元净流动性 4 周变化（$M）—— **月频观测**，与实时采集同款。

    ⚠️ 采样网格必须与**实时采集**一致（月末锚点），
    否则两张网格会在历史表里并存 ⇒ 同一个月被计入两次。
    """
    from app.repositories.money_flow_sources import (
        US_LIQ_SOURCE,
        fetch_us_net_liquidity_monthly,
    )

    rows: list[Row] = []
    for obs_date, delta, prev_end in await fetch_us_net_liquidity_monthly(today=end):
        if not (start <= obs_date <= end):
            continue
        rows.append(
            (
                obs_date,
                "us_liq_net",
                round(delta, 1),
                f"{prev_end.isoformat()}~{obs_date.isoformat()}",
                US_LIQ_SOURCE,
            )
        )
    return rows


async def _collect_etf_rows(start: date, end: date) -> list[Row]:
    """黄金 ETF 4 周累计净申赎（亿元）—— 上交所官方份额。

    ⚠️ 采样网格必须与**实时采集**一致（ISO 周的最后一个交易日），
    否则两张网格会在历史表里并存 ⇒ 同一周被计入两次。
    """
    from app.repositories.money_flow_sources import (
        GOLD_ETF_SYMBOL,
        SSE_SOURCE,
        fetch_sina_etf_closes,
        fetch_sse_etf_shares,
        week_end_days,
    )

    closes = await fetch_sina_etf_closes("sh518880")
    if not closes:
        logger.warning("新浪 ETF 收盘价不可用，gold_etf_flow 跳过回填")
        return []
    trading_days = sorted(closes)
    # 周末日网格（往前多留 35 天取「4 周前」的搭档点）
    week_ends = week_end_days(trading_days, today=end)
    sample_dates = [d for d in week_ends if start - timedelta(days=35) <= d <= end]
    if not sample_dates:
        return []

    # 并发采样（并发度 8）：逐个串行要几分钟，调度器里等不起。
    # ⚠ 上交所接口对突发并发敏感，所以限流而不是全开。
    shares: dict[date, float] = {}
    sem = asyncio.Semaphore(8)

    async def _one(sd: date) -> None:
        async with sem:
            v = await fetch_sse_etf_shares(GOLD_ETF_SYMBOL, sd)
        if v is not None:
            shares[sd] = v

    await asyncio.gather(*(_one(sd) for sd in sample_dates))
    logger.info("上交所份额采样 %d/%d 个日期有数据", len(shares), len(sample_dates))
    if not shares:
        return []

    rows: list[Row] = []
    for sd, sh in sorted(shares.items()):
        if not (start <= sd <= end):
            continue
        target = sd - timedelta(days=28)
        cand = [k for k in shares if abs((k - target).days) <= 7]
        if not cand:
            continue
        prev_day = min(cand, key=lambda k: abs((k - target).days))
        near = [k for k in closes if abs((k - sd).days) <= 5]
        if not near:
            continue
        close = closes[min(near, key=lambda k: abs((k - sd).days))]
        delta_yi = (sh - shares[prev_day]) * close / 1e4
        rows.append(
            (
                sd,
                "gold_etf_flow",
                round(delta_yi, 4),
                f"{prev_day.isoformat()}~{sd.isoformat()}",
                SSE_SOURCE,
            )
        )
    return rows


async def _collect_cn_margin_rows(start: date, end: date) -> list[Row]:
    """A 股融资余额月环比（%）—— **已过完**的月末观测。

    ⚠️ 跳过还没过完的当月：它的「月末值」其实是月内至今值，
    与历史行的「月末 vs 月末」不是同一个量，且会一天一变。
    """
    from app.repositories.money_flow_sources import MARGIN_SOURCE, fetch_cn_margin_balances

    raw = await fetch_cn_margin_balances()
    if len(raw) < 2:
        return []
    by_month: dict[tuple[int, int], tuple[date, float]] = {}
    for d, v in raw:
        key = (d.year, d.month)
        cur = by_month.get(key)
        if cur is None or d > cur[0]:
            by_month[key] = (d, v)
    months = sorted(by_month)
    today = date.today()
    if months and months[-1] == (today.year, today.month):
        months = months[:-1]
    rows: list[Row] = []
    for i in range(1, len(months)):
        d, v = by_month[months[i]]
        if not (start <= d <= end):
            continue
        _, pv = by_month[months[i - 1]]
        if pv <= 0:
            continue
        rows.append(
            (d, "cn_margin_flow", round((v / pv - 1.0) * 100.0, 4), d.isoformat(), MARGIN_SOURCE)
        )
    return rows


async def _collect_cn_money_rows(start: date, end: date) -> list[Row]:
    """中国 M1−M2 剪刀差（百分点）—— 月末观测。"""
    from app.repositories.money_flow_sources import MONEY_SUPPLY_SOURCE, fetch_cn_money_supply

    raw = await fetch_cn_money_supply()
    rows: list[Row] = []
    for d, m1, m2 in raw:
        if not (start <= d <= end):
            continue
        rows.append((d, "cn_money_gap", round(m1 - m2, 4), d.isoformat(), MONEY_SUPPLY_SOURCE))
    return rows


#: 因子 → 采集器
_COLLECTORS = {
    "cot_gold_net": _collect_cftc_rows,
    "cot_gold_flow": _collect_cftc_rows,
    "gold_etf_flow": _collect_etf_rows,
    "us_liq_net": _collect_us_liq_rows,
    "cn_margin_flow": _collect_cn_margin_rows,
    "cn_money_gap": _collect_cn_money_rows,
}


def _min_samples_of(factor_key: str) -> int:
    """该因子的滚动分位样本门槛（取自规则表，避免两处各写一份常数）。"""
    from app.services.money_flow import MONEY_FLOW_FACTOR_RULES

    for rule in MONEY_FLOW_FACTOR_RULES:
        if rule["key"] == factor_key:
            return int(rule["min_samples"])
    return 30


#: 同一源的两个因子（CFTC）只采一次
_SOURCE_GROUPS = {
    "cot_gold_net": "cftc",
    "cot_gold_flow": "cftc",
    "gold_etf_flow": "etf",
    "us_liq_net": "us_liq",
    "cn_margin_flow": "cn_margin",
    "cn_money_gap": "cn_money",
}


# ───────────────────── 回填入口 ─────────────────────


async def backfill_money_flow_history(
    repo: MoneyFlowFactorHistoryRepository,
    *,
    target: str = "default",
    days: int | None = None,
    force: bool = False,
    today: date | None = None,
    factors: list[str] | None = None,
) -> dict[str, int]:
    """把各源自带的**历史**回填进 ``daily_money_flow_factors``。

    返回 ``{factor_key: 写入行数}``。

    参数
    ----
    - ``days``：覆盖所有因子的回填窗口（自然日）；默认按因子各自的
      ``BACKFILL_WINDOW_DAYS``（周频 728 / 月频 1826）。
    - ``force``：忽略「样本已充足」的检查，强制重写。
    - ``factors``：只回填指定因子（默认全部 6 个）。

    幂等：按 ``(target, snapshot_date, factor_key)`` 覆盖写。
    """
    end = today or date.today()
    wanted = list(factors) if factors else list(_COLLECTORS)

    # ── 1. 决定要回填哪些因子（样本已充足则跳过） ──
    # ⚠ 门槛必须取**规则表的 min_samples**（36~60），不能用拍脑袋的常数：
    # 用 30 的话会出现「回填跑完了、滚动分位仍不激活」的夹层 ——
    # 样本 30~59 满足回填门槛但达不到阈带的 min_samples，
    # 于是回填认为「够了」不再跑、阈值又认为「不够」永远不切动态。
    need: set[str] = set()
    for key in wanted:
        if key not in _COLLECTORS:
            logger.warning("未知资金流因子 %s，跳过", key)
            continue
        window = days or BACKFILL_WINDOW_DAYS.get(key, 728)
        if force:
            need.add(key)
            continue
        threshold = _min_samples_of(key)
        count = await repo.count_samples(target, key, window, end_date=end)
        if count < threshold:
            logger.info("资金流因子 %s 窗口内仅 %d 样本（需 %d），需要回填", key, count, threshold)
            need.add(key)
        else:
            logger.info("资金流因子 %s 已有 %d 样本（需 %d），跳过回填", key, count, threshold)
    if not need:
        logger.info("资金流因子历史充足，跳过回填")
        return {}

    # ── 2. 按源分组采集（CFTC 的两个因子共用一次下载） ──
    # 各源并发取：CFTC 是 18MB/年的 zip、FRED 是全量 CSV、上交所要打 72 次
    # 串行会拖到分钟级 —— 与宏观面回填同款（``macro_backfill`` 用 gather）。
    groups = {_SOURCE_GROUPS[k]: k for k in need}

    async def _collect_group(group: str, representative: str) -> list[Row]:
        window = days or BACKFILL_WINDOW_DAYS.get(representative, 728)
        start = end - timedelta(days=window)
        try:
            return await _COLLECTORS[representative](start, end)
        except Exception as exc:
            logger.warning("资金流历史采集 %s 失败: %s", group, exc)
            return []

    results = await asyncio.gather(
        *(_collect_group(group, rep) for group, rep in groups.items()),
        return_exceptions=True,
    )
    collected: dict[str, list[Row]] = {}
    for (group, _rep), res in zip(groups.items(), results, strict=True):
        if isinstance(res, BaseException):
            logger.warning("资金流历史采集 %s 失败: %s", group, res)
            continue
        collected[group] = res
        logger.info("资金流历史采集 %s：%d 行", group, len(res))

    # ── 3. 落表 ──
    written: dict[str, int] = {}
    for key in need:
        group = _SOURCE_GROUPS[key]
        rows = [r for r in collected.get(group, []) if r[1] == key]
        if not rows:
            continue
        n = await repo.upsert_batch(target, rows)
        written[key] = n
        logger.info("资金流因子 %s 回填 %d 行", key, n)
    return written
