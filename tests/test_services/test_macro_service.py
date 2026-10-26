"""宏观参考因子服务单元测试：友好度映射、权重归一、指数合成。"""

import pytest

from app.schemas.common import DirectionSignal
from app.services.macro import MACRO_FACTOR_RULES, MacroFactorService, _friendly_score

_RULES = {r["key"]: r for r in MACRO_FACTOR_RULES}

#: V0.119.0 的 11 个因子 key
ALL_KEYS = {
    "dxy",
    "us2y",
    "us10y",
    "us30y",
    "curve_10y2y",
    "real10y",
    "vix",
    "cb_gold",
    "us_gov_debt",
    "cn_gov_debt",
    "eu_gov_debt",
}
#: 可滚动（参与 252 日滚动分位）的因子 ——
#: cb_gold 是季度合计；3 个政府债务因子是季度/年度低频序列，
#: 日频落表会把同一个值重复 N 次 ⇒ P10 == P90 ⇒ 阈值退化。全部显式跳过。
ROLLING_KEYS = ALL_KEYS - {"cb_gold", "us_gov_debt", "cn_gov_debt", "eu_gov_debt"}


@pytest.fixture(autouse=True)
def _stub_macro_sources(monkeypatch):
    """把 5 个外部源全部打桩 —— **任何漏打桩都会让单测真的联网**。

    V0.118.0 起 8 个因子里 7 个来自外部源（H.15 / FRED / Yahoo）。漏打桩的后果：
    CI 无外网 ⇒ 用例挂；本地有外网 ⇒ 用例变慢，且断言随当天行情漂移。
    V0.119.0 又加了 2 个源（低频 FRED 序列 / Eurostat）。
    个别测试要改 H.15 的返回值时，在自己用例里再 monkeypatch 一次即可
    （后写的 monkeypatch 覆盖先写的）。
    """
    from datetime import date

    from app.repositories.market_data import USTYield

    async def fake_ust():
        return USTYield(us2y=4.05, us10y=4.05, us30y=4.88, data_date=date(2026, 10, 21))

    async def fake_fred(series_id, **kwargs):
        return None  # 取不到 → 回退静态参考值

    async def fake_yahoo(symbol, **kwargs):
        return None

    async def fake_fred_periodic(series_id, **kwargs):
        return None  # 低频序列（季度/年度）取不到 → 回退静态参考值

    async def fake_eurostat(**kwargs):
        return None

    monkeypatch.setattr("app.repositories.market_data.fetch_us_treasury_h15", fake_ust)
    monkeypatch.setattr("app.repositories.macro_sources.fetch_fred_latest", fake_fred)
    monkeypatch.setattr("app.repositories.macro_sources.fetch_yahoo_latest", fake_yahoo)
    monkeypatch.setattr(
        "app.repositories.macro_sources.fetch_fred_periodic_latest", fake_fred_periodic
    )
    monkeypatch.setattr("app.repositories.macro_sources.fetch_eurostat_gov_debt", fake_eurostat)


def test_weights_sum_to_one() -> None:
    """宏观因子权重必须归一。"""
    assert sum(r["weight"] for r in MACRO_FACTOR_RULES) == pytest.approx(1.0)


def test_factor_set_is_eleven_keys() -> None:
    """V0.119.0：因子集恰好 11 个，key 集合被锁死（加因子要同步前端 + 权重 schema）。"""
    assert {r["key"] for r in MACRO_FACTOR_RULES} == ALL_KEYS
    assert len(MACRO_FACTOR_RULES) == 11


def test_negative_correlation_mapping() -> None:
    """负相关因子（美元指数/美债）：值越低越利好黄金。"""
    dxy = _RULES["dxy"]
    assert _friendly_score(94.0, dxy) == 100.0  # best 分位
    assert _friendly_score(107.0, dxy) == 0.0  # worst 分位
    assert _friendly_score(100.5, dxy) == 50.0  # 中枢

    us10y = _RULES["us10y"]
    assert _friendly_score(3.8, us10y) == 100.0
    assert _friendly_score(5.4, us10y) == 0.0


def test_positive_correlation_mapping() -> None:
    """正相关因子（VIX/央行购金）：值越高越利好黄金。"""
    cb = _RULES["cb_gold"]
    assert _friendly_score(1200.0, cb) == 100.0
    assert _friendly_score(500.0, cb) == 0.0
    assert _friendly_score(850.0, cb) == 50.0

    vix = _RULES["vix"]
    assert _friendly_score(30.0, vix) == 100.0
    assert _friendly_score(13.0, vix) == 0.0


