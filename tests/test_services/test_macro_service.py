"""宏观参考因子服务单元测试：友好度映射、权重归一、指数合成。"""

import pytest

from app.schemas.common import DirectionSignal
from app.services.macro import MACRO_FACTOR_RULES, MacroFactorService, _friendly_score

_RULES = {r["key"]: r for r in MACRO_FACTOR_RULES}


def test_weights_sum_to_one() -> None:
    """宏观因子权重必须归一。"""
    assert sum(r["weight"] for r in MACRO_FACTOR_RULES) == pytest.approx(1.0)


def test_negative_correlation_mapping() -> None:
    """负相关因子（美元指数/美债）：值越低越利好黄金。"""
    dxy = _RULES["dxy"]
    assert _friendly_score(95.0, dxy) == 100.0  # best 分位
    assert _friendly_score(105.0, dxy) == 0.0  # worst 分位
    assert _friendly_score(100.0, dxy) == 50.0  # 中枢

    us10y = _RULES["us10y"]
    assert _friendly_score(3.5, us10y) == 100.0
    assert _friendly_score(4.5, us10y) == 0.0


def test_positive_correlation_mapping() -> None:
    """正相关因子（VIX/央行购金）：值越高越利好黄金。"""
    cb = _RULES["cb_gold"]
    assert _friendly_score(1200.0, cb) == 100.0
    assert _friendly_score(500.0, cb) == 0.0
    assert _friendly_score(850.0, cb) == 50.0

    vix = _RULES["vix"]
    assert _friendly_score(25.0, vix) == 100.0
    assert _friendly_score(12.0, vix) == 0.0


async def test_macro_evaluate(monkeypatch) -> None:
    """指数合成：5 因子、分数与方向、贡献求和（绕过 TTL 缓存直接测合成逻辑）。"""
    async def fake_collect(self):
        return {
            "dxy": (96.5, "2026-08-28", "静态参考值"),
            "us10y": (4.4, "2026-08-28", "静态参考值"),
            "us30y": (4.9, "2026-08-28", "静态参考值"),
            "vix": (18.5, "2026-08-28", "静态参考值"),
            "cb_gold": (1019.0, "2025Q3–2026Q2 滚动12月", "WGC GDT Q2 2026"),
        }

    monkeypatch.setattr(MacroFactorService, "_collect", fake_collect)
    out = await MacroFactorService()._evaluate_uncached()

    assert len(out.factors) == 5
    assert 0 <= out.score <= 100
    assert out.direction in (DirectionSignal.BULLISH, DirectionSignal.BEARISH, DirectionSignal.NEUTRAL)
    assert sum(f.contribution for f in out.factors) == pytest.approx(out.score, abs=0.5)
    assert all(0 <= f.score <= 100 for f in out.factors)
    # 美债 4.4% → 友好度 10（偏利空）
    us10y = next(f for f in out.factors if f.key == "us10y")
    assert us10y.direction == DirectionSignal.BEARISH
    assert us10y.score == pytest.approx(10.0, abs=0.1)
    # 数据源标识被透传到输出
    assert us10y.source == "静态参考值"
    # 央行购金 T12M=1019 → 友好度 ~74（BULLISH ≥60）
    cb = next(f for f in out.factors if f.key == "cb_gold")
    assert cb.direction == DirectionSignal.BULLISH
    assert cb.score == pytest.approx(74.1, abs=0.2)
    assert "Q2 2026" in cb.source  # 数据源含 WGC 季度报告标识


async def test_macro_evaluate_cb_gold_uses_central_bank_service(
    monkeypatch, db_session
) -> None:
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
                country_iso="CHN", country_name="中国", quarter=q,
                tonnes_net=t, source="IMF IRFCL", data_date=date(2026, 6, 30),
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
    monkeypatch.setattr(
        "app.repositories.market_data.fetch_us_treasury_h15", fake_ust
    )

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


async def test_macro_evaluate_cb_gold_falls_back_when_no_injection(
    monkeypatch, db_session
) -> None:
    """未注入 CentralBankService 时，cb_gold 回退 STATIC_REF 硬编码值（保证系统永远有值）。"""
    async def fake_ust():
        from app.repositories.market_data import USTYield
        from datetime import date
        return USTYield(us10y=4.4, us30y=4.9, data_date=date(2026, 8, 28))
    monkeypatch.setattr(
        "app.repositories.market_data.fetch_us_treasury_h15", fake_ust
    )

    from app.services.macro import _CACHE
    _CACHE.update(ts=0.0, result=None)

    # 不传 central_bank
    out = await MacroFactorService().evaluate()
    cb = next(f for f in out.factors if f.key == "cb_gold")
    assert cb.value == "1019"  # STATIC_REF 硬编码
    assert cb.source == "世界黄金协会 GDT Q2 2026（季度明细：Q1 56.5 / Q2 288.9）"
