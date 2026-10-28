"""资金流面服务：按「钱往哪儿流」判断黄金（V0.120.0 新增的第 4 个评分面）。

设计边界（这一条决定了本面与宏观面的分工）
------------------------------------------
本面**只收流量 / 数量类读数**，**不收价格类读数**：
不收 SHIBOR、不收汇率、不收任何利率、不收金价本身。
价格与存量口径归宏观面 —— 否则同一条逻辑会被计两遍
（V0.119.0 的政府债务组就是这个教训：债务↑同时走了「货币化利多」和
「实际利率利空」两条通道，只算一条、且明确说明算的是哪条）。

因子集（6 个：周 3 / 月 3）
-------------------------
==================  ==========  ======  ======  ==========================
因子                 节奏         权重     符号    源
==================  ==========  ======  ======  ==========================
``cot_gold_net``    周           18%     +      CFTC 分类持仓（管理基金净多占 OI）
``cot_gold_flow``   周           14%     +      同上（4 周净多变化）
``gold_etf_flow``   周           22%     +      上交所官方 ETF 份额（4 周累计净申赎）
``us_liq_net``      月           14%     +      FRED（美元净流动性 4 周变化）
``cn_margin_flow``  月           16%     −      沪深融资余额（月环比）
``cn_money_gap``    月           16%     −      央行 M1−M2 剪刀差
==================  ==========  ======  ======  ==========================

符号口径
--------
- ``+``（值越高越利多黄金）：钱**流进**黄金 / 钱**变多**。
- ``−``（**机会成本**口径）：``cn_margin_flow`` 下降 = 股市杠杆钱撤出 =
  黄金的机会成本下降 = **利多黄金**；``cn_money_gap`` 走阔（剪刀差扩大）=
  钱淤积在存款 = 抗通胀资产需求上升 = **利多黄金**。

降级链（复用宏观面的三件套，不重写）
-------------------------------------
用户手动覆盖（本轮未实现）> 自动源 > **上次成功落库的真实读数** > ``STATIC_REF``。
``is_persistable_source`` 把「静态常量」和「末次落库」挡在历史表之外 ——
旧读数不能被记成今天的观测，否则滚动分位窗口会被压平。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import date, timedelta

from app.schemas.common import DirectionSignal
from app.schemas.market import MoneyFlowFactorOut, MoneyFlowIndexOut
from app.schemas.thresholds import DirectionThreshold
from app.services.macro import (
    LAST_KNOWN_GOOD_PREFIX,
    is_persistable_source,
    source_tier,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: 资金流因子规则：面内权重合计 1.0；best=最利好黄金的一端，worst=最利空的一端。
#:
#: ``best`` / ``worst`` 的来源是**实测历史分位**（``scripts/calibrate_money_flow_bands.py``），
#: 不是拍脑袋：
#:
#: ==================  =====================  =========  ==========================
#: 因子                 样本                   分位口径   P10 / P90
#: ==================  =====================  =========  ==========================
#: ``cot_gold_net``    407 周（2019-01 起）    8 年      6.49% / 34.10%
#: ``cot_gold_flow``   403 个 4 周窗口          8 年      -43,005 / +41,616 张
#: ``gold_etf_flow``   94 个 4 周窗口           3 年      -20.84 / +74.25 亿元
#: ``us_liq_net``      663 个 4 周窗口          13 年     -151,369 / +179,325 $M
#: ``cn_margin_flow``  60 个月                 5 年      -4.30% / +6.03%
#: ``cn_money_gap``    60 个月                 5 年      -11.2 / -3.1 pp
#: ==================  =====================  =========  ==========================
#:
#: 月频两个因子刻意用 **60 个月**窗口（与滚动分位窗口一致）—— 静态兜底带必须
#: 和滚动带同口径，否则「冷启动用静态、之后切滚动」时分数会跳变。
#: 代价是 ``cn_money_gap`` 的近 5 年区间**全为负**（-11.2 ~ -1.2），
#: 这本身是事实：2024-09 以来 M1 同比从 -7.4% 回升到 +3.2%，剪刀差单调收窄。
#:
#: ``window_days`` / ``min_samples`` 是**滚动分位**的窗口与样本门槛：
#: 周频 104 周（728 天）、月频 60 月（1826 天）。
MONEY_FLOW_FACTOR_RULES: list[dict] = [
    {
        "key": "cot_gold_net",
        "name": "黄金投机净多占 OI",
        "unit": "%",
        "weight": 0.18,
        "positive": True,
        "best": 34.1023,
        "worst": 6.4927,
        "cadence": "weekly",
        "max_lag_days": 14,
        "window_days": 728,
        "min_samples": 60,
    },
    {
        "key": "cot_gold_flow",
        "name": "黄金投机净多 4 周变化",
        "unit": "张",
        "weight": 0.14,
        "positive": True,
        "best": 41616.0,
        "worst": -43005.4,
        "cadence": "weekly",
        "max_lag_days": 14,
        "window_days": 728,
        "min_samples": 60,
    },
    {
        "key": "gold_etf_flow",
        "name": "黄金ETF 4 周累计净申赎",
        "unit": "亿元",
        "weight": 0.22,
        "positive": True,
        "best": 74.2516,
        "worst": -20.8368,
        "cadence": "weekly",
        "max_lag_days": 14,
        "window_days": 728,
        "min_samples": 40,
    },
    {
        "key": "us_liq_net",
        "name": "美元净流动性 4 周变化",
        "unit": "$M",
        "weight": 0.14,
        "positive": True,
        # 静态兜底带 = **近 60 个月**（与滚动窗口同长）的 P10/P90
        # （实测标定，见 scripts/calibrate_money_flow_bands.py）
        "best": 130327.72,
        "worst": -252038.76,
        "cadence": "monthly",
        "max_lag_days": 60,
        "window_days": 1826,
        "min_samples": 36,
    },
    {
        "key": "cn_margin_flow",
        "name": "A股融资余额月变动",
        "unit": "%",
        "weight": 0.16,
        "positive": False,
        "best": -4.2966,
        "worst": 6.0334,
        "cadence": "monthly",
        "max_lag_days": 60,
        "window_days": 1826,
        "min_samples": 36,
    },
    {
        "key": "cn_money_gap",
        "name": "中国 M1-M2 剪刀差",
        "unit": "pp",
        "weight": 0.16,
        "positive": False,
        "best": -11.2,
        "worst": -3.1,
        "cadence": "monthly",
        "max_lag_days": 60,
        "window_days": 1826,
        "min_samples": 36,
    },
]

#: 静态参考值（外部源失败时的兜底；标注数据日期）
#:
#: ⚠ 这些不是市场读数 —— 不得写入 ``daily_money_flow_factors`` 历史表
#: （见 ``services/macro.py::is_persistable_source``）。
#:
#: 取值 = V0.120.0 上线时（2026-10-27）的**实测**读数，不是拍脑袋。
STATIC_REF: dict[str, dict] = {
    "cot_gold_net": {"value": 25.9039, "date": "2026-10-20", "note": "静态参考值"},
    "cot_gold_flow": {"value": -23183.0, "date": "2026-10-20", "note": "静态参考值"},
    "gold_etf_flow": {"value": 13.5625, "date": "2026-10-26", "note": "静态参考值"},
    "us_liq_net": {"value": 14170.2, "date": "2026-09-30", "note": "静态参考值"},
    "cn_margin_flow": {"value": -5.6531, "date": "2026-10-26", "note": "静态参考值"},
    "cn_money_gap": {"value": -4.0, "date": "2026-09-30", "note": "静态参考值"},
}

#: 周频因子（前端分组展示用）
WEEKLY_FACTORS: frozenset[str] = frozenset({"cot_gold_net", "cot_gold_flow", "gold_etf_flow"})
#: 月频因子
MONTHLY_FACTORS: frozenset[str] = frozenset({"us_liq_net", "cn_margin_flow", "cn_money_gap"})

#: 资金流综合指数结果缓存时长（秒）
MONEY_FLOW_CACHE_TTL = 600  # 10 分钟

_CACHE: dict = {"ts": 0.0, "result": None, "readings": None}


def clear_money_flow_cache() -> None:
    """失效资金流面缓存（保存权重 / 手动干预后调用）。"""
    global _CACHE
    _CACHE = {"ts": 0.0, "result": None, "readings": None}


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _friendly_score(value: float, rule: dict) -> float:
    """因子值 → 0-100 黄金友好度（线性 + 截断）。

    与宏观面同一套公式：``(value - worst) / (best - worst) * 100``，
    正/负相关天然兼容（正相关 best 在高位，负相关 best 在低位）。
    """
    best, worst = rule["best"], rule["worst"]
    if best == worst:
        return 50.0
    return _clamp((value - worst) / (best - worst) * 100, 0, 100)


@dataclass
class FlowReading:
    """一个资金流因子的当前读数。"""

    value: float
    data_date: str
    """展示用的口径说明（日期或自由文本）"""
    source: str
    """源标识 —— ``source_tier`` 据此判 live / lkg / static"""
    obs_date: date | None = None
    """**因子自身的观测日**（落表用）；降级值没有新观测日时为 ``None``"""


class MoneyFlowService:
    """资金流面采集与评分。"""

    def __init__(
        self,
        settings=None,
        threshold_calculator=None,
        history_repo=None,
    ) -> None:
        self._settings = settings
        # 滚动分位计算器（可选）。未注入 → 全 hardcode（静态阈带）。
        self._threshold_calculator = threshold_calculator
        # 历史仓储（可选）。用于「末次落库」降级层 + 滚动分位窗口。
        self._history_repo = history_repo

    def _resolve_target(self) -> str:
        """标的维度归一（资金流因子都是全市场源 → 共享同一份历史）。"""
        return "default"

    # ───────────────────── 采集 ─────────────────────

    async def collect_readings(self) -> dict[str, FlowReading]:
        """采集全部因子的当前读数（带 TTL 缓存）。

        评分与落表**共用这一份** —— 否则 scheduler 落表时会把外网再打一遍。
        """
        global _CACHE
        if _CACHE["readings"] is not None and time.time() - _CACHE["ts"] < MONEY_FLOW_CACHE_TTL:
            return _CACHE["readings"]  # type: ignore[return-value]

        readings = await self._collect()
        _CACHE = {"ts": time.time(), "result": _CACHE["result"], "readings": readings}
        return readings

    async def _collect(self) -> dict[str, FlowReading]:
        """按优先级链采集读数。

        优先级：静态参考值 < 末次落库 < 自动源。
        （本轮不含用户手动覆盖 —— 资金流面没有手动校准页。）
        """
        readings: dict[str, FlowReading] = {}
        for key, ref in STATIC_REF.items():
            readings[key] = FlowReading(
                value=float(ref["value"]),
                data_date=ref["date"],
                source=ref["note"],
                obs_date=None,
            )

        lkg = await self._collect_last_known_good()
        readings.update(lkg)

        results = await asyncio.gather(
            self._collect_cftc(),
            self._collect_etf(),
            self._collect_us_liquidity(),
            self._collect_cn_margin(),
            self._collect_cn_money(),
            return_exceptions=True,
        )
        for res in results:
            if isinstance(res, BaseException):
                logger.warning("资金流数据源失败（已回退末次落库/静态参考值）: %s", res)
                continue
            readings.update(res)
        return readings

    async def _collect_last_known_good(self) -> dict[str, FlowReading]:
        """「上次成功落库的真实读数」兜底层（与宏观面同款）。"""
        if self._history_repo is None:
            return {}
        try:
            rows = await self._history_repo.get_latest_per_factor(self._resolve_target())
        except Exception as exc:
            logger.warning("末次落库读数不可用（回退静态参考值）: %s", exc)
            return {}
        known = {r["key"] for r in MONEY_FLOW_FACTOR_RULES}
        out: dict[str, FlowReading] = {}
        for key, row in rows.items():
            if key not in known:
                continue
            if not is_persistable_source(row.source):
                # 理论上不该存在（落表时被挡住），历史表可能被手改过 —— 跳过
                continue
            out[key] = FlowReading(
                value=float(row.value),
                data_date=row.data_date,
                source=LAST_KNOWN_GOOD_PREFIX + "·" + row.source,
                obs_date=row.snapshot_date,
            )
        if out:
            logger.info("资金流因子降级到末次落库读数: %s", sorted(out))
        return out

    async def _collect_cftc(self) -> dict[str, FlowReading]:
        """CFTC 黄金投机净多：水平（占 OI %）+ 4 周变化。"""
        from app.repositories.money_flow_sources import (
            CFTC_SOURCE,
            fetch_cftc_gold_positions,
        )

        points = await fetch_cftc_gold_positions(min_points=8)
        if not points:
            return {}
        latest = points[-1]
        out: dict[str, FlowReading] = {
            "cot_gold_net": FlowReading(
                value=round(latest.net_pct_oi, 4),
                data_date=latest.obs_date.isoformat(),
                source=CFTC_SOURCE,
                obs_date=latest.obs_date,
            )
        }
        if len(points) >= 5:
            # 4 周变化 = 最新周与 4 周前的净多之差
            delta = latest.net_long - points[-5].net_long
            out["cot_gold_flow"] = FlowReading(
                value=float(delta),
                data_date=latest.obs_date.isoformat(),
                source=CFTC_SOURCE,
                obs_date=latest.obs_date,
            )
        else:
            logger.warning("CFTC 观测不足 5 周，cot_gold_flow 暂缺")
        return out

    async def _collect_etf(self) -> dict[str, FlowReading]:
        """黄金 ETF 4 周累计净申赎（亿元）。

        口径：**上交所官方每日基金份额**（万份）× 窗口末日收盘价。
        不用「成交量 ÷ 换手率」重建 —— 官方份额没有量化误差。

        ⚠️ 窗口末日锚在**周网格**上（ISO 周的最后一个交易日），不是「最新交易日」：
        本因子的规则声明 ``cadence=weekly``，若末日跟着最新交易日走，
        每日调度就会一天写一行，而相邻几天的 4 周累计窗口几乎是同一个数
        ⇒ 同一周被重复计入滚动分位窗口 ⇒ 样本量虚高、近期状态被过度加权。
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
            return {}
        trading_days = sorted(closes)
        week_ends = week_end_days(trading_days)
        if len(week_ends) < 2:
            logger.warning("交易日不足两周，gold_etf_flow 暂缺")
            return {}

        # 窗口末日：从最近的周末日**往回退**，直到上交所真的发布了那一天的份额。
        #
        # ⚠ 为什么要往回退：上交所的份额要等结算后才发布（实测：盘中查当天 →
        # result=null），周五的份额通常周一才发布。
        shares_end: float | None = None
        end_day: date | None = None
        for candidate in reversed(week_ends[-3:]):
            v = await fetch_sse_etf_shares(GOLD_ETF_SYMBOL, candidate)
            if v is not None:
                shares_end = v
                end_day = candidate
                break
        if shares_end is None or end_day is None:
            logger.warning("上交所 ETF 份额近 3 个周末日均缺失，gold_etf_flow 暂缺")
            return {}

        # 4 周前的那一周的周末日（同一张网格，容忍 ±7 天避开节假日）
        target = end_day - timedelta(days=28)
        prev_candidates = sorted(
            (d for d in week_ends if abs((d - target).days) <= 7),
            key=lambda d: abs((d - target).days),
        )
        shares_prev: float | None = None
        prev_day: date | None = None
        for candidate in prev_candidates:
            v = await fetch_sse_etf_shares(GOLD_ETF_SYMBOL, candidate)
            if v is not None:
                shares_prev = v
                prev_day = candidate
                break
        if shares_prev is None or prev_day is None:
            logger.warning("上交所 ETF 份额（4 周前 %s 附近）缺失，gold_etf_flow 暂缺", target)
            return {}

        # Δ万份 × 元/份 → 亿元
        delta_yi = (shares_end - shares_prev) * closes[end_day] / 1e4
        return {
            "gold_etf_flow": FlowReading(
                value=round(delta_yi, 4),
                data_date=f"{prev_day.isoformat()}~{end_day.isoformat()}",
                source=SSE_SOURCE,
                obs_date=end_day,
            )
        }

    async def _collect_us_liquidity(self) -> dict[str, FlowReading]:
        """美元净流动性 4 周变化（$M）—— **月频观测**。

        净流动性 = WALCL（美联储总资产）− WTREGEN（国库券）− RRPONTSYD（逆回购）。
        用 **4 周变化**而非 1 周：1 周变化被 TGA 季度末摆动主导。

        ⚠️ 观测网格是**月频**（每个已过完的月一行），尽管源数据是周更：
        本因子取的是「4 周变化」，相邻两次观测**重叠 3/4** ⇒ 按周落表会让
        有效样本数只剩名义值的 1/4（同一个量被重复计入滚动分位窗口）。
        详见 ``repositories/money_flow_sources.py::fetch_us_net_liquidity_monthly``。
        """
        from app.repositories.money_flow_sources import (
            US_LIQ_SOURCE,
            fetch_us_net_liquidity_monthly,
        )

        rows = await fetch_us_net_liquidity_monthly()
        if not rows:
            return {}
        obs_date, delta, prev_end = rows[-1]
        return {
            "us_liq_net": FlowReading(
                value=round(delta, 1),
                data_date=f"{prev_end.isoformat()}~{obs_date.isoformat()}",
                source=US_LIQ_SOURCE,
                obs_date=obs_date,
            )
        }

    async def _collect_cn_margin(self) -> dict[str, FlowReading]:
        """A 股融资余额月环比（%）。

        沪深两市「融资余额」相加 → 取**完整月末**值 → 环比变化率。

        ⚠️ 为什么只取**已过完的月份**：本因子的规则声明 ``cadence=monthly``。
        若拿「当月至今」当观测值，观测日每天推进 ⇒ 每日调度一天写一行，
        而同一个月的 20 来行几乎是同一个数 ⇒ 同一月被重复计入滚动分位窗口
        ⇒ 样本量虚高、当前月被过度加权。且「月内变动」与「月环比」不是同一个量。
        取已过完的月份后，观测日 = 该月最后一个交易日 ⇒ 一个月恰好一行。
        """
        from app.repositories.money_flow_sources import (
            MARGIN_SOURCE,
            fetch_cn_margin_balances,
        )

        rows = await fetch_cn_margin_balances()
        if len(rows) < 2:
            return {}
        by_month: dict[tuple[int, int], tuple[date, float]] = {}
        for d, v in rows:
            key = (d.year, d.month)
            cur = by_month.get(key)
            if cur is None or d > cur[0]:
                by_month[key] = (d, v)
        months = sorted(by_month)
        # 丢掉**还没过完**的当月（其「月末值」其实是月内至今值）
        today = date.today()
        if months and months[-1] == (today.year, today.month):
            months = months[:-1]
        if len(months) < 2:
            return {}
        last_d, last_v = by_month[months[-1]]
        _prev_d, prev_v = by_month[months[-2]]
        if prev_v <= 0:
            return {}
        return {
            "cn_margin_flow": FlowReading(
                value=round((last_v / prev_v - 1.0) * 100.0, 4),
                data_date=last_d.isoformat(),
                source=MARGIN_SOURCE,
                obs_date=last_d,
            )
        }

    async def _collect_cn_money(self) -> dict[str, FlowReading]:
        """中国 M1−M2 剪刀差（百分点）。"""
        from app.repositories.money_flow_sources import (
            MONEY_SUPPLY_SOURCE,
            fetch_cn_money_supply,
        )

        rows = await fetch_cn_money_supply()
        if not rows:
            return {}
        obs_date, m1, m2 = rows[-1]
        return {
            "cn_money_gap": FlowReading(
                value=round(m1 - m2, 4),
                data_date=obs_date.isoformat(),
                source=MONEY_SUPPLY_SOURCE,
                obs_date=obs_date,
            )
        }

    # ───────────────────── 评分 ─────────────────────

    async def evaluate(self) -> MoneyFlowIndexOut:
        """采集并合成资金流面指数（0-100）。"""
        global _CACHE
        if _CACHE["result"] is not None and time.time() - _CACHE["ts"] < MONEY_FLOW_CACHE_TTL:
            return _CACHE["result"]  # type: ignore[return-value]

        result = await self._evaluate_uncached()
        _CACHE = {"ts": time.time(), "result": result, "readings": _CACHE["readings"]}
        return result

    async def _evaluate_uncached(self) -> MoneyFlowIndexOut:
        readings = await self.collect_readings()
        weights = await self._settings.money_flow_weights() if self._settings is not None else {}

        # 本轮**真实观测**（live / lkg）的因子有没有？
        #
        # ⚠ 静态兜底值不是市场读数（见 ``STATIC_REF`` 的注释）。若 6 个因子**全部**
        # 只剩静态兜底 —— 即外网 5 个源全挂 **且** 历史表里也读不到任何一行 ——
        # 整面就一个真实读数都没有 ⇒ 必须 ``score=None``（从综合指数剔除），
        # 而不是把 2026-10 的常量当成「今天的资金流」交给综合指数。
        # 这正是 V0.118.1「兜底层才是真正的契约」的同款问题：
        # 降级值可以救**单个因子**，但救不了**整面**。
        has_real_reading = any(
            source_tier(r.source) != "static" for r in readings.values() if r is not None
        )

        if self._threshold_calculator is not None:
            flow_target = self._resolve_target()
            thresholds = await self._threshold_calculator.get_or_compute(flow_target)
            flow_dynamic = self._threshold_calculator.is_dynamic_active(
                thresholds, target=flow_target
            )
        else:
            flow_target = self._resolve_target()
            thresholds = {
                r["key"]: (float(r["best"]), float(r["worst"])) for r in MONEY_FLOW_FACTOR_RULES
            }
            flow_dynamic = False

        hardcode = {
            r["key"]: (float(r["best"]), float(r["worst"])) for r in MONEY_FLOW_FACTOR_RULES
        }
        # V0.120.0：用计算器**记录**的滚动集，而不是「阈值 ≠ hardcode」反推。
        # 资金流面的静态带就是拿同一段 5 年历史标定的 ⇒ 滚动分位算出的
        # best/worst 可能与静态带**逐位相同**（cn_money_gap 实测如此），
        # 值比较会把它误报成「还在用静态阈值」⇒ badge 说 5/6 而真相是 6/6。
        applied = (
            self._threshold_calculator.rolling_keys(flow_target)
            if self._threshold_calculator is not None
            else frozenset()
        )
        if applied:
            dynamic_factors = sorted(applied)
        else:
            dynamic_factors = [k for k, v in thresholds.items() if hardcode.get(k) != v]

        total = 0.0
        total_weight = 0.0
        weekly_weight = 0.0
        monthly_weight = 0.0
        factors: list[MoneyFlowFactorOut] = []
        for rule in MONEY_FLOW_FACTOR_RULES:
            key = rule["key"]
            reading = readings.get(key)
            if reading is None:
                logger.warning("资金流因子 %s 无读数，本轮剔除", key)
                continue
            weight = weights.get(key, rule["weight"])
            rule_eff = dict(rule)
            rule_eff["best"], rule_eff["worst"] = thresholds[key]
            score = _friendly_score(reading.value, rule_eff)
            total += score * weight
            total_weight += weight
            if key in WEEKLY_FACTORS:
                weekly_weight += weight
            else:
                monthly_weight += weight
            direction = (
                DirectionSignal.BULLISH
                if score >= int(DirectionThreshold.NEUTRAL_HIGH)
                else DirectionSignal.BEARISH
                if score <= int(DirectionThreshold.NEUTRAL_LOW)
                else DirectionSignal.NEUTRAL
            )
            factors.append(
                MoneyFlowFactorOut(
                    key=key,
                    name=rule["name"],
                    value=f"{reading.value:g}",
                    unit=rule["unit"],
                    data_date=reading.data_date,
                    source=reading.source,
                    tier=source_tier(reading.source),
                    cadence=rule["cadence"],
                    max_lag_days=int(rule["max_lag_days"]),
                    window_days=int(rule["window_days"]),
                    score=round(score, 1),
                    direction=direction,
                    weight=weight,
                    contribution=0.0,
                    detail=f"{rule['name']} {reading.value:g} {rule['unit']}，黄金友好度 {score:.0f}/100",
                )
            )

        if total_weight > 0 and abs(total_weight - 1.0) > 1e-9:
            logger.warning("资金流因子权重合计 %.4f ≠ 1，按剩余权重归一化", total_weight)
            total = total / total_weight
        for f in factors:
            f.contribution = round(f.score * f.weight / total_weight, 2) if total_weight else 0.0

        if not factors or not has_real_reading:
            # 一个因子都没取到读数 ⇒ 整面不可用，**不能返回 0 分**：
            # 0 分会被综合指数当成「资金正在撤离黄金」，而真相是「没数」。
            # 同理：全部因子只剩静态兜底值时，整面也没有真实读数 ⇒ 一样剔除。
            logger.warning(
                "资金流面本轮无任何有效读数（factors=%d, 真实观测=%s），整面从综合指数剔除",
                len(factors),
                has_real_reading,
            )
            return MoneyFlowIndexOut(
                score=None,
                direction=DirectionSignal.NEUTRAL,
                factors=[],
                summary=self._summarize(None, DirectionSignal.NEUTRAL),
                flow_dynamic=flow_dynamic,
                dynamic_factors=dynamic_factors,
                rolling_factors=[r["key"] for r in MONEY_FLOW_FACTOR_RULES],
                weekly_weight=0.0,
                monthly_weight=0.0,
            )

        total = round(total, 1)
        direction = (
            DirectionSignal.BULLISH
            if total >= int(DirectionThreshold.BULLISH)
            else DirectionSignal.BEARISH
            if total <= int(DirectionThreshold.BEARISH)
            else DirectionSignal.NEUTRAL
        )
        logger.info(
            "Money flow index: %.1f (%s), %d factors, weekly=%.0f%% monthly=%.0f%%",
            total,
            direction.value,
            len(factors),
            weekly_weight / total_weight * 100 if total_weight else 0.0,
            monthly_weight / total_weight * 100 if total_weight else 0.0,
        )
        return MoneyFlowIndexOut(
            score=total,
            direction=direction,
            factors=factors,
            summary=self._summarize(total, direction),
            flow_dynamic=flow_dynamic,
            dynamic_factors=dynamic_factors,
            rolling_factors=[r["key"] for r in MONEY_FLOW_FACTOR_RULES],
            weekly_weight=round(weekly_weight / total_weight, 4) if total_weight else 0.0,
            monthly_weight=round(monthly_weight / total_weight, 4) if total_weight else 0.0,
        )

    async def persistable_rows(self) -> list[tuple[date, str, float, str, str]]:
        """本轮可落表的观测行：``(观测日, key, value, data_date, source)``。

        只写**本次真的观测到**的读数（``is_persistable_source``）——
        静态常量与「末次落库」都不写（否则滚动分位窗口会被假数据带偏）。
        观测日取因子自身的观测日；没有观测日的（降级值）不落表。
        """
        readings = await self.collect_readings()
        rows: list[tuple[date, str, float, str, str]] = []
        for key, reading in readings.items():
            if reading.obs_date is None:
                continue
            if not is_persistable_source(reading.source):
                continue
            rows.append((reading.obs_date, key, reading.value, reading.data_date, reading.source))
        return rows

    @staticmethod
    def _summarize(score: float | None, direction: DirectionSignal) -> str:
        """资金流面摘要。"""
        if score is None:
            return "资金流面本轮无有效读数，整面不可用（已从综合指数剔除）"
        txt = {
            DirectionSignal.BULLISH: "资金正在流入黄金",
            DirectionSignal.BEARISH: "资金正在撤离黄金",
            DirectionSignal.NEUTRAL: "资金流向中性",
        }[direction]
        return (
            f"资金流面指数 {score:.1f}/100，{txt}"
            "（CFTC 黄金投机净多及 4 周变化、黄金ETF 4 周累计净申赎、"
            "美元净流动性 4 周变化、A股融资余额月变动、M1-M2 剪刀差）"
        )
