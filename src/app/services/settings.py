"""权重配置服务：读取/保存用户自定义权重，未配置时返回默认值。"""

import json

from app.repositories.settings import SettingRepository
from app.schemas.settings import (
    CombineWeightConfig,
    MacroWeightConfig,
    TrendWeightConfig,
    WeightConfig,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

WEIGHTS_KEY = "weight_config"


class WeightService:
    """评估权重管理：趋势维度 / 宏观因子 / 技术宏观合成比。"""

    def __init__(self, repo: SettingRepository) -> None:
        self._repo = repo

    async def get_weights(self) -> WeightConfig:
        """获取当前权重（存储值优先，缺失回退默认）。"""
        raw = await self._repo.get(WEIGHTS_KEY)
        if raw:
            try:
                config = WeightConfig.model_validate_json(raw)
                return config
            except Exception as exc:  # noqa: BLE001 —— 脏数据回退默认
                logger.warning("stored weights invalid (%s), fallback default", exc)
        return WeightConfig()

    async def save_weights(self, config: WeightConfig) -> WeightConfig:
        """保存权重并返回（schema 已校验各组和=1）。"""
        await self._repo.set(WEIGHTS_KEY, config.model_dump_json())
        logger.info("Weights saved: %s", config.model_dump_json())
        return config

    async def trend_weights(self) -> dict[str, float]:
        """技术面维度权重（中文 key，供 TrendService）。"""
        w = (await self.get_weights()).trend
        return {
            "结构": w.structure,
            "动量": w.momentum,
            "支撑": w.support,
            "动能": w.momentum_rsi,
            "回撤": w.drawdown,
        }

    async def macro_weights(self) -> dict[str, float]:
        """宏观面因子权重（英文 key，供 MacroFactorService）。"""
        w = (await self.get_weights()).macro
        return {
            "dxy": w.dxy,
            "us10y": w.us10y,
            "us30y": w.us30y,
            "vix": w.vix,
            "cb_gold": w.cb_gold,
        }

    async def combine_weights(self) -> tuple[float, float]:
        """综合指数合成权重：(技术面, 宏观面)。"""
        w = (await self.get_weights()).combine
        return w.tech, w.macro