def test_new_factors_friendly_score() -> None:
    """V0.118.0 新增 3 因子：2Y 负相关、实际利率负相关、利差负相关（倒挂利多）。"""
    us2y = _RULES["us2y"]
    assert _friendly_score(3.0, us2y) == 100.0
    assert _friendly_score(5.0, us2y) == 0.0

    real10y = _RULES["real10y"]
    assert _friendly_score(0.8, real10y) == 100.0
    assert _friendly_score(3.2, real10y) == 0.0

    # 利差：倒挂（-0.5）= 100 分，陡峭（1.5）= 0 分
    curve = _RULES["curve_10y2y"]
    assert _friendly_score(-0.5, curve) == 100.0
    assert _friendly_score(1.5, curve) == 0.0
    assert _friendly_score(0.5, curve) == 50.0


def test_gov_debt_friendly_score_is_debasement_direction() -> None:
    """V0.119.0 新增 3 个政府债务因子：债务↑ = 利多黄金（debasement 口径）。

    符号由 ``best`` / ``worst`` 的相对位置决定，**不靠 positive 字段** ——
    ``positive`` 只驱动滚动分位的方向。
    """
    us = _RULES["us_gov_debt"]
    assert _friendly_score(140.0, us) == 100.0  # best
    assert _friendly_score(60.0, us) == 0.0  # worst
    assert _friendly_score(100.0, us) == 50.0  # 中枢
    assert _friendly_score(122.59, us) == pytest.approx(78.2375, abs=1e-3)

    cn = _RULES["cn_gov_debt"]
    assert _friendly_score(95.0, cn) == 100.0
    assert _friendly_score(40.0, cn) == 0.0
    assert _friendly_score(88.33, cn) == pytest.approx(87.8727, abs=1e-2)

    eu = _RULES["eu_gov_debt"]
    assert _friendly_score(95.0, eu) == 100.0
    assert _friendly_score(60.0, eu) == 0.0
    assert _friendly_score(82.9, eu) == pytest.approx(65.4286, abs=1e-2)


def test_gov_debt_cadence_and_lag_limits() -> None:
    """低频因子必须声明 cadence / max_lag_days，否则前端会永久亮滞后红灯。

    日频因子滞后 4 天就该告警；季度/年度因子 4 天必红 ⇒ 前端改挂中性 chip。
    """
    assert _RULES["us_gov_debt"]["cadence"] == "quarterly"
    assert _RULES["us_gov_debt"]["max_lag_days"] == 300
    assert _RULES["eu_gov_debt"]["cadence"] == "quarterly"
    assert _RULES["eu_gov_debt"]["max_lag_days"] == 300
    assert _RULES["cn_gov_debt"]["cadence"] == "annual"
    assert _RULES["cn_gov_debt"]["max_lag_days"] == 1100

    # 存量 8 个因子保持日频口径
    for key in ("dxy", "us2y", "us10y", "us30y", "curve_10y2y", "real10y", "vix"):
        assert _RULES[key]["cadence"] == "daily", key
        assert _RULES[key]["max_lag_days"] == 4, key


def test_gov_debt_lag_threshold_covers_current_observation_age() -> None:
    """滞后阈值必须**大于**当前真实观测年龄，否则那一行会**永久亮红灯**。

    「常亮的告警等于没有告警」（freshness 降级 UX 纪律）。

    2026-10-26 实测：
      us 209 天（季度，阈值 300）
      cn 664 天（年度，阈值 1100 —— WEO 年度序列的观测年本身落后 1~2 年）
      eu 118 天（季度，阈值 300）

    ⚠ 参考日固定为发版日：这个断言锁的是**设计决定**（阈值要留多少余量），
    不是「数据永远不���」。源刷新后（观测年推进）阈值应重新评估。
    """
    from datetime import date

    from app.services.macro import STATIC_REF

    ref = date(2026, 10, 26)
    for key in ("us_gov_debt", "cn_gov_debt", "eu_gov_debt"):
        obs = date.fromisoformat(STATIC_REF[key]["date"])
        age = (ref - obs).days
        limit = _RULES[key]["max_lag_days"]
        assert age < limit, f"{key} 观测已 {age} 天，超过阈值 {limit} 天 ⇒ 会永久亮红灯"


