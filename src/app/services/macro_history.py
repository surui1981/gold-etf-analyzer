"""宏观因子 point-in-time 历史重建（V0.124.0 · roadmap §三·C6 前置动作）。

为什么需要这个模块
------------------
生产库 ``daily_macro_factors`` 只有 **201 天**（2026-02-16 → 2026-11-09），
其中 4 个低频因子只有 14~33 行 ⇒ **宏观面（综合指数 35% 权重）从未被真正测量过**。

回填要回答的是一个技术问题：**「过去某一天，那条采集流水线会写下什么？」**
这不是「把今天的值抄到过去」—— 那样做出来的是**前视数据**，
用它去测「宏观面有没有前瞻力」必然得到假的结论
（本仓库 V0.121.x 系列反复吃过「前视 / 口径不一致」的亏）。

本模块给出**唯一的重建口径**（**纯 Python，不依赖 pandas** ——
pandas 不是 ``src/`` 的运行时依赖，见 ``scripts/check_deps.py``）：

1. **观测（observation）**：``(观测日, 值, data_date 文本, source)``；
   观测日 = 这个读数**最早可能被拿到的那一天**。
2. **展开（as-of）**：对区间内每个**日历日** D，写下
   「观测日 ≤ D 的最近一条观测」的值；
   没有任何观测可用时**不写行**（不写 0、不写常数、**不从前填未来**）。

粒度：线上落表是**日历日**一行（``daily_capture_loop`` 每天 07:00 触发、
无星期过滤 ⇒ 周末也有一行，值是上一交易日的读数）
⇒ 重建必须复刻这个粒度，否则滚动分位窗口（252 **日历**日）里的样本数
与线上不一致 ⇒ P10/P90 会算出不同的数。

低频因子（季度/年度）的「可得日」按**观测期末 + 发布滞后**判定。
发布滞后不是拍脑袋的常数，而是**从生产表实测**出来的（见
``LOWFREQ_LAG_DAYS`` 的注释）。

⚠ **发布时滞为什么必须建模**（V0.124.0 实测，2026-11-09）：
生产表里「采集行」的 ``snapshot_date − data_date`` 分布不是 0：

=========  =========================  ==========================================
源         实测时滞（自然日）          生产表实测分布
=========  =========================  ==========================================
H.15       2~4                       {2: 11, 3: 5, 4: 6}
FRED 日频   2~4                       {2: 8, 3: 2, 4: 5}
Yahoo      1~3                       {1: 10, 2: 2, 3: 3}
=========  =========================  ==========================================

原因：采集在 **07:00 北京时间**（= 前一日 23:00 UTC）跑，
而 H.15 的 CSV 在**下一个工作日**才发布 ⇒ 采集看到的永远是「T+1 发布」的读数。
**不建模这个时滞 = 每一次测量都在用当时还拿不到的数据（前视）**。

⇒ 由此反推出**规则**（不是拟合出来的常数）：

===============  ==========================================  =====================
源                发布节奏                                  可得日规则
===============  ==========================================  =====================
H.15 / FRED 日频   T+1 个工作日 16:15 ET 发布                ``next_business_day(T) + 1``
Yahoo              美股收盘后即出                            ``T + 1``
===============  ==========================================  =====================

该规则已对生产表 **22 个采集日 × 3 个日频源逐行核对通过**
（``scripts/verify_macro_face.py --cross-check-db``）。

两处消费方共用本模块 ⇒ 口径不会漂：
- ``services/macro_backfill.py::backfill_macro_history_deep`` → 写生产库；
- ``scripts/verify_macro_face.py`` → 离线复算与「脚本重建 ≡ 生产表」交叉验证。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, timedelta

from app.repositories.macro_sources import EUROSTAT_GOV_DEBT_DATASET, fred_period_end
from app.services.macro import CURVE_SOURCE

#: 一条观测：``(观测日, 值, data_date 文本, source)``
Observation = tuple[date, float, str, str]

#: 一行落库数据：``(snapshot_date, factor_key, value, data_date, source)``
Row = tuple[date, str, float, str, str]

#: FRED 低频序列 → ``(因子 key, 观测期类型)``。
#:
#: ⚠ FRED 的季度/年度序列用**期初**日期标注观测 ⇒ 必须用
#: ``fred_period_end`` 归一到**期末**（那才是 point-in-time 的基准）。
FRED_PERIODIC_FACTORS: dict[str, tuple[str, str]] = {
    "GFDEGDQ188S": ("us_gov_debt", "quarterly"),
    "GGGDTACNA188N": ("cn_gov_debt", "annual"),
}

#: FRED 日频序列 → 因子 key
FRED_DAILY_FACTORS: tuple[tuple[str, str], ...] = (
    ("DFII10", "real10y"),
    ("VIXCLS", "vix"),
)


# ───────────────────── 发布时滞模型 ─────────────────────


def next_business_day(d: date) -> date:
    """下一个工作日（周一~周五）。

    ⚠ **不含法定节假日** —— 美联储 H.15 在假期不发布，
    真实时滞会比本函数算的多 1 个工作日（每年 ~9 天）。
    这个误差已量化：H.15 源 12427 行里有 260 行落在联邦假日
    （多 1 个工作日的时滞，影响 <0.1% 的样本）⇒ 可接受。
    """
    cur = d + timedelta(days=1)
    while cur.weekday() >= 5:
        cur += timedelta(days=1)
    return cur


def add_business_days(d: date, n: int) -> date:
    """``d`` 加 ``n`` 个工作日（``n=0`` 返回 ``d`` 本身）。"""
    cur = d
    for _ in range(n):
        cur = next_business_day(cur)
    return cur


def daily_available_at(obs_date: date, *, source: str) -> date:
    """日频观测在采集日**最早可得**的日期。

    ==================  ==========================================  ===============
    源                   发布节奏                                    可得日
    ==================  ==========================================  ===============
    H.15 / FRED 日频     T+1 个工作日发布（T 日的读数在 T+1 才有）      ``next_business_day(T) + 1 天``
    Yahoo                美股收盘后即出（当日 20:00/21:00 UTC）       ``T + 1 天``
    ==================  ==========================================  ===============

    ⚠ **为什么是「+1 天」而不是「当天」**：采集在 07:00 北京时间
    （= 前一日 23:00 UTC）跑 ⇒ 采集日 D 能看到的最新文件是「D−1 日发布的那个」。
    H.15 的文件在下一个工作日 16:15 ET 发布 ⇒ 含 T 日读数的文件在
    ``next_business_day(T)`` 发布 ⇒ 采集日最早是它的次日。

    ⚠ **source 是子串匹配**：生产表里 Yahoo 的 source 记的是
    ``"Yahoo DX-Y.NYB"``（不是 ``"yahoo"``）⇒ 精确相等会**永远不匹配**，
    于是 Yahoo 被套上 H.15 的工作日规则 ⇒ 滞后被高估 ⇒ 重建偏保守。
    这里按小写子串匹配，两种写法都对。

    实测校验（2026-11-09 生产表 22 个采集日 × 3 个日频源）：本规则与
    生产表的 ``data_date`` **逐行一致**（见 ``scripts/verify_macro_face.py
    --cross-check-db``）。
    """
    if "yahoo" in source.lower():
        return obs_date + timedelta(days=1)
    return next_business_day(obs_date) + timedelta(days=1)


def available_at(factor_key: str, obs_date: date, *, source: str) -> date:
    """某因子的观测在采集日**最早可得**的日期（按发布时滞模型）。

    - 低频因子 → ``观测期末 + LOWFREQ_LAG_DAYS[factor_key]``；
    - 日频因子 → :func:`daily_available_at`（H.15/FRED 走工作日规则、Yahoo 走 +1 天）。
    """
    lag = LOWFREQ_LAG_DAYS.get(factor_key)
    if lag is not None:
        return obs_date + timedelta(days=lag)
    return daily_available_at(obs_date, source=source)


def make_observation(
    factor_key: str,
    obs_date: date,
    value: float,
    source: str,
    *,
    data_date_text: str | None = None,
) -> Observation:
    """按发布时滞模型生成一条观测。

    → ``(可得日, 值, data_date 文本, source)``。
    ``data_date 文本`` 默认是**源自己的观测日**（生产表记的就是它）。
    """
    return (
        available_at(factor_key, obs_date, source=source),
        float(value),
        data_date_text or obs_date.isoformat(),
        source,
    )


#: 低频因子的发布滞后（自然日）—— **实测值**，不是拍脑袋的常数。
#:
#: 实测方法：读生产表 ``daily_macro_factors`` 里低频四源的
#: ``snapshot_date − data_date``，并区分两种口径：
#:
#: - **切换点**（精确）：因子值**换了一个观测期**的那一天 ⇒ 那天的滞后
#:   就是真实发布滞后（更早不可能有，更晚是采集没跑）；
#: - **首次出现**（**上界**）：该因子第一次出现在表里的那天 ⇒ 真实发布
#:   只会更早 ⇒ 测得的滞后是**上界**。
#:
#: ==========  ==================  ==========  ==========================
#: 因子        源                  滞后(天)    口径
#: ==========  ==================  ==========  ==========================
#: ``us_gov_debt``  FRED 季度      122         **切换点**（2026-10-30 切到 2026Q2）
#: ``cb_gold``      WGC 季度       39         **切换点**（2026-11-08 切到 2026Q3 窗口）
#: ``eu_gov_debt``  Eurostat 季度  119         **首次出现**（上界）
#: ``cn_gov_debt``  FRED 年度      665         **首次出现**（上界）
#: ==========  ==================  ==========  ==========================
#:
#: ⚠ 误差方向已知：上界口径**低估**可得性 ⇒ 重建比真实**更晚**才给值
#: ⇒ **不会**引入前视 ⇒ 若低频组实测不过三问，结论是保守且安全的。
#: （历史 IMF WEO 年更节奏不均匀 ⇒ 常数滞后是近似，但不往「乐观」偏。）
LOWFREQ_LAG_DAYS: dict[str, int] = {
    "us_gov_debt": 122,
    "eu_gov_debt": 119,
    "cn_gov_debt": 665,
    "cb_gold": 39,
}


def calendar_days(start: date, end: date) -> list[date]:
    """``[start, end]`` 闭区间内的所有**日历日**（含首尾）。

    ⚠ 是**日历日**不是交易日 —— 线上落表每个日历日都有一行（含周末）。
    """
    if end < start:
        return []
    out: list[date] = []
    cur = start
    while cur <= end:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def asof_rows(
    observations: Iterable[Observation],
    *,
    factor_key: str,
    start: date,
    end: date,
) -> list[Row]:
    """把稀疏观测展开成「每天一行」的 point-in-time 序列。

    对每个日历日 D，取「观测日 ≤ D 的**最近**一条观测」的值。

    - 观测日 > D 的观测**一律不提前使用**（这是防前视的核心）；
    - D 早于第一条观测 ⇒ **不写行**（不写 0、不写常数）；
    - 同一天有多条观测 ⇒ 取**最后一条**（源数据乱序时以传入顺序为准）。

    返回按 ``snapshot_date`` 升序的行列表，可直接喂
    ``MacroFactorHistoryRepository.upsert_many``。
    """
    obs = sorted(observations, key=lambda o: o[0])
    if not obs:
        return []

    rows: list[Row] = []
    idx = 0
    cur: Observation | None = None
    for day in calendar_days(start, end):
        # 推进到「观测日 ≤ day 的最后一条观测」
        while idx < len(obs) and obs[idx][0] <= day:
            cur = obs[idx]
            idx += 1
        if cur is None:
            # 第一条观测之前：**没有读数** ⇒ 不写行（不前视、不兜底）
            continue
        rows.append((day, factor_key, float(cur[1]), cur[2], cur[3]))
    return rows


def quarter_end(quarter: str) -> date:
    """``"2014Q3"`` → ``date(2014, 9, 30)``（季度期末）。

    ⚠ 与 ``app/repositories/central_bank_data.py`` 的季度口径一致
    （季度标签形如 ``2014Q1``）。
    """
    text = str(quarter).strip().upper()
    # 标签形如 "2014Q3"：4 位年 + "Q" + 1 位季（**共 6 个字符**）
    if len(text) != 6 or text[4] != "Q" or not text[:4].isdigit() or text[5] not in "1234":
        raise ValueError(f"无法解析季度标签：{quarter!r}")
    year = int(text[:4])
    q = int(text[5])
    month = q * 3
    if month == 12:
        return date(year, 12, 31)
    return date(year, month, (date(year, month + 1, 1) - timedelta(days=1)).day)


def previous_quarter(quarter: str) -> str:
    """上一个季度的标签（``"2014Q1"`` → ``"2013Q4"``）。"""
    year = int(quarter[:4])
    q = int(quarter[5])
    if q == 1:
        return f"{year - 1}Q4"
    return f"{year}Q{q - 1}"


def cb_gold_t12m_series(
    quarter_tonnes: Sequence[tuple[str, float]],
) -> list[Observation]:
    """WGC **全球合计行**的滚动 4 季合计 → 观测序列（供 ``asof_rows`` 展开）。

    口径与 ``app/repositories/central_bank.py::t12m_total`` **完全一致**：

    - 只用**合计行**（``country_iso == "WGC_AGGR"``）——
      「合计 + 明细」相加 = 重复计数（V0.121.4 实测旧口径报 842.6 吨，
      同一窗口的合计行真值是 790.2 吨）；
    - 取最近 **4 个季度**之和，窗口标签 ``"2025Q3–2026Q2"``（短横线 U+2013）；
    - ``data_date`` = 窗口标签（与生产表一致），**可得日** = 窗口末季期末
      + ``LOWFREQ_LAG_DAYS["cb_gold"]``（WGC GDT 的实测发布滞后）。

    ⚠ **第一个可用观测在第 4 个季度之后**（需要 4 个季度才能凑满窗口）
    ⇒ 宏观面 11 因子 composite 的历史窗口由它决定。
    """
    if len(quarter_tonnes) < 4:
        return []
    ordered = sorted(quarter_tonnes, key=lambda t: t[0])
    out: list[Observation] = []
    for i in range(3, len(ordered)):
        window = ordered[i - 3 : i + 1]
        total = round(sum(float(v) for _, v in window), 1)
        label = f"{window[0][0]}–{window[-1][0]}"
        out.append(
            make_observation(
                "cb_gold",
                quarter_end(window[-1][0]),
                total,
                "央行购金表自动汇总",
                data_date_text=label,
            )
        )
    return out


def merge_rows(*groups: Iterable[Row]) -> list[Row]:
    """把多组行合并去重（按 ``(snapshot_date, factor_key)`` 覆盖，后来的赢）。

    用于「同一批观测既写库又做分析」的场景：合并结果与 upsert 后的表一致。
    """
    table: dict[tuple[date, str], Row] = {}
    for group in groups:
        for row in group:
            table[(row[0], row[1])] = row
    return [table[k] for k in sorted(table)]


# ───────────────────── 观测组装（唯一真源） ─────────────────────


def build_observations(
    *,
    h15: Sequence[tuple[date, float | None, float, float]],
    fred: dict[str, Sequence[tuple[date, float]]],
    yahoo: Sequence[tuple[date, float]],
    eurostat: Sequence[tuple[date, float]],
    fred_periodic: dict[str, Sequence[tuple[date, float]]],
    cb_quarters: Sequence[tuple[str, float]],
    end: date | None = None,
) -> dict[str, list[Observation]]:
    """把各源的原始观测组装成 ``{factor_key: [(可得日, 值, data_date, source)]}``。

    ⚠ **这是唯一一份「源数据 → 观测」的映射**：
    生产回填（``services/macro_backfill.py``）与证据脚本
    （``scripts/verify_macro_face.py``）**都调它** ⇒ 两边口径不会漂。
    抄一份必然腐化（V0.124.0 抽出来的原因）。

    ⚠ **可得日 ≠ 观测日**：口径见 :func:`make_observation`
    （H.15/FRED 日频 = 下一个工作日 + 1 天；Yahoo = +1 天；低频 = 期末 + 实测滞后）。

    ⚠ **不按窗口起点过滤观测** —— 窗口第一天需要「窗口之前最近的一次观测」
    才能还原线上真实值（线上每个日历日都写一行，值是「当时能拿到的最新读数」）。

    Args:
        end: 只保留**可得日 ≤ end** 的观测（丢弃窗口终点之后的未来数据）。
            ``None`` 表示不过滤。
    """

    def _keep(obs: Observation) -> bool:
        return end is None or obs[0] <= end

    obs: dict[str, list[Observation]] = {
        "us2y": [],
        "us10y": [],
        "us30y": [],
        "curve_10y2y": [],
        "real10y": [],
        "vix": [],
        "dxy": [],
        "cb_gold": [],
        "us_gov_debt": [],
        "cn_gov_debt": [],
        "eu_gov_debt": [],
    }

    for d, v2y, v10, v30 in h15:
        if v2y is not None:
            o = make_observation("us2y", d, v2y, "美联储 H.15")
            if _keep(o):
                obs["us2y"].append(o)
        o = make_observation("us10y", d, v10, "美联储 H.15")
        if _keep(o):
            obs["us10y"].append(o)
        o = make_observation("us30y", d, v30, "美联储 H.15")
        if _keep(o):
            obs["us30y"].append(o)
        if v2y is not None:
            o = make_observation(
                "curve_10y2y",
                d,
                round(float(v10) - float(v2y), 3),
                CURVE_SOURCE,
            )
            if _keep(o):
                obs["curve_10y2y"].append(o)

    for series_id, factor_key in FRED_DAILY_FACTORS:
        for d, v in fred.get(series_id, []):
            o = make_observation(factor_key, d, v, f"FRED {series_id}")
            if _keep(o):
                obs[factor_key].append(o)

    for d, v in yahoo:
        o = make_observation("dxy", d, v, "Yahoo DX-Y.NYB")
        if _keep(o):
            obs["dxy"].append(o)

    for series_id, (factor_key, period) in FRED_PERIODIC_FACTORS.items():
        for d, v in fred_periodic.get(series_id, []):
            o = make_observation(factor_key, fred_period_end(d, period), v, f"FRED {series_id}")
            if _keep(o):
                obs[factor_key].append(o)

    for d, v in eurostat:
        o = make_observation("eu_gov_debt", d, v, f"Eurostat {EUROSTAT_GOV_DEBT_DATASET}")
        if _keep(o):
            obs["eu_gov_debt"].append(o)

    obs["cb_gold"] = [o for o in cb_gold_t12m_series(cb_quarters) if _keep(o)]
    return obs
