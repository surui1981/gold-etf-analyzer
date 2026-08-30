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
        """获取当前权重（存储值优先，缺失回退默认）。

        兼容旧版配置：V0.20 之前合成权重只有 tech/macro 两项，
        升级后要求三项（含 news）之和为 1，缺 news 时自动补全，避免整份配置被丢弃。
        """
        raw = await self._repo.get(WEIGHTS_KEY)
        if raw:
            try:
                return WeightConfig.model_validate_json(raw)
            except Exception as exc:  # noqa: BLE001 —— 脏数据尝试修复
                logger.warning("stored weights invalid (%s), try migrate legacy config", exc)
                migrated = _migrate_legacy(raw)
                if migrated is not None:
                    logger.info("Legacy weights migrated: %s", migrated.model_dump_json())
                    return migrated
                logger.warning("weights migration failed, fallback default")
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

    async def combine_weights(self) -> tuple[float, float, float]:
        """综合指数合成权重：(技术面, 宏观面, 消息面)。"""
        w = (await self.get_weights()).combine
        return w.tech, w.macro, w.news


def _migrate_legacy(raw: str) -> WeightConfig | None:
    """迁移旧版权重配置（合成权重缺 news 时按余额补全）。"""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None

    combine = data.get("combine")
    if isinstance(combine, dict) and "news" not in combine:
        try:
            tech = float(combine.get("tech", 0.6))
            macro = float(combine.get("macro", 0.4))
        except (TypeError, ValueError):
            return None

        legacy_default = abs(tech - 0.6) < 1e-6 and abs(macro - 0.4) < 1e-6
        if legacy_default:
            # 旧版默认配置（用户未自定义）→ 直接采用 V0.20 三面默认 30/40/30
            data["combine"] = {"tech": 0.30, "macro": 0.40, "news": 0.30}
        else:
            # 用户自定义过：保留 tech/macro 相对比例，消息面取默认 30%
            news = 0.30
            total = tech + macro
            scale = (1.0 - news) / total if total > 0 else 0.0
            data["combine"] = {
                "tech": round(tech * scale, 4),
                "macro": round(macro * scale, 4),
                "news": news,
            }
    try:
        return WeightConfig.model_validate(data)
    except Exception:  # noqa: BLE001
        return None