def test_gov_debt_excluded_from_rolling_factors() -> None:
    """3 个低频因子 + cb_gold 必须排除在滚动分位之外（否则 P10 == P90 退化）。"""
    from app.services.macro import SKIP_ROLLING_FACTORS

    assert "us_gov_debt" in SKIP_ROLLING_FACTORS
    assert "cn_gov_debt" in SKIP_ROLLING_FACTORS
    assert "eu_gov_debt" in SKIP_ROLLING_FACTORS
    assert "cb_gold" in SKIP_ROLLING_FACTORS


async def test_macro_evaluate(monkeypatch) -> None:
    """指数合成：11 因子、分数与方向、贡献求和（绕过 TTL 缓存直接测合成逻辑）。"""

    async def fake_collect(self):
        return {
            "dxy": (96.5, "2026-08-28", "静态参考值"),
            "us2y": (4.05, "2026-08-28", "静态参考值"),
            "us10y": (4.4, "2026-08-28", "静态参考值"),
            "us30y": (4.9, "2026-08-28", "静态参考值"),
            "curve_10y2y": (0.35, "2026-08-28", "派生 10Y-2Y"),
            "real10y": (2.4, "2026-08-28", "静态参考值"),
            "vix": (18.5, "2026-08-28", "静态参考值"),
            "cb_gold": (1019.0, "2025Q3–2026Q2 滚动12月", "WGC GDT Q2 2026"),
            "us_gov_debt": (122.59, "2026-03-31", "FRED GFDEGDQ188S"),
            "cn_gov_debt": (88.33, "2024-12-31", "FRED GGGDTACNA188N"),
            "eu_gov_debt": (82.9, "2026-06-30", "Eurostat GOV_10Q_GGDEBT"),
        }

    monkeypatch.setattr(MacroFactorService, "_collect", fake_collect)
    out = await MacroFactorService()._evaluate_uncached()

    assert len(out.factors) == 11
    assert {f.key for f in out.factors} == ALL_KEYS
    assert 0 <= out.score <= 100
    assert out.direction in (
        DirectionSignal.BULLISH,
        DirectionSignal.BEARISH,
        DirectionSignal.NEUTRAL,
    )
    assert sum(f.contribution for f in out.factors) == pytest.approx(out.score, abs=0.5)
    assert all(0 <= f.score <= 100 for f in out.factors)
    # 美债 4.4% → 友好度 (4.4-5.4)/(3.8-5.4)*100 = 62.5
    us10y = next(f for f in out.factors if f.key == "us10y")
    assert us10y.direction == DirectionSignal.BULLISH
    assert us10y.score == pytest.approx(62.5, abs=0.1)
    # 数据源标识被透传到输出
    assert us10y.source == "静态参考值"
    # 央行购金 T12M=1019 → 友好度 ~74（BULLISH ≥60）
    cb = next(f for f in out.factors if f.key == "cb_gold")
    assert cb.direction == DirectionSignal.BULLISH
    assert cb.score == pytest.approx(74.1, abs=0.2)
    assert "Q2 2026" in cb.source  # 数据源含 WGC 季度报告标识
    # 贡献之和 = 指数分（权重已归一化到 1.0）
    assert sum(f.weight for f in out.factors) == pytest.approx(1.0, abs=1e-6)

    # V0.119.0：低频因子把 cadence / max_lag_days 透出（前端据此不亮滞后红灯）
    us_debt = next(f for f in out.factors if f.key == "us_gov_debt")
    assert us_debt.cadence == "quarterly"
    assert us_debt.max_lag_days == 300
    assert us_debt.source == "FRED GFDEGDQ188S"
    assert us_debt.data_date == "2026-03-31"
    cn_debt = next(f for f in out.factors if f.key == "cn_gov_debt")
    assert cn_debt.cadence == "annual"
    # 1100 天 ≈ 3 年。**不是 550 天** —— FRED 的 IMF WEO 年度序列最新观测是
    # 2024-12-31（664 天前，年度序列本身落后日历 1~2 年），
    # 拿 550 天当阈值会让这一行永远亮红灯（常亮的告警等于没有告警）。
    assert cn_debt.max_lag_days == 1100

    # V0.119.0：rolling_factors 是后端算出的可滚动清单（前端不再硬编码 filter）
    assert set(out.rolling_factors) == ROLLING_KEYS
    assert len(out.rolling_factors) == 7


