"""资金流面服务测试（V0.120.0）。

覆盖 5 组：
1. 规则表自洽（6 个因子、权重合计 1、周/月各 3、窗口与节奏匹配）
2. 打分公式（best→100 / worst→0 / 中点→50 / 越界截断 / 负号口径）
3. evaluate() 端到端（因子明细、贡献、周/月权重合计）
4. 降级链（live / lkg / static 三层，tier 正确）
5. 落表口径（静态与末次落库**不落表**；观测日用因子自身的观测日）
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.schemas.market import MoneyFlowIndexOut
from app.services import money_flow as mf
from app.services.money_flow import (
    MONEY_FLOW_FACTOR_RULES,
    MONTHLY_FACTORS,
    STATIC_REF,
    WEEKLY_FACTORS,
    FlowReading,
    MoneyFlowService,
    _friendly_score,
)

KEYS = [r["key"] for r in MONEY_FLOW_FACTOR_RULES]
RULE_BY_KEY = {r["key"]: r for r in MONEY_FLOW_FACTOR_RULES}


@pytest.fixture(autouse=True)
def _clear_money_flow_cache():
    """每个用例前后清掉**模块级**结果缓存。

    ⚠ ``MoneyFlowService.evaluate()`` 走 ``services/money_flow.py::_CACHE``
    （进程级，TTL 10 分钟）。只覆盖 ``collect_readings`` 不够 ——
    缓存里存的是**上一次 evaluate 的整个结果**，不清理的话后一个用例会拿到
    前一个用例的因子列表与权重（本次就是踩这个：自定义权重的用例拿到了
    默认权重的缓存结果）。
    """
    mf.clear_money_flow_cache()
    yield
    mf.clear_money_flow_cache()


# ───────────────────────── 1. 规则表自洽 ─────────────────────────


def test_规则表_6个因子且权重合计为1():
    assert len(MONEY_FLOW_FACTOR_RULES) == 6
    assert abs(sum(float(r["weight"]) for r in MONEY_FLOW_FACTOR_RULES) - 1.0) < 1e-9


def test_规则表_周3月3且与常量集合一致():
    weekly = {r["key"] for r in MONEY_FLOW_FACTOR_RULES if r["cadence"] == "weekly"}
    monthly = {r["key"] for r in MONEY_FLOW_FACTOR_RULES if r["cadence"] == "monthly"}
    assert weekly == set(WEEKLY_FACTORS)
    assert monthly == set(MONTHLY_FACTORS)
    assert len(weekly) == 3
    assert len(monthly) == 3
    assert weekly.isdisjoint(monthly)
    assert weekly | monthly == set(KEYS)


def test_规则表_滚动窗口按节奏匹配():
    """周频 104 周（728 日）/ 月频 60 月（1826 日）。

    ⚠ 窗口必须跟节奏走：同一个 252 日窗口对周频只装 36 个观测、对月频只有 8 个
    ⇒ 样本不足 ⇒ 阈值永远退回硬编码（V0.119.0 记过的坑）。
    """
    for r in MONEY_FLOW_FACTOR_RULES:
        if r["cadence"] == "weekly":
            assert r["window_days"] == 728, r["key"]
        else:
            assert r["window_days"] == 1826, r["key"]
        assert r["min_samples"] >= 30, r["key"]
        assert r["max_lag_days"] > 0


def test_规则表_阈值带best不等于worst():
    """best == worst 会让打分恒为 50（退化）。"""
    for r in MONEY_FLOW_FACTOR_RULES:
        assert float(r["best"]) != float(r["worst"]), r["key"]


def test_规则表_两个中国因子取负号口径():
    """用户拍板：机会成本口径（值越高越利空黄金）。"""
    assert RULE_BY_KEY["cn_margin_flow"]["positive"] is False
    assert RULE_BY_KEY["cn_money_gap"]["positive"] is False
    # 负号口径 ⇒ best 在低位、worst 在高位
    for k in ("cn_margin_flow", "cn_money_gap"):
        assert float(RULE_BY_KEY[k]["best"]) < float(RULE_BY_KEY[k]["worst"]), k
    for k in ("cot_gold_net", "cot_gold_flow", "gold_etf_flow", "us_liq_net"):
        assert RULE_BY_KEY[k]["positive"] is True
        assert float(RULE_BY_KEY[k]["best"]) > float(RULE_BY_KEY[k]["worst"]), k


def test_静态兜底值覆盖全部因子():
    assert set(STATIC_REF) == set(KEYS)
    for v in STATIC_REF.values():
        assert isinstance(v["value"], (int, float))
        assert v["date"]


# ───────────────────────── 2. 打分公式 ─────────────────────────


def test_打分_best得100_worst得0_中点得50():
    rule = dict(RULE_BY_KEY["cot_gold_net"])
    assert _friendly_score(rule["best"], rule) == pytest.approx(100.0)
    assert _friendly_score(rule["worst"], rule) == pytest.approx(0.0)
    mid = (rule["best"] + rule["worst"]) / 2
    assert _friendly_score(mid, rule) == pytest.approx(50.0)


def test_打分_越界截断():
    """超出阈带的读数必须截断到 0/100，而不是线性外推。

    ⚠ 注意方向：``worst`` 本身可能是**正数**（cot_gold_net 的 worst=6.49%），
    所以「低于 worst」要用**减法**构造，不能用 ``worst * 10`` ——
    那样算出来是 64.9，反而**高于** best（34.1），截断到 100 而不是 0。
    """
    rule = dict(RULE_BY_KEY["cot_gold_net"])
    assert _friendly_score(rule["best"] + 100, rule) == 100.0
    assert _friendly_score(rule["worst"] - 100, rule) == 0.0


def test_打分_带子午线为0时恒50():
    rule = dict(RULE_BY_KEY["cot_gold_net"])
    rule["best"] = rule["worst"] = 1.0
    assert _friendly_score(123.0, rule) == 50.0


def test_打分_负号口径下高值得低分():
    """机会成本口径：融资余额**上升** = 股市杠杆加码 = 黄金承压 ⇒ 分数低。"""
    rule = dict(RULE_BY_KEY["cn_margin_flow"])
    high = _friendly_score(rule["worst"], rule)  # 余额大涨
    low = _friendly_score(rule["best"], rule)  # 余额大跌
    assert high < low
    assert high == pytest.approx(0.0)
    assert low == pytest.approx(100.0)


# ───────────────────────── 3. evaluate() ─────────────────────────


def _svc(readings, settings=None, threshold_calculator=None, history_repo=None):
    """构造一个只返回固定读数的 service。

    ⚠ 覆盖的是 ``collect_readings``（不是 ``_collect``）—— evaluate() 与
    persistable_rows() 都走前者，而 collect_readings 背后是**模块级缓存**：
    直接覆盖 _collect 会让假读数进缓存、串到别的测试里。
    """
    svc = MoneyFlowService(
        settings=settings,
        threshold_calculator=threshold_calculator,
        history_repo=history_repo,
    )

    async def _collect_readings():
        return dict(readings)

    svc.collect_readings = _collect_readings  # type: ignore[method-assign]
    return svc


def _live_readings():
    """6 个因子各给一个 live 读数（source 不带降级前缀 ⇒ tier=live）。"""
    return {
        "cot_gold_net": FlowReading(
            value=25.9, data_date="2026-10-20", source="CFTC 分类持仓", obs_date=date(2026, 10, 20)
        ),
        "cot_gold_flow": FlowReading(
            value=-23183.0,
            data_date="2026-10-20",
            source="CFTC 分类持仓",
            obs_date=date(2026, 10, 20),
        ),
        "gold_etf_flow": FlowReading(
            value=13.5625,
            data_date="2026-10-26",
            source="上交所 ETF 份额",
            obs_date=date(2026, 10, 26),
        ),
        "us_liq_net": FlowReading(
            value=14170.2,
            data_date="2026-08-31~2026-09-30",
            source="FRED WALCL/TGA/RRP",
            obs_date=date(2026, 9, 30),
        ),
        "cn_margin_flow": FlowReading(
            value=-5.6531,
            data_date="2026-10-26",
            source="沪深融资余额",
            obs_date=date(2026, 10, 26),
        ),
        "cn_money_gap": FlowReading(
            value=-4.0, data_date="2026-09-30", source="央行 M1/M2", obs_date=date(2026, 9, 30)
        ),
    }


async def test_evaluate_产出6个因子与正确元数据():
    svc = _svc(_live_readings())
    out = await svc.evaluate()
    assert isinstance(out, MoneyFlowIndexOut)
    assert len(out.factors) == 6
    assert {f.key for f in out.factors} == set(KEYS)
    for f in out.factors:
        assert f.tier == "live"
        assert 0 <= f.score <= 100
        assert f.cadence in ("weekly", "monthly")
        assert f.window_days == RULE_BY_KEY[f.key]["window_days"]
        assert f.max_lag_days == RULE_BY_KEY[f.key]["max_lag_days"]
        assert f.contribution >= 0
    # 面内权重合计 = 1
    assert sum(f.weight for f in out.factors) == pytest.approx(1.0)
    # 贡献合计 = 指数
    assert sum(f.contribution for f in out.factors) == pytest.approx(out.score, abs=0.15)


async def test_evaluate_周月权重分别对应各档因子():
    svc = _svc(_live_readings())
    out = await svc.evaluate()
    weekly = sum(f.weight for f in out.factors if f.key in WEEKLY_FACTORS)
    monthly = sum(f.weight for f in out.factors if f.key in MONTHLY_FACTORS)
    assert out.weekly_weight == pytest.approx(weekly)
    assert out.monthly_weight == pytest.approx(monthly)
    assert out.weekly_weight + out.monthly_weight == pytest.approx(1.0)


async def test_evaluate_缺读数的因子被剔除且权重归一化():
    """读数缺失 → 该因子不参与（不是记 0 分），其余权重归一化。

    口径（与宏观面同款，见 ``schemas/market.py::MacroFactorOut.weight``）：
    ``weight`` 是**配置权重**、不随剔除缩放；本次实际生效的权重体现在
    ``contribution`` 上。故「权重合计」按配置口径校验，贡献分按归一化口径校验。
    """
    readings = _live_readings()
    del readings["gold_etf_flow"]
    svc = _svc(readings)
    out = await svc.evaluate()
    assert len(out.factors) == 5
    assert "gold_etf_flow" not in {f.key for f in out.factors}
    # 配置权重之和 = 1 - 被剔除因子的配置权重
    assert sum(f.weight for f in out.factors) == pytest.approx(
        1.0 - float(RULE_BY_KEY["gold_etf_flow"]["weight"])
    )
    # 归一化体现在贡献分上：Σcontribution = 指数分
    assert sum(f.contribution for f in out.factors) == pytest.approx(out.score, abs=0.15)
    # 周/月两档占比也按剩余权重归一化（合计仍是 1）
    assert out.weekly_weight + out.monthly_weight == pytest.approx(1.0)


async def test_evaluate_全部缺失时不给0分指数():
    """一个因子都没取到读数 ⇒ ``score`` 必须是 ``None``（整面剔除）。

    ⚠ 返回 0 分会被综合指数当成「资金正在撤离黄金」—— 真相是「没数」，
    这是 V0.118.1「兜底层才是真正的契约」纪律的同款问题。
    """
    svc = _svc({})
    out = await svc.evaluate()
    assert out.factors == []
    assert out.score is None
    assert "无有效读数" in out.summary


async def test_evaluate_全部只剩静态兜底时整面剔除():
    """6 个因子全是静态兜底值 ⇒ 整面没有真实读数 ⇒ ``score`` 必须 ``None``。

    ⚠ 静态兜底值是上线时的常量（2026-10），**不是市场读数**
    （见 ``services/money_flow.py::STATIC_REF`` 的注释）。
    把它当成「今天的资金流」交给综合指数 = 谎报观测 ——
    正是 V0.118.1「兜底层才是真正的契约」纪律要防的那类事：
    降级值能救**单个因子**，但救不了**整面**。
    """
    readings = {
        key: FlowReading(
            value=float(ref["value"]),
            data_date=ref["date"],
            source=ref["note"],
            obs_date=None,
        )
        for key, ref in STATIC_REF.items()
    }
    svc = _svc(readings)
    out = await svc.evaluate()
    assert out.score is None
    assert out.factors == []
    assert "无有效读数" in out.summary


async def test_evaluate_用户自定义权重生效():
    """面内权重来自 settings（用户可在权重页改）—— 不是写死的。"""

    class _Settings:
        async def money_flow_weights(self):
            return {
                "cot_gold_net": 0.5,
                "cot_gold_flow": 0.1,
                "gold_etf_flow": 0.2,
                "us_liq_net": 0.1,
                "cn_margin_flow": 0.05,
                "cn_money_gap": 0.05,
            }

    svc = _svc(_live_readings(), settings=_Settings())
    out = await svc.evaluate()
    by = {f.key: f for f in out.factors}
    assert by["cot_gold_net"].weight == pytest.approx(0.5)
    assert by["cn_money_gap"].weight == pytest.approx(0.05)


# ───────────────────────── 4. 降级链 ─────────────────────────


async def test_降级_末次落库读数标tier_lkg():
    from app.services.macro import LAST_KNOWN_GOOD_PREFIX

    readings = _live_readings()
    readings["cot_gold_net"] = FlowReading(
        value=20.0,
        data_date="2026-10-13",
        source=LAST_KNOWN_GOOD_PREFIX + "·CFTC 分类持仓",
        obs_date=date(2026, 10, 13),
    )
    svc = _svc(readings)
    out = await svc.evaluate()
    f = next(x for x in out.factors if x.key == "cot_gold_net")
    assert f.tier == "lkg"


async def test_降级_静态兜底读数标tier_static():
    readings = _live_readings()
    readings["us_liq_net"] = FlowReading(
        value=STATIC_REF["us_liq_net"]["value"],
        data_date=STATIC_REF["us_liq_net"]["date"],
        source=STATIC_REF["us_liq_net"]["note"],
        obs_date=None,
    )
    svc = _svc(readings)
    out = await svc.evaluate()
    f = next(x for x in out.factors if x.key == "us_liq_net")
    assert f.tier == "static"


async def test_降级_末次落库读数来自历史仓储():
    """history_repo 提供「上次成功落库的真实读数」，源不可用时顶上。

    ⚠ 仓储返回的是**ORM 行对象**，服务按属性读（``row.source`` / ``row.value`` /
    ``row.data_date`` / ``row.snapshot_date``）—— 用 dict 替身会直接
    ``AttributeError``（这正是本用例第一版的失败原因）。
    """

    class _Repo:
        async def get_latest_per_factor(self, target):
            assert target == "default"
            return {
                "gold_etf_flow": SimpleNamespace(
                    key="gold_etf_flow",
                    value=42.0,
                    data_date="2026-10-20",
                    source="上交所 ETF 份额",
                    snapshot_date=date(2026, 10, 20),
                )
            }

    svc = MoneyFlowService(history_repo=_Repo())
    readings = await svc._collect_last_known_good()
    assert "gold_etf_flow" in readings
    assert readings["gold_etf_flow"].value == 42.0
    assert "末次" in readings["gold_etf_flow"].source


async def test_降级_历史表里的静态值不被当末次落库():
    """历史表若被手改塞进静态常量，不能拿它当「真实读数」顶上。"""

    class _Repo:
        async def get_latest_per_factor(self, target):
            return {
                "gold_etf_flow": SimpleNamespace(
                    key="gold_etf_flow",
                    value=42.0,
                    data_date="2026-10-20",
                    source="静态参考值",
                    snapshot_date=date(2026, 10, 20),
                )
            }

    svc = MoneyFlowService(history_repo=_Repo())
    readings = await svc._collect_last_known_good()
    assert readings == {}


# ───────────────────────── 5. 落表口径 ─────────────────────────


async def test_落表_只写本次真的观测到的读数():
    """静态兜底 / 末次落库**不落表** —— 否则滚动分位窗口会被假数据带偏。"""
    from app.services.macro import LAST_KNOWN_GOOD_PREFIX

    readings = _live_readings()
    readings["cot_gold_net"] = FlowReading(
        value=20.0,
        data_date="2026-10-13",
        source=LAST_KNOWN_GOOD_PREFIX + "·CFTC 分类持仓",
        obs_date=date(2026, 10, 13),
    )
    readings["us_liq_net"] = FlowReading(
        value=1.0, data_date="2026-10-01", source="静态参考值", obs_date=None
    )
    svc = _svc(readings)
    rows = await svc.persistable_rows()
    keys = {r[1] for r in rows}
    assert "cot_gold_net" not in keys
    assert "us_liq_net" not in keys
    assert "gold_etf_flow" in keys
    for obs_day, key, value, data_date, source in rows:
        assert isinstance(obs_day, date)
        assert key in KEYS
        assert isinstance(value, float)
        assert data_date
        assert source


async def test_落表_观测日取因子自身观测日():
    """snapshot_date = 因子自身的观测日（不是采集日）。

    这一点决定了滚动分位窗口里是不是**不同观测** —— 落成采集日的话，
    同一个周值会被重复约 5 次、分位带被压平成一条线。
    """
    svc = _svc(_live_readings())
    rows = await svc.persistable_rows()
    by = {r[1]: r for r in rows}
    assert by["cot_gold_net"][0] == date(2026, 10, 20)
    assert by["cn_money_gap"][0] == date(2026, 9, 30)
    today = date.today()
    for obs_day, _k, _v, _dd, _s in rows:
        assert obs_day <= today


# ───────────────────── 6. 观测节奏：月频只取已过完的月份 ─────────────────────


async def test_融资余额_只取已过完的月份(monkeypatch):
    """⚠️ 月频因子的观测日必须**稳定**在月末，否则每日调度一天写一行。

    「当月至今」的「月末值」其实是月内至今值：观测日每天推进 ⇒ 同一个月的
    20 来行几乎是同一个数 ⇒ 同一月被重复计入滚动分位窗口；
    且「月内变动」与历史行的「月末 vs 月末」不是同一个量。
    """
    from app.repositories import money_flow_sources as mfs

    rows = [
        (date(2026, 7, 31), 20000.0),
        (date(2026, 8, 31), 21000.0),
        (date(2026, 9, 30), 20400.0),
        # 当月（2026-10）至今 —— 必须被排除
        (date(2026, 10, 26), 19000.0),
        (date(2026, 10, 27), 18900.0),
    ]

    async def _fake():
        return rows

    monkeypatch.setattr(mfs, "fetch_cn_margin_balances", _fake)
    svc = MoneyFlowService(settings=None, threshold_calculator=None, history_repo=None)
    out = await svc._collect_cn_margin()
    assert "cn_margin_flow" in out
    r = out["cn_margin_flow"]
    # 2026-09-30 vs 2026-08-31：20400 / 21000 - 1 = -2.857%
    assert r.value == pytest.approx(-2.8571, abs=1e-3)
    assert r.obs_date == date(2026, 9, 30), "观测日必须是已过完那个月的月末"
    assert r.data_date == "2026-09-30"


async def test_融资余额_只有当月数据时整条缺失(monkeypatch):
    """只剩进行中的当月 ⇒ 没有可比的完整月 ⇒ 该因子暂缺（而不是给一个半成品）。"""
    from app.repositories import money_flow_sources as mfs

    rows = [(date(2026, 10, 26), 19000.0), (date(2026, 10, 27), 18900.0)]

    async def _fake():
        return rows

    monkeypatch.setattr(mfs, "fetch_cn_margin_balances", _fake)
    svc = MoneyFlowService(settings=None, threshold_calculator=None, history_repo=None)
    out = await svc._collect_cn_margin()
    assert out == {}


# ───────────────────── 7. 观测节奏：周频锚在周末日 ─────────────────────


async def test_黄金ETF_窗口末日锚在周末日而不是最新交易日(monkeypatch):
    """⚠️ 周频因子的窗口末日若跟着「最新交易日」走 ⇒ 每日调度一天写一行，
    而相邻几天的 4 周累计窗口几乎是同一个数 ⇒ 同一周被重复计入滚动分位窗口。

    期望：末日 = 最近一个**已过完的周**的最后一个交易日（周五），
    起点 = 同一张网格上约 4 周前的那一周的末日。
    """
    from app.repositories import money_flow_sources as mfs

    # 2026-09-21 ~ 2026-10-30 的全部工作日
    days = []
    d = date(2026, 9, 21)
    while d <= date(2026, 10, 30):
        if d.weekday() < 5:
            days.append(d)
        d = date.fromordinal(d.toordinal() + 1)
    closes = {x: 1.0 for x in days}
    shares = {x: 2000.0 for x in days}
    shares[date(2026, 10, 23)] = 1000.0  # 只有 10-23 当周净赎回

    async def _fake_closes(_sym):
        return closes

    async def _fake_shares(_sym, day):
        return shares.get(day)

    monkeypatch.setattr(mfs, "fetch_sina_etf_closes", _fake_closes)
    monkeypatch.setattr(mfs, "fetch_sse_etf_shares", _fake_shares)

    svc = MoneyFlowService(settings=None, threshold_calculator=None, history_repo=None)
    out = await svc._collect_etf()
    assert "gold_etf_flow" in out
    r = out["gold_etf_flow"]
    # 「今天」是 2026-10-28（周三）⇒ 本周（10-26 ~ 11-01）还没过完 ⇒ 末日回退到 10-23（周五）
    assert r.obs_date == date(2026, 10, 23)
    assert r.data_date == "2026-09-25~2026-10-23"
    # Δ = (1000 - 2000) 万份 × 1.0 元/份 = -1000 万元 = -0.1 亿元
    assert r.value == pytest.approx(-0.1, abs=1e-6)


async def test_黄金ETF_周末日份额未发布时自动往前回退(monkeypatch):
    """上周五的份额通常周一才发布 ⇒ 末日要能往前退一周。"""
    from app.repositories import money_flow_sources as mfs

    days = []
    d = date(2026, 9, 1)
    while d <= date(2026, 10, 30):
        if d.weekday() < 5:
            days.append(d)
        d = date.fromordinal(d.toordinal() + 1)
    closes = {x: 1.0 for x in days}
    # 10-23 的份额还没发布（result=null）
    published = {x for x in days if x != date(2026, 10, 23)}

    async def _fake_closes(_sym):
        return closes

    async def _fake_shares(_sym, day):
        return 1000.0 if day in published else None

    monkeypatch.setattr(mfs, "fetch_sina_etf_closes", _fake_closes)
    monkeypatch.setattr(mfs, "fetch_sse_etf_shares", _fake_shares)

    svc = MoneyFlowService(settings=None, threshold_calculator=None, history_repo=None)
    out = await svc._collect_etf()
    assert "gold_etf_flow" in out
    assert out["gold_etf_flow"].obs_date == date(2026, 10, 16)


async def test_美元流动性_观测日锚在月末而不是最新周(monkeypatch):
    """⚠️ 月频因子（4 周变化）若按周落表 ⇒ 相邻两次观测**重叠 3/4**，
    有效样本数只剩名义值的 1/4 ⇒ 滚动分位窗口被同一个量灌满。

    期望：观测日 = **已过完的月**的月末（2026-09-30），
    值 = asof(9-30) − asof(8-31)（TGA / RRP 恒定 ⇒ 只剩 WALCL 的变化）。
    """
    from app.repositories import macro_sources

    # WALCL / WTREGEN 是周更（H.4.1 每周三），RRP 是日频
    wednesdays = []
    d = date(2026, 6, 3)
    while d <= date(2026, 10, 21):
        if d.weekday() == 2:
            wednesdays.append(d)
        d = date.fromordinal(d.toordinal() + 1)
    walcl = {x: 1000.0 + 10.0 * i for i, x in enumerate(wednesdays)}
    tga = {x: 100.0 for x in wednesdays}
    rrp = {x: 50.0 for x in wednesdays}

    async def _fake_fred(sid, base_url=None):
        return {"WALCL": walcl, "WTREGEN": tga, "RRPONTSYD": rrp}[sid]

    monkeypatch.setattr(macro_sources, "fetch_fred_series", _fake_fred)

    svc = MoneyFlowService(settings=None, threshold_calculator=None, history_repo=None)
    out = await svc._collect_us_liquidity()
    assert "us_liq_net" in out
    r = out["us_liq_net"]
    # 「今天」是 2026-10-28 ⇒ 当月还没过完 ⇒ 锚点回退到 09-30
    assert r.obs_date == date(2026, 9, 30)
    assert r.data_date == "2026-08-31~2026-09-30"
    # asof(9-30) 的 WALCL 减去 asof(8-31) 的 WALCL（中间隔 5 个周三）
    assert r.value == pytest.approx(50.0, abs=1e-6)


async def test_美元流动性_只取已过完的月份(monkeypatch):
    """当月至今**不是**月末值 ⇒ 不能当观测（与融资余额因子同款口径）。"""
    from app.repositories import macro_sources

    wednesdays = []
    d = date(2026, 8, 5)
    while d <= date(2026, 10, 21):
        if d.weekday() == 2:
            wednesdays.append(d)
        d = date.fromordinal(d.toordinal() + 1)
    walcl = {x: 500.0 for x in wednesdays}
    tga = {x: 0.0 for x in wednesdays}
    rrp = {x: 0.0 for x in wednesdays}

    async def _fake_fred(sid, base_url=None):
        return {"WALCL": walcl, "WTREGEN": tga, "RRPONTSYD": rrp}[sid]

    monkeypatch.setattr(macro_sources, "fetch_fred_series", _fake_fred)

    svc = MoneyFlowService(settings=None, threshold_calculator=None, history_repo=None)
    out = await svc._collect_us_liquidity()
    assert out["us_liq_net"].obs_date == date(2026, 9, 30)
    assert out["us_liq_net"].obs_date.month != 10
