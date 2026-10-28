"""权重配置服务单元测试：默认值、保存读取、分组权重。"""

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.settings import SettingRepository
from app.schemas.settings import MacroWeightConfig, WeightConfig
from app.services.settings import WEIGHTS_KEY, WeightService, clear_weights_cache


def _service(session: AsyncSession) -> WeightService:
    return WeightService(SettingRepository(session))


async def test_default_weights(db_session: AsyncSession) -> None:
    """未配置时返回内置默认权重。"""
    svc = _service(db_session)
    w = await svc.get_weights()

    assert w.trend.structure == 0.30
    assert w.trend.momentum == 0.20
    # V0.119.0：宏观面 8 因子 → 11 因子，旧 8 个 ×0.88 缩放 + 政府债务组 12%
    assert w.macro.dxy == 0.13
    assert w.macro.us2y == 0.05
    assert w.macro.us10y == 0.07
    assert w.macro.us30y == 0.05
    assert w.macro.curve_10y2y == 0.09
    assert w.macro.real10y == 0.18
    assert w.macro.vix == 0.09
    assert w.macro.cb_gold == 0.22
    assert w.macro.us_gov_debt == 0.05
    assert w.macro.cn_gov_debt == 0.04
    assert w.macro.eu_gov_debt == 0.03
    # V0.120.0：四面临界 30/40/30 → 25/35/25/15（新增资金流面 15%）
    assert w.combine.tech == 0.25
    assert w.combine.macro == 0.35
    assert w.combine.news == 0.25
    assert w.combine.flow == 0.15


async def test_save_and_read(db_session: AsyncSession) -> None:
    """保存后重新读取返回用户配置。"""
    svc = _service(db_session)
    custom = WeightConfig(
        trend={
            "structure": 0.40,
            "momentum": 0.20,
            "support": 0.20,
            "momentum_rsi": 0.10,
            "drawdown": 0.10,
        },
        macro={
            "dxy": 0.30,
            "us2y": 0.05,
            "us10y": 0.08,
            "us30y": 0.07,
            "curve_10y2y": 0.10,
            "real10y": 0.15,
            "vix": 0.10,
            "cb_gold": 0.05,
            "us_gov_debt": 0.05,
            "cn_gov_debt": 0.03,
            "eu_gov_debt": 0.02,
        },
        combine={"tech": 0.50, "macro": 0.30, "news": 0.10, "flow": 0.10},
    )
    await svc.save_weights(custom)

    w = await svc.get_weights()
    assert w.trend.structure == 0.40
    assert w.macro.dxy == 0.30
    assert w.combine.tech == 0.50

    # 分组权重接口
    trend = await svc.trend_weights()
    assert trend["结构"] == 0.40
    macro = await svc.macro_weights()
    assert macro["dxy"] == 0.30
    assert await svc.combine_weights() == (0.50, 0.30, 0.10, 0.10)

    # 持久化验证
    raw = await SettingRepository(db_session).get(WEIGHTS_KEY)
    assert raw is not None and "dxy" in raw


async def test_invalid_sum_rejected() -> None:
    """各组权重和不为 1 应校验失败。"""
    with pytest.raises(ValidationError):
        WeightConfig(
            trend={
                "structure": 0.5,
                "momentum": 0.5,
                "support": 0.1,
                "momentum_rsi": 0.1,
                "drawdown": 0.1,
            }
        )


# ───────────────────── V0.79.0 Step F · group_combine 开关 ─────────────────────


async def test_group_combine_default_true(db_session: AsyncSession) -> None:
    """未显式配置时 group_combine 默认 True（推荐方案 2）。"""
    svc = _service(db_session)
    assert await svc.group_combine() is True


async def test_group_combine_save_and_load_roundtrip(db_session: AsyncSession) -> None:
    """保存 group_combine=False → 重新读取保持 False。"""
    svc = _service(db_session)
    custom = WeightConfig(
        trend={
            "structure": 0.30,
            "momentum": 0.20,
            "support": 0.20,
            "momentum_rsi": 0.15,
            "drawdown": 0.15,
        },
        macro={
            "dxy": 0.25,
            "us2y": 0.05,
            "us10y": 0.07,
            "us30y": 0.08,
            "curve_10y2y": 0.10,
            "real10y": 0.20,
            "vix": 0.10,
            "cb_gold": 0.05,
            "us_gov_debt": 0.05,
            "cn_gov_debt": 0.03,
            "eu_gov_debt": 0.02,
        },
        combine={"tech": 0.30, "macro": 0.40, "news": 0.30},
        group_combine=False,  # V0.79.0 Step F：切回历史单维度加权
    )
    await svc.save_weights(custom)

    # 内存立即可见
    assert await svc.group_combine() is False

    # 重新构造 service 模拟冷启动 → 仍然 False
    fresh = _service(db_session)
    assert await fresh.group_combine() is False


