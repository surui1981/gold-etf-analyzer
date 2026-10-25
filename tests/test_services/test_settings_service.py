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
    # V0.118.0：宏观面 5 因子 → 8 因子，默认值同步改成新方案
    assert w.macro.dxy == 0.15
    assert w.macro.us2y == 0.06
    assert w.macro.us10y == 0.08
    assert w.macro.us30y == 0.06
    assert w.macro.curve_10y2y == 0.10
    assert w.macro.real10y == 0.20
    assert w.macro.vix == 0.10
    assert w.macro.cb_gold == 0.25
    assert w.combine.tech == 0.30
    assert w.combine.macro == 0.40
    assert w.combine.news == 0.30


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
            "cb_gold": 0.15,
        },
        combine={"tech": 0.50, "macro": 0.30, "news": 0.20},
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
    assert await svc.combine_weights() == (0.50, 0.30, 0.20)

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
            "cb_gold": 0.15,
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


# ───────────────────── V0.118.0 · 宏观 5 因子 → 8 因子迁移 ─────────────────────

#: V0.118.0 之前落库的宏观权重 JSON（5 因子，合计 = 1.0）
LEGACY_MACRO_5 = {"dxy": 0.25, "us10y": 0.2, "us30y": 0.15, "vix": 0.15, "cb_gold": 0.25}

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


def test_macro_weight_config_migrates_5_to_8_keys() -> None:
    """5 键旧配置 → 8 键：新增因子取默认值，旧因子按比例缩放，合计仍为 1。

    **不做迁移会怎样**：3 个新字段拿到默认值后合计 = 1.36 → ``_sum_to_one`` 抛错
    → ``_load_weights`` 的异常兜底路径**静默把用户的自定义权重重置为默认**。
    """
    cfg = MacroWeightConfig.model_validate(LEGACY_MACRO_5)
    dumped = cfg.model_dump()

    assert set(dumped) == set(MACRO_8_KEYS)
    assert abs(sum(dumped.values()) - 1.0) < 1e-6

    # 新增因子取默认值
    assert dumped["us2y"] == pytest.approx(0.06)
    assert dumped["curve_10y2y"] == pytest.approx(0.10)
    assert dumped["real10y"] == pytest.approx(0.20)

    # 旧因子的**相对比例**保持不变（旧合计 1.0 → 扣掉新增份额 0.36 → 缩放系数 0.64）
    scale = 0.64
    for key, old in LEGACY_MACRO_5.items():
        assert dumped[key] == pytest.approx(old * scale, abs=1e-6), key


def test_macro_weight_config_with_8_keys_is_not_touched() -> None:
    """已经给全 8 个 key → 原样返回，不做任何缩放。"""
    full = {
        "dxy": 0.30,
        "us2y": 0.05,
        "us10y": 0.08,
        "us30y": 0.07,
        "curve_10y2y": 0.10,
        "real10y": 0.15,
        "vix": 0.10,
        "cb_gold": 0.15,
    }
    cfg = MacroWeightConfig.model_validate(full)
    dumped = cfg.model_dump()
    for key, val in full.items():
        assert dumped[key] == pytest.approx(val), key
    assert abs(sum(dumped.values()) - 1.0) < 1e-6


async def test_stored_legacy_5_key_weights_are_migrated_not_reset(
    db_session: AsyncSession,
) -> None:
    """**端到端**：库里存着 5 键旧权重 → 读出来是 8 键迁移结果，不是默认值。

    这是本条迁移最关键的行为：读出来是「默认值」意味着用户的自定义权重被吞了。
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

    assert set(macro) == set(MACRO_8_KEYS)
    assert abs(sum(macro.values()) - 1.0) < 1e-6
    # dxy 迁移后 = 0.25 * 0.64 = 0.16；默认值是 0.15 —— 两者不同才能证明没被重置
    assert macro["dxy"] == pytest.approx(0.16, abs=1e-6)
    assert macro["dxy"] != pytest.approx(0.15, abs=1e-6)


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