async def test_macro_evaluate_cb_gold_uses_central_bank_service(monkeypatch, db_session) -> None:
    """注入 CentralBankService 后，cb_gold 从 central_bank_purchases 表自动计算（不依赖 STATIC_REF）。"""
    from datetime import date

    from app.models.central_bank import CentralBankPurchase
    from app.repositories.central_bank import CentralBankPurchaseRepository
    from app.services.central_bank import CentralBankService

    # 种 4 个季度数据（T12M = 280+290+250+290 = 1110，落在 cb_gold 友好区间）
    for q, t in [
        ("2025Q3", 280.0),
        ("2025Q4", 290.0),
        ("2026Q1", 250.0),
        ("2026Q2", 290.0),
    ]:
        db_session.add(
            CentralBankPurchase(
                country_iso="CHN",
                country_name="中国",
                quarter=q,
                tonnes_net=t,
                source="IMF IRFCL",
                data_date=date(2026, 6, 30),
            )
        )
    await db_session.commit()

    # 真实调用 _collect（不 monkeypatch），传入 central_bank
    cb_service = CentralBankService(CentralBankPurchaseRepository(db_session))
    svc = MacroFactorService(central_bank=cb_service)

    # 避免真实抓 H.15：monkeypatch 美债拉取
    async def fake_ust():
        from app.repositories.market_data import USTYield

        return USTYield(us10y=4.4, us30y=4.9, data_date=date(2026, 8, 28))

    monkeypatch.setattr("app.repositories.market_data.fetch_us_treasury_h15", fake_ust)

    # 绕过 10min TTL 缓存
    from app.services.macro import _CACHE

    _CACHE.update(ts=0.0, result=None)

    out = await svc.evaluate()
    cb = next(f for f in out.factors if f.key == "cb_gold")
    # cb_gold 来自表：value="1110"（g格式字符串）, date="2025Q3–2026Q2"
    assert cb.value == "1110"
    assert cb.data_date == "2025Q3–2026Q2"
    assert cb.source == "央行购金表自动汇总"
    assert cb.direction == DirectionSignal.BULLISH


async def test_macro_evaluate_cb_gold_falls_back_when_no_injection(monkeypatch, db_session) -> None:
    """未注入 CentralBankService 时，cb_gold 回退 STATIC_REF 硬编码值（保证系统永远有值）。"""

    async def fake_ust():
        from datetime import date

        from app.repositories.market_data import USTYield

        return USTYield(us10y=4.4, us30y=4.9, data_date=date(2026, 8, 28))

    monkeypatch.setattr("app.repositories.market_data.fetch_us_treasury_h15", fake_ust)

    from app.services.macro import _CACHE

    _CACHE.update(ts=0.0, result=None)

    # 不传 central_bank
    out = await MacroFactorService().evaluate()
    cb = next(f for f in out.factors if f.key == "cb_gold")
    assert cb.value == "1019"  # STATIC_REF 硬编码
    assert cb.source == "世界黄金协会 GDT Q2 2026（季度明细：Q1 56.5 / Q2 288.9）"


# ───────────────────── V0.110.0 · 宏观因子手动校准 ─────────────────────


def _override_service(**overrides):
    """构造一个只提供 macro_overrides() 的假 WeightService。"""
    from app.schemas.settings import MacroFactorOverrideSet
    from app.services.settings import WeightService

    cfg = MacroFactorOverrideSet(**overrides)

    class _Fake(WeightService):
        def __init__(self) -> None:
            pass

        async def macro_overrides(self):
            return cfg

        async def macro_weights(self):
            return {}  # 空 dict → _evaluate_uncached 回退 MACRO_FACTOR_RULES 内置权重

    return _Fake()


async def _collect_with(monkeypatch, fake_settings, *, us_ten_ok: bool = True) -> dict:
    """跑一次 _collect（绕过 10min TTL 缓存），返回各因子三元组。"""
    from datetime import date

    from app.repositories.market_data import USTYield

    async def fake_ust():
        if not us_ten_ok:
            raise RuntimeError("H.15 unreachable")
        return USTYield(us10y=4.05, us30y=4.88, data_date=date(2026, 10, 21))

    monkeypatch.setattr("app.repositories.market_data.fetch_us_treasury_h15", fake_ust)
    svc = MacroFactorService(settings=fake_settings)
    return await svc._collect()


async def test_v01100_manual_override_beats_static_ref(monkeypatch) -> None:
    """dxy / vix 无自动源，覆盖值必须压过 STATIC_REF 的 2026-08-28 常量。"""
    from app.schemas.settings import MacroFactorOverride

    fake = _override_service(
        dxy=MacroFactorOverride(value=97.42, as_of="2026-10-21", note="Wind"),
        vix=MacroFactorOverride(value=16.8, as_of="2026-10-21", note=None),
    )
    values = await _collect_with(monkeypatch, fake)

    assert values["dxy"] == (97.42, "2026-10-21", "手动输入")
    assert values["vix"] == (16.8, "2026-10-21", "手动输入")