async def test_group_combine_legacy_stored_json_without_field_defaults_true(
    db_session: AsyncSession,
) -> None:
    """历史权重 JSON 缺 group_combine 字段 → model_validate 默认 True（向后兼容）。"""
    repo = SettingRepository(db_session)
    # 模拟 V0.79.0 Step F 之前存储的 JSON（无 group_combine）
    legacy_json = (
        '{"trend":{"structure":0.3,"momentum":0.2,"support":0.2,'
        '"momentum_rsi":0.15,"drawdown":0.15},'
        '"macro":{"dxy":0.25,"us10y":0.2,"us30y":0.15,"vix":0.15,"cb_gold":0.25},'
        '"combine":{"tech":0.3,"macro":0.4,"news":0.3}}'
    )
    await repo.set(WEIGHTS_KEY, legacy_json)

    svc = _service(db_session)
    # 历史配置加载后，group_combine 默认为 True（推荐）
    assert await svc.group_combine() is True


# ───────────────────── V0.119.0 · 宏观 8 因子 → 11 因子迁移 ─────────────────────

#: V0.118.0 之前落库的宏观权重 JSON（5 因子，合计 = 1.0）
#: ⚠ 这组值**恰好等于**旧版默认权重 ⇒ 语义是「用户从没自定义过」
LEGACY_MACRO_5 = {"dxy": 0.25, "us10y": 0.2, "us30y": 0.15, "vix": 0.15, "cb_gold": 0.25}

#: 真正的「用户自定义」5 键权重（合计 = 1.0，且不等于旧默认）⇒ 走按比例迁移
CUSTOM_MACRO_5 = {"dxy": 0.30, "us10y": 0.15, "us30y": 0.10, "vix": 0.20, "cb_gold": 0.25}

#: V0.118.0 的 8 因子 key
MACRO_8_KEYS = (
    "dxy",
    "us2y",
    "us10y",
    "us30y",
    "curve_10y2y",
    "real10y",
    "vix",
    "cb_gold",
)

#: V0.119.0 的 11 因子 key
MACRO_11_KEYS = (*MACRO_8_KEYS, "us_gov_debt", "cn_gov_debt", "eu_gov_debt")

#: V0.118.0 的 8 因子默认权重（= 权重页「恢复默认」写进去的那一组）
MACRO_8_DEFAULTS = {
    "dxy": 0.15,
    "us2y": 0.06,
    "us10y": 0.08,
    "us30y": 0.06,
    "curve_10y2y": 0.10,
    "real10y": 0.20,
    "vix": 0.10,
    "cb_gold": 0.25,
}

#: V0.119.0 的 11 因子默认权重（政府债务组占 12%：美 5 / 中 4 / 欧 3）
MACRO_11_DEFAULTS = {
    "dxy": 0.13,
    "us2y": 0.05,
    "us10y": 0.07,
    "us30y": 0.05,
    "curve_10y2y": 0.09,
    "real10y": 0.18,
    "vix": 0.09,
    "cb_gold": 0.22,
    "us_gov_debt": 0.05,
    "cn_gov_debt": 0.04,
    "eu_gov_debt": 0.03,
}


def test_macro_weight_config_legacy_defaults_become_new_defaults() -> None:
    """存量配置**恰好等于旧默认**（= 用户从没自定义过）→ 直接落到 V0.119.0 新默认。

    否则「没动过权重」的用户会拿到按比例缩放出来的
    dxy 16.8% / us10y 8.4% / us30y 5.6% / vix 11.2% / cb_gold 14%
    —— 这组权重谁都没设计过，也和本版的设计（13/7/9/22 + 政府债务 12%）不符。
    """
    cfg = MacroWeightConfig.model_validate(LEGACY_MACRO_5)
    dumped = cfg.model_dump()

    assert set(dumped) == set(MACRO_11_KEYS)
    assert abs(sum(dumped.values()) - 1.0) < 1e-6
    for key, want in MACRO_11_DEFAULTS.items():
        assert dumped[key] == pytest.approx(want, abs=1e-9), key


