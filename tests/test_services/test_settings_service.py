"""权重配置服务单元测试：默认值、保存读取、分组权重。"""

import pytest
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
        trend={"structure": 0.40, "momentum": 0.20, "support": 0.20, "momentum_rsi": 0.10, "drawdown": 0.10},
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
    with pytest.raises(Exception):
        WeightConfig(trend={"structure": 0.5, "momentum": 0.5, "support": 0.1, "momentum_rsi": 0.1, "drawdown": 0.1})