async def test_v01100_manual_override_beats_live_h15(monkeypatch) -> None:
    """覆盖优先级高于自动源：H.15 拉到 4.05，但用户填了 3.90 就用 3.90。"""
    from app.schemas.settings import MacroFactorOverride

    fake = _override_service(us10y=MacroFactorOverride(value=3.90, as_of="2026-10-21"))
    values = await _collect_with(monkeypatch, fake)

    assert values["us10y"] == (3.90, "2026-10-21", "手动输入")
    # 未覆盖的 us30y 仍走 H.15 自动源
    assert values["us30y"][2] == "美联储 H.15"


async def test_v01100_partial_override_keeps_auto_for_others(monkeypatch) -> None:
    """只覆盖 dxy 时，其余 4 个因子不受影响（各自照常走自动源 / 静态参考）。"""
    from app.schemas.settings import MacroFactorOverride

    fake = _override_service(dxy=MacroFactorOverride(value=97.42, as_of="2026-10-21"))
    values = await _collect_with(monkeypatch, fake)

    assert values["dxy"][2] == "手动输入"
    assert values["vix"] == (18.5, "2026-08-28", "静态参考值")
    assert values["cb_gold"][0] == 1019.0


async def test_v01100_empty_override_set_changes_nothing(monkeypatch) -> None:
    """空覆盖集 = 完全不干预（回归保护：默认路径行为不变）。"""
    values = await _collect_with(monkeypatch, _override_service())
    assert values["dxy"] == (96.5, "2026-08-28", "静态参考值")


async def test_v01100_override_survives_h15_failure(monkeypatch) -> None:
    """H.15 挂掉时手动值仍生效（覆盖不依赖任何自动源可用性）。"""
    from app.schemas.settings import MacroFactorOverride

    fake = _override_service(us10y=MacroFactorOverride(value=3.90, as_of="2026-10-21"))
    values = await _collect_with(monkeypatch, fake, us_ten_ok=False)

    assert values["us10y"] == (3.90, "2026-10-21", "手动输入")
    assert values["us30y"][2] == "静态参考值"  # 未覆盖的仍回退静态


async def test_v01100_override_read_failure_does_not_break_macro(monkeypatch) -> None:
    """读覆盖抛异常时回落自动源，不能让整个宏观面 500。"""
    from app.services.settings import WeightService

    class _Boom(WeightService):
        def __init__(self) -> None:
            pass

        async def macro_overrides(self):
            raise RuntimeError("db down")

    values = await _collect_with(monkeypatch, _Boom())
    assert values["dxy"] == (96.5, "2026-08-28", "静态参考值")


async def test_v01100_override_propagates_into_index(monkeypatch) -> None:
    """端到端：覆盖 dxy 后 MacroIndexOut 的因子值与来源都变成手动值。"""
    from app.schemas.settings import MacroFactorOverride
    from app.services.macro import _CACHE

    monkeypatch.setattr(
        "app.repositories.market_data.fetch_us_treasury_h15",
        lambda: _noop_ust(),
    )
    _CACHE.update(ts=0.0, result=None)

    fake = _override_service(dxy=MacroFactorOverride(value=105.0, as_of="2026-10-21"))
    out = await MacroFactorService(settings=fake).evaluate()

    dxy = next(f for f in out.factors if f.key == "dxy")
    assert dxy.value == "105"
    assert dxy.source == "手动输入"
    assert dxy.data_date == "2026-10-21"
    assert dxy.score == pytest.approx(
        15.4, abs=0.1
    )  # V0.118.0：worst 分位 107 → (105-107)/(94-107)*100
    from app.services.macro import clear_macro_cache

    clear_macro_cache()


async def _noop_ust():
    from datetime import date

    from app.repositories.market_data import USTYield

    return USTYield(us10y=4.05, us30y=4.88, data_date=date(2026, 10, 21))


# ───────────────────── V0.118.0 · 8 因子 + 实时源 + 派生利差 ─────────────────────


async def test_curve_derived_from_10y_minus_2y(monkeypatch) -> None:
    """利差是**派生**因子：10Y − 2Y，来源标「派生 10Y-2Y」，数据日期取两个输入的较早者。"""
    from datetime import date

    from app.repositories.market_data import USTYield

    async def fake_ust():
        return USTYield(us2y=4.05, us10y=4.35, us30y=4.88, data_date=date(2026, 10, 21))

    monkeypatch.setattr("app.repositories.market_data.fetch_us_treasury_h15", fake_ust)
    values = await MacroFactorService()._collect()

    val, data_date, source = values["curve_10y2y"]
    assert val == pytest.approx(0.30)
    assert source == "派生 10Y-2Y"
    assert data_date == "2026-10-21"