def test_macro_weight_config_migrates_5_to_11_keys() -> None:
    """5 键**自定义**配置 → 11 键：新增因子取默认值，旧因子按比例缩放，合计仍为 1。

    **不做迁移会怎样**：6 个新字段拿到默认值后合计 = 1.44 → ``_sum_to_one`` 抛错
    → ``_load_weights`` 的异常兜底路径**静默把用户的自定义权重重置为默认**。
    """
    cfg = MacroWeightConfig.model_validate(CUSTOM_MACRO_5)
    dumped = cfg.model_dump()

    assert set(dumped) == set(MACRO_11_KEYS)
    assert abs(sum(dumped.values()) - 1.0) < 1e-6

    # 新增因子取默认值
    assert dumped["us2y"] == pytest.approx(0.05)
    assert dumped["curve_10y2y"] == pytest.approx(0.09)
    assert dumped["real10y"] == pytest.approx(0.18)
    assert dumped["us_gov_debt"] == pytest.approx(0.05)
    assert dumped["cn_gov_debt"] == pytest.approx(0.04)
    assert dumped["eu_gov_debt"] == pytest.approx(0.03)

    # 旧因子的**相对比例**保持不变（合计 1.0 → 扣掉新增份额 0.44 → 缩放系数 0.56）
    scale = 0.56
    for key, old in CUSTOM_MACRO_5.items():
        assert dumped[key] == pytest.approx(old * scale, abs=1e-6), key


def test_macro_weight_config_legacy_8_defaults_become_new_defaults() -> None:
    """V0.119.0 的第二道迁移守卫：8 键**旧默认** → 直落 11 键新默认。

    「旧默认值也是一种用户状态」：存量配置恰好等于 V0.118.0 的默认权重时，
    用户从没自定义过，升级后应直接吃新推荐权重，而不是缩放出来的
    dxy 13.2% / cb_gold 22% —— 后者相对比例对，但绝对值是缩放算出来的。
    """
    cfg = MacroWeightConfig.model_validate(MACRO_8_DEFAULTS)
    dumped = cfg.model_dump()

    assert set(dumped) == set(MACRO_11_KEYS)
    assert abs(sum(dumped.values()) - 1.0) < 1e-6
    for key, want in MACRO_11_DEFAULTS.items():
        assert dumped[key] == pytest.approx(want, abs=1e-9), key
    # 关键：不是缩放值
    assert dumped["dxy"] != pytest.approx(0.132, abs=1e-6)
    assert dumped["cb_gold"] != pytest.approx(0.22 * 0.88, abs=1e-6)


def test_macro_weight_config_migrates_8_to_11_keys() -> None:
    """8 键**自定义**配置 → 11 键：旧 8 个按 ×0.88 缩放（相对比例不变）。

    政府债务组占 12%，所以旧因子的可用份额从 1.0 缩到 0.88。
    """
    custom8 = {
        "dxy": 0.30,
        "us2y": 0.05,
        "us10y": 0.08,
        "us30y": 0.07,
        "curve_10y2y": 0.10,
        "real10y": 0.15,
        "vix": 0.10,
        "cb_gold": 0.15,
    }
    assert abs(sum(custom8.values()) - 1.0) < 1e-6

    cfg = MacroWeightConfig.model_validate(custom8)
    dumped = cfg.model_dump()

    assert set(dumped) == set(MACRO_11_KEYS)
    assert abs(sum(dumped.values()) - 1.0) < 1e-6
    for key, old in custom8.items():
        assert dumped[key] == pytest.approx(old * 0.88, abs=1e-6), key
    assert dumped["us_gov_debt"] == pytest.approx(0.05)
    assert dumped["cn_gov_debt"] == pytest.approx(0.04)
    assert dumped["eu_gov_debt"] == pytest.approx(0.03)


async def test_stored_legacy_5_key_weights_become_new_defaults(
    db_session: AsyncSession,
) -> None:
    """**端到端**：库里存着 5 键**旧默认**权重 → 读出来是 V0.119.0 的新默认。

    「用户从没自定义过」⇒ 升级后应该直接吃新推荐权重，
    而不是吃「旧默认按比例缩放」出来的 dxy 16.8% / cb_gold 14%。
    """
    repo = SettingRepository(db_session)
    legacy_json = (
        '{"trend":{"structure":0.3,"momentum":0.2,"support":0.2,'
        '"momentum_rsi":0.15,"drawdown":0.15},'
        '"macro":{"dxy":0.25,"us10y":0.2,"us30y":0.15,"vix":0.15,"cb_gold":0.25},'
        '"combine":{"tech":0.3,"macro":0.4,"news":0.3}}'
    )
    await repo.set(WEIGHTS_KEY, legacy_json)

    svc = _service(db_session)
    macro = await svc.macro_weights()

    assert set(macro) == set(MACRO_11_KEYS)
    assert abs(sum(macro.values()) - 1.0) < 1e-6
    for key, want in MACRO_11_DEFAULTS.items():
        assert macro[key] == pytest.approx(want, abs=1e-6), key
    # 关键：不是按比例缩放出来的 0.168
    assert macro["dxy"] != pytest.approx(0.168, abs=1e-6)


