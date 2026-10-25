"""宏观参考因子服务单元测试：友好度映射、权重归一、指数合成。"""

import pytest

from app.schemas.common import DirectionSignal
from app.services.macro import MACRO_FACTOR_RULES, MacroFactorService, _friendly_score

_RULES = {r["key"]: r for r in MACRO_FACTOR_RULES}

#: V0.118.0 的 8 个因子 key
ALL_KEYS = {"dxy", "us2y", "us10y", "us30y", "curve_10y2y", "real10y", "vix", "cb_gold"}
#: 可滚动（参与 252 日滚动分位）的因子 —— cb_gold 是季度合计，显式跳过
ROLLING_KEYS = ALL_KEYS - {"cb_gold"}


@pytest.fixture(autouse=True)
def _stub_macro_sources(monkeypatch):
    """把 4 个外部源全部打桩 —— **任何漏打桩都会让单测真的联网**。

    V0.118.0 起 8 个因子里 7 个来自外部源（H.15 / FRED / Yahoo）。漏打桩的后果：
    CI 无外网 ⇒ 用例挂；本地有外网 ⇒ 用例变慢，且断言随当天行情漂移。
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

    monkeypatch.setattr("app.repositories.market_data.fetch_us_treasury_h15", fake_ust)
    monkeypatch.setattr("app.repositories.macro_sources.fetch_fred_latest", fake_fred)
    monkeypatch.setattr("app.repositories.macro_sources.fetch_yahoo_latest", fake_yahoo)


def test_weights_sum_to_one() -> None:
    """宏观因子权重必须归一。"""
    assert sum(r["weight"] for r in MACRO_FACTOR_RULES) == pytest.approx(1.0)


def test_factor_set_is_eight_keys() -> None:
    """V0.118.0：因子集恰好 8 个，key 集合被锁死（加因子要同步前端 + 权重 schema）。"""
    assert {r["key"] for r in MACRO_FACTOR_RULES} == ALL_KEYS
    assert len(MACRO_FACTOR_RULES) == 8


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


async def test_macro_evaluate(monkeypatch) -> None:
    """指数合成：8 因子、分数与方向、贡献求和（绕过 TTL 缓存直接测合成逻辑）。"""

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
        }

    monkeypatch.setattr(MacroFactorService, "_collect", fake_collect)
    out = await MacroFactorService()._evaluate_uncached()

    assert len(out.factors) == 8
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