async def test_curve_falls_back_to_static_when_input_is_static(monkeypatch) -> None:
    """输入是静态兜底时，派生利差也必须标成静态 —— 否则假值会写进历史表。"""
    from app.repositories.market_data import USTYield

    async def fake_ust():
        from datetime import date

        return USTYield(us10y=4.35, us30y=4.88, data_date=date(2026, 10, 21))  # 无 us2y

    monkeypatch.setattr("app.repositories.market_data.fetch_us_treasury_h15", fake_ust)
    values = await MacroFactorService()._collect()

    assert values["curve_10y2y"][2].startswith("静态")
    from app.services.macro import is_persistable_source

    assert is_persistable_source(values["curve_10y2y"][2]) is False


async def test_manual_override_of_2y_propagates_to_curve(monkeypatch) -> None:
    """手动覆盖 2Y（不覆盖利差）⇒ 利差跟着一起变（口径自洽）。"""
    from app.schemas.settings import MacroFactorOverride

    fake = _override_service(us2y=MacroFactorOverride(value=3.50, as_of="2026-10-21"))
    values = await _collect_with(monkeypatch, fake)

    # H.15 给 us10y=4.05（见 _collect_with），手动 us2y=3.50 ⇒ 利差 0.55
    assert values["curve_10y2y"][0] == pytest.approx(0.55)
    assert values["curve_10y2y"][2] == "派生 10Y-2Y"


async def test_manual_override_of_curve_wins_over_derivation(monkeypatch) -> None:
    """手动覆盖利差时，派生逻辑必须让位（覆盖 > 一切）。"""
    from app.schemas.settings import MacroFactorOverride

    fake = _override_service(curve_10y2y=MacroFactorOverride(value=-0.20, as_of="2026-10-21"))
    values = await _collect_with(monkeypatch, fake)

    assert values["curve_10y2y"] == (-0.20, "2026-10-21", "手动输入")


async def test_live_fred_and_yahoo_sources_are_used(monkeypatch) -> None:
    """V0.118.0：dxy 走 Yahoo、vix/real10y 走 FRED（不再停在 2026-08-28 常量）。"""
    from datetime import date

    async def fake_fred(series_id, **kwargs):
        return {"VIXCLS": (19.03, date(2026, 10, 22)), "DFII10": (2.64, date(2026, 10, 22))}[
            series_id
        ]

    async def fake_yahoo(symbol, **kwargs):
        return (101.81, date(2026, 10, 23))

    monkeypatch.setattr("app.repositories.macro_sources.fetch_fred_latest", fake_fred)
    monkeypatch.setattr("app.repositories.macro_sources.fetch_yahoo_latest", fake_yahoo)
    values = await MacroFactorService()._collect()

    assert values["dxy"] == (101.81, "2026-10-23", "Yahoo DX-Y.NYB")
    assert values["vix"] == (19.03, "2026-10-22", "FRED VIXCLS")
    assert values["real10y"] == (2.64, "2026-10-22", "FRED DFII10")


def test_static_sources_are_not_persistable() -> None:
    """静态兜底值**不得**写进历史表 —— 一次上游故障就能把滚动分位带偏。"""
    from app.services.macro import STATIC_SOURCE_PREFIX, is_persistable_source

    assert is_persistable_source("静态参考值") is False
    assert is_persistable_source(STATIC_SOURCE_PREFIX + "参考值") is False
    assert is_persistable_source("美联储 H.15") is True
    assert is_persistable_source("FRED VIXCLS") is True
    assert is_persistable_source("Yahoo DX-Y.NYB") is True
    assert is_persistable_source("派生 10Y-2Y") is True
    assert is_persistable_source("手动输入") is True


# ───────────────────── V0.118.1 · 末次落库兜底层 ─────────────────────
#
# 背景：V0.118.0 给 8 个因子都接上了自动实时源，但兜底层仍是 ``STATIC_REF`` 里
# 2026-08-28 的内置常量（dxy 96.5 / vix 18.5）。上游源一挂（DNS 故障 / 限流），
# 宏观面就静默退回两个半月前的常量 —— 而历史表里明明存着前几轮抓到的真值
# （dxy 101.81）。用户在「宏观因子手动校准」页看到的「当前生效」列因此停在
# 2026-08-28，且与真实市场差 5 个点，**且没有任何降级提示**。
#
# V0.118.1 在自动源与常量之间插入「上次成功落库的真实读数」这一层。