async def test_stored_custom_5_key_weights_are_migrated_not_reset(
    db_session: AsyncSession,
) -> None:
    """**端到端**：库里存着 5 键**用户自定义**权重 → 读出来是 11 键迁移结果。

    这是本条迁移最关键的行为：读出来是「默认值」意味着用户的自定义权重被吞了。
    """
    repo = SettingRepository(db_session)
    custom_json = (
        '{"trend":{"structure":0.3,"momentum":0.2,"support":0.2,'
        '"momentum_rsi":0.15,"drawdown":0.15},'
        '"macro":{"dxy":0.30,"us10y":0.15,"us30y":0.10,"vix":0.20,"cb_gold":0.25},'
        '"combine":{"tech":0.3,"macro":0.4,"news":0.3}}'
    )
    await repo.set(WEIGHTS_KEY, custom_json)

    svc = _service(db_session)
    macro = await svc.macro_weights()

    assert set(macro) == set(MACRO_11_KEYS)
    assert abs(sum(macro.values()) - 1.0) < 1e-6
    # dxy 迁移后 = 0.30 * 0.56 = 0.168；默认值是 0.13 —— 两者不同才能证明没被重置
    assert macro["dxy"] == pytest.approx(0.168, abs=1e-6)
    assert macro["dxy"] != pytest.approx(0.13, abs=1e-6)


async def test_stored_legacy_8_key_defaults_become_new_defaults(
    db_session: AsyncSession,
) -> None:
    """**端到端**：库里存着 8 键**旧默认**权重 → 读出来是 11 键新默认。"""
    repo = SettingRepository(db_session)
    legacy8_json = (
        '{"trend":{"structure":0.3,"momentum":0.2,"support":0.2,'
        '"momentum_rsi":0.15,"drawdown":0.15},'
        '"macro":{"dxy":0.15,"us2y":0.06,"us10y":0.08,"us30y":0.06,'
        '"curve_10y2y":0.10,"real10y":0.20,"vix":0.10,"cb_gold":0.25},'
        '"combine":{"tech":0.3,"macro":0.4,"news":0.3}}'
    )
    await repo.set(WEIGHTS_KEY, legacy8_json)

    svc = _service(db_session)
    macro = await svc.macro_weights()

    assert set(macro) == set(MACRO_11_KEYS)
    assert abs(sum(macro.values()) - 1.0) < 1e-6
    for key, want in MACRO_11_DEFAULTS.items():
        assert macro[key] == pytest.approx(want, abs=1e-6), key


async def test_stored_custom_8_key_weights_are_migrated_not_reset(
    db_session: AsyncSession,
) -> None:
    """**端到端**：库里存着 8 键**用户自定义**权重 → 读出来是 11 键缩放结果。"""
    repo = SettingRepository(db_session)
    custom8_json = (
        '{"trend":{"structure":0.3,"momentum":0.2,"support":0.2,'
        '"momentum_rsi":0.15,"drawdown":0.15},'
        '"macro":{"dxy":0.30,"us2y":0.05,"us10y":0.08,"us30y":0.07,'
        '"curve_10y2y":0.10,"real10y":0.15,"vix":0.10,"cb_gold":0.15},'
        '"combine":{"tech":0.3,"macro":0.4,"news":0.3}}'
    )
    await repo.set(WEIGHTS_KEY, custom8_json)

    svc = _service(db_session)
    macro = await svc.macro_weights()

    assert set(macro) == set(MACRO_11_KEYS)
    assert abs(sum(macro.values()) - 1.0) < 1e-6
    # dxy 迁移后 = 0.30 * 0.88 = 0.264；默认值是 0.13
    assert macro["dxy"] == pytest.approx(0.264, abs=1e-6)
    assert macro["dxy"] != pytest.approx(0.13, abs=1e-6)


