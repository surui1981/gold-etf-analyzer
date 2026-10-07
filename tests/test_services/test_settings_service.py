"""权重配置服务单元测试：默认值、保存读取、分组权重。"""

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.settings import SettingRepository
from app.schemas.settings import WeightConfig
from app.services.settings import WEIGHTS_KEY, WeightService


def _service(session: AsyncSession) -> WeightService:
    return WeightService(SettingRepository(session))


async def test_default_weights(db_session: AsyncSession) -> None:
    """未配置时返回内置默认权重。"""
    svc = _service(db_session)
    w = await svc.get_weights()

    assert w.trend.structure == 0.30
    assert w.trend.momentum == 0.20
    assert w.macro.dxy == 0.25
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
        macro={"dxy": 0.30, "us10y": 0.20, "us30y": 0.10, "vix": 0.20, "cb_gold": 0.20},
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
        macro={"dxy": 0.25, "us10y": 0.20, "us30y": 0.15, "vix": 0.15, "cb_gold": 0.25},
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