class _FakeHistoryRepo:
    """``MacroFactorHistoryRepository.get_latest_per_factor`` 的最小替身。"""

    def __init__(self, rows: dict) -> None:
        self._rows = rows
        self.calls = 0

    async def get_latest_per_factor(self, target: str = "default") -> dict:
        self.calls += 1
        return self._rows


class _Row:
    """``DailyMacroFactor`` 的最小替身（只带 service 用到的三个字段）。"""

    def __init__(self, value: float, data_date: str, source: str) -> None:
        self.factor_key = ""
        self.value = value
        self.data_date = data_date
        self.source = source


def _lkg_rows(**kwargs) -> dict:
    """构造历史行：``_lkg_rows(dxy=(101.81, "2026-10-23", "Yahoo DX-Y.NYB"))``。"""
    out = {}
    for key, (value, data_date, source) in kwargs.items():
        row = _Row(value, data_date, source)
        row.factor_key = key
        out[key] = row
    return out


async def test_v01181_source_failure_uses_last_stored_reading(monkeypatch) -> None:
    """上游源全挂 → 用「上次成功落库的真实读数」，**不是** 2026-08-28 的常量。"""

    async def fake_ust():
        raise RuntimeError("H.15 unreachable")

    async def fake_fred(series_id, **kwargs):
        raise RuntimeError("FRED unreachable")

    async def fake_yahoo(symbol, **kwargs):
        raise RuntimeError("Yahoo unreachable")

    monkeypatch.setattr("app.repositories.market_data.fetch_us_treasury_h15", fake_ust)
    monkeypatch.setattr("app.repositories.macro_sources.fetch_fred_latest", fake_fred)
    monkeypatch.setattr("app.repositories.macro_sources.fetch_yahoo_latest", fake_yahoo)

    repo = _FakeHistoryRepo(
        _lkg_rows(
            dxy=(101.81, "2026-10-23", "Yahoo DX-Y.NYB"),
            vix=(19.03, "2026-10-22", "FRED VIXCLS"),
            us2y=(4.65, "2026-10-22", "美联储 H.15"),
            us10y=(4.96, "2026-10-22", "美联储 H.15"),
            us30y=(5.29, "2026-10-22", "美联储 H.15"),
            real10y=(2.64, "2026-10-22", "FRED DFII10"),
        )
    )
    svc = MacroFactorService(history_repo=repo)
    values = await svc._collect()

    # 关键：dxy 是 101.81（真值），不是 96.5（08-28 的常量）
    assert values["dxy"][0] == pytest.approx(101.81)
    assert values["dxy"][1] == "2026-10-23"
    assert values["vix"][0] == pytest.approx(19.03)
    assert values["us10y"][0] == pytest.approx(4.96)
    assert values["real10y"][0] == pytest.approx(2.64)
    # 降级必须可辨认：source 带「末次落库」前缀
    assert values["dxy"][2].startswith("末次落库")
    assert "Yahoo DX-Y.NYB" in values["dxy"][2]


async def test_v01181_live_source_beats_last_stored(monkeypatch) -> None:
    """自动源可用时优先用自动源（末次落库只是兜底层）。"""
    from datetime import date

    from app.repositories.market_data import USTYield

    async def fake_ust():
        return USTYield(us2y=4.05, us10y=4.35, us30y=4.88, data_date=date(2026, 10, 21))

    async def fake_fred(series_id, **kwargs):
        return {"VIXCLS": (19.03, date(2026, 10, 22))}[series_id]

    async def fake_yahoo(symbol, **kwargs):
        return (101.81, date(2026, 10, 23))

    monkeypatch.setattr("app.repositories.market_data.fetch_us_treasury_h15", fake_ust)
    monkeypatch.setattr("app.repositories.macro_sources.fetch_fred_latest", fake_fred)
    monkeypatch.setattr("app.repositories.macro_sources.fetch_yahoo_latest", fake_yahoo)

    repo = _FakeHistoryRepo(
        _lkg_rows(
            dxy=(99.0, "2026-10-01", "Yahoo DX-Y.NYB"),
            vix=(17.0, "2026-10-01", "FRED VIXCLS"),
            us2y=(4.00, "2026-10-01", "美联储 H.15"),
            us10y=(4.20, "2026-10-01", "美联储 H.15"),
        )
    )
    values = await MacroFactorService(history_repo=repo)._collect()

    assert values["dxy"][0] == pytest.approx(101.81)
    assert values["dxy"][2] == "Yahoo DX-Y.NYB"  # 不是末次落库
    assert values["vix"][0] == pytest.approx(19.03)
    assert values["us10y"][0] == pytest.approx(4.35)
    assert values["us10y"][2] == "美联储 H.15"