# ───────────────────── V0.110.0 · 宏观因子手动校准 ─────────────────────


async def test_v01100_macro_overrides_default_empty(db_session: AsyncSession) -> None:
    """未设置过 → 空覆盖集（5 项全 None），宏观面行为与改动前一致。"""
    cfg = await _service(db_session).macro_overrides()
    assert cfg.is_empty()
    assert cfg.active() == {}


async def test_v01100_macro_overrides_roundtrip(db_session: AsyncSession) -> None:
    """保存 → 重新读取一致；未填的因子保持 None。"""
    from app.schemas.settings import MacroFactorOverride, MacroFactorOverrideSet

    svc = _service(db_session)
    await svc.save_macro_overrides(
        MacroFactorOverrideSet(
            dxy=MacroFactorOverride(value=97.42, as_of="2026-10-21", note="Wind"),
            vix=MacroFactorOverride(value=16.8, as_of="2026-10-21"),
        )
    )
    clear_weights_cache()  # 绕过 60s 内存缓存，验证真的落库了

    got = await WeightService(SettingRepository(db_session)).macro_overrides()
    assert set(got.active()) == {"dxy", "vix"}
    assert got.dxy.value == 97.42
    assert got.dxy.note == "Wind"
    assert got.us10y is None


async def test_v01100_macro_overrides_isolated_from_weights(db_session: AsyncSession) -> None:
    """覆盖与权重分属不同 key：保存覆盖不得影响已保存的权重。"""
    from app.schemas.settings import MacroFactorOverride, MacroFactorOverrideSet

    svc = _service(db_session)
    await svc.save_weights(WeightConfig())
    await svc.save_macro_overrides(
        MacroFactorOverrideSet(dxy=MacroFactorOverride(value=97.42, as_of="2026-10-21"))
    )
    clear_weights_cache()

    got = await WeightService(SettingRepository(db_session)).get_weights()
    assert got.trend.structure == 0.30  # 默认权重没被动过


async def test_v01100_corrupt_stored_overrides_fallback_empty(db_session: AsyncSession) -> None:
    """存储内容损坏 → 回退空覆盖集（不能因一条坏数据让宏观面整体挂掉）。"""
    from app.repositories.settings import SettingRepository as _Repo
    from app.services.settings import MACRO_OVERRIDE_KEY

    await _Repo(db_session).set(MACRO_OVERRIDE_KEY, "{not-json")
    clear_weights_cache()

    cfg = await _service(db_session).macro_overrides()
    assert cfg.is_empty()


def test_v01100_override_lag_days_counts_trading_days() -> None:
    """滞后天数按交易日计（周一至周五），与白银页 staleness 判定同口径。"""
    from datetime import date

    from app.schemas.settings import MacroFactorOverride
    from app.services.settings import override_lag_days

    ov = MacroFactorOverride(value=97.42, as_of=date(2026, 10, 21))  # 2026-10-21 是周三
    assert override_lag_days(ov, today=date(2026, 10, 21)) == 0  # 当天填的
    assert override_lag_days(ov, today=date(2026, 10, 22)) == 1  # 次日（周四）
    assert override_lag_days(ov, today=date(2026, 10, 28)) == 5  # 整一周（5 个交易日）

    # 跨周末：周五填的读数，下周一查看只算 1 个交易日滞后（周末不是交易日）
    fri = MacroFactorOverride(value=18.0, as_of=date(2026, 10, 23))
    assert override_lag_days(fri, today=date(2026, 10, 26)) == 1

    # 周末填的读数：周六→周一只隔 1 个日历日但 0 个交易日，不提示滞后
    sat = MacroFactorOverride(value=18.0, as_of=date(2026, 10, 17))
    assert override_lag_days(sat, today=date(2026, 10, 19)) == 0


# ───────────────────── V0.120.0 · 三键 → 四键迁移 + 资金流面权重 ─────────────────────

#: V0.119.0 的三键合成权重默认值（技术 / 宏观 / 消息）
LEGACY_COMBINE_3 = {"tech": 0.30, "macro": 0.40, "news": 0.30}

#: V0.120.0 的四键合成权重默认值（新增资金流面 15%）
COMBINE_4_DEFAULTS = {"tech": 0.25, "macro": 0.35, "news": 0.25, "flow": 0.15}

#: 资金流面 6 因子默认权重（周 54% / 月 46%）
MONEY_FLOW_DEFAULTS = {
    "cot_gold_net": 0.18,
    "cot_gold_flow": 0.14,
    "gold_etf_flow": 0.22,
    "us_liq_net": 0.14,
    "cn_margin_flow": 0.16,
    "cn_money_gap": 0.16,
}


def test_combine_legacy_3_defaults_become_new_defaults() -> None:
    """存量三键**恰好等于旧默认** ⇒ 直接落到四键新默认（25/35/25/15）。

    「旧默认值也是一种用户状态」：存量值恰好等于旧默认 = 用户从没自定义过，
    迁移时必须直落新默认，而不是按比例缩放出来的 25.5/34/25.5/15。
    """
    from app.schemas.settings import CombineWeightConfig

    cfg = CombineWeightConfig.model_validate(LEGACY_COMBINE_3)
    dumped = cfg.model_dump()
    assert set(dumped) == set(COMBINE_4_DEFAULTS)
    for key, want in COMBINE_4_DEFAULTS.items():
        assert dumped[key] == pytest.approx(want, abs=1e-9), key
    # 关键：不是缩放值
    assert dumped["tech"] != pytest.approx(0.255, abs=1e-6)


def test_combine_custom_3_keys_are_scaled_not_reset() -> None:
    """存量三键**自定义**值 ⇒ 三个面按原相对比例缩到 85%，资金流面取 15%。

    **不做迁移会怎样**：flow 拿到默认值 0.15 后合计 = 1.15 → ``_sum_to_one`` 抛错
    → ``_load_weights`` 的异常兜底路径**静默把用户的自定义权重重置为默认**。
    """
    from app.schemas.settings import CombineWeightConfig

    custom3 = {"tech": 0.50, "macro": 0.30, "news": 0.20}
    cfg = CombineWeightConfig.model_validate(custom3)
    dumped = cfg.model_dump()

    assert abs(sum(dumped.values()) - 1.0) < 1e-6
    assert dumped["flow"] == pytest.approx(0.15, abs=1e-9)
    for key, old in custom3.items():
        assert dumped[key] == pytest.approx(old * 0.85, abs=1e-6), key


async def test_stored_legacy_3_key_combine_becomes_new_defaults(
    db_session: AsyncSession,
) -> None:
    """**端到端**：库里存着三键**旧默认** ⇒ 读出来是四键新默认。"""
    repo = SettingRepository(db_session)
    legacy_json = (
        '{"trend":{"structure":0.3,"momentum":0.2,"support":0.2,'
        '"momentum_rsi":0.15,"drawdown":0.15},'
        '"macro":{"dxy":0.13,"us2y":0.05,"us10y":0.07,"us30y":0.05,'
        '"curve_10y2y":0.09,"real10y":0.18,"vix":0.09,"cb_gold":0.22,'
        '"us_gov_debt":0.05,"cn_gov_debt":0.04,"eu_gov_debt":0.03},'
        '"combine":{"tech":0.3,"macro":0.4,"news":0.3}}'
    )
    await repo.set(WEIGHTS_KEY, legacy_json)
    clear_weights_cache()

    svc = _service(db_session)
    assert await svc.combine_weights() == (0.25, 0.35, 0.25, 0.15)


async def test_money_flow_weights_default_and_roundtrip(db_session: AsyncSession) -> None:
    """资金流面 6 因子权重：默认 18/14/22/14/16/16（合计 1），保存后可回读。"""
    from app.schemas.settings import MoneyFlowWeightConfig

    svc = _service(db_session)
    got = await svc.money_flow_weights()
    assert set(got) == set(MONEY_FLOW_DEFAULTS)
    assert abs(sum(got.values()) - 1.0) < 1e-6
    for key, want in MONEY_FLOW_DEFAULTS.items():
        assert got[key] == pytest.approx(want, abs=1e-9), key

    custom = WeightConfig(
        flow=MoneyFlowWeightConfig.model_validate(
            {
                "cot_gold_net": 0.30,
                "cot_gold_flow": 0.10,
                "gold_etf_flow": 0.20,
                "us_liq_net": 0.10,
                "cn_margin_flow": 0.15,
                "cn_money_gap": 0.15,
            }
        )
    )
    await svc.save_weights(custom)
    clear_weights_cache()

    got2 = await _service(db_session).money_flow_weights()
    assert got2["cot_gold_net"] == pytest.approx(0.30, abs=1e-9)
    assert got2["gold_etf_flow"] == pytest.approx(0.20, abs=1e-9)
    assert abs(sum(got2.values()) - 1.0) < 1e-6