async def test_v01181_manual_override_still_beats_last_stored(monkeypatch) -> None:
    """手动覆盖仍然压过末次落库（手动 > 自动源 > 末次落库 > 常量）。"""
    from app.schemas.settings import MacroFactorOverride

    async def fake_ust():
        raise RuntimeError("H.15 unreachable")

    monkeypatch.setattr("app.repositories.market_data.fetch_us_treasury_h15", fake_ust)

    repo = _FakeHistoryRepo(_lkg_rows(dxy=(101.81, "2026-10-23", "Yahoo DX-Y.NYB")))
    fake = _override_service(dxy=MacroFactorOverride(value=97.42, as_of="2026-10-21"))
    svc = MacroFactorService(settings=fake, history_repo=repo)
    values = await svc._collect()

    assert values["dxy"] == (97.42, "2026-10-21", "手动输入")


async def test_v01181_no_history_falls_back_to_static_ref(monkeypatch) -> None:
    """历史表为空（全新部署）→ 仍走内置常量，不报错。"""

    async def fake_ust():
        raise RuntimeError("H.15 unreachable")

    monkeypatch.setattr("app.repositories.market_data.fetch_us_treasury_h15", fake_ust)

    values = await MacroFactorService(history_repo=_FakeHistoryRepo({}))._collect()
    assert values["dxy"] == (96.5, "2026-08-28", "静态参考值")


async def test_v01181_history_read_failure_does_not_break_macro(monkeypatch) -> None:
    """读历史表抛异常 → 回落常量，宏观面不能整体 500。"""

    class _Boom:
        async def get_latest_per_factor(self, target: str = "default") -> dict:
            raise RuntimeError("db down")

    async def fake_ust():
        raise RuntimeError("H.15 unreachable")

    monkeypatch.setattr("app.repositories.market_data.fetch_us_treasury_h15", fake_ust)

    values = await MacroFactorService(history_repo=_Boom())._collect()
    assert values["dxy"] == (96.5, "2026-08-28", "静态参考值")


async def test_v01181_curve_derived_from_lkg_inputs_is_marked_degraded(monkeypatch) -> None:
    """末次落库时派生的利差：source 带「末次落库」前缀（混了日期，不算干净观测）。"""

    async def fake_ust():
        raise RuntimeError("H.15 unreachable")

    monkeypatch.setattr("app.repositories.market_data.fetch_us_treasury_h15", fake_ust)

    repo = _FakeHistoryRepo(
        _lkg_rows(
            us2y=(4.65, "2026-10-22", "美联储 H.15"),
            us10y=(4.96, "2026-10-22", "美联储 H.15"),
        )
    )
    values = await MacroFactorService(history_repo=repo)._collect()

    val, data_date, source = values["curve_10y2y"]
    assert val == pytest.approx(0.31)
    assert data_date == "2026-10-22"
    assert source.startswith("末次落库")


def test_v01181_last_known_good_is_not_persistable() -> None:
    """末次落库值**不得**再落进历史表 —— 旧读数不能被记成今天的观测。"""
    from app.services.macro import (
        LAST_KNOWN_GOOD_PREFIX,
        is_persistable_source,
    )

    lkg = LAST_KNOWN_GOOD_PREFIX + "·FRED VIXCLS"
    assert is_persistable_source(lkg) is False
    assert is_persistable_source(LAST_KNOWN_GOOD_PREFIX + "·派生 10Y-2Y") is False
    # 真实自动源仍然可落表
    assert is_persistable_source("FRED VIXCLS") is True


def test_v01181_source_tier_classification() -> None:
    """source → 层级：live / lkg / static。"""
    from app.services.macro import (
        LAST_KNOWN_GOOD_PREFIX,
        STATIC_SOURCE_PREFIX,
        source_tier,
    )

    assert source_tier("FRED VIXCLS") == "live"
    assert source_tier("手动输入") == "live"
    assert source_tier(LAST_KNOWN_GOOD_PREFIX + "·FRED VIXCLS") == "lkg"
    assert source_tier(STATIC_SOURCE_PREFIX + "参考值") == "static"
