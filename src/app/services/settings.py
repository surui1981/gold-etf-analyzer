"""权重配置服务：读取/保存用户自定义权重，未配置时返回默认值。"""

import json
import time

from pydantic import BaseModel, ConfigDict

from app.repositories.settings import SettingRepository
from app.schemas.alert import AlertRuleIn, AlertRuleOut
from app.schemas.backtest import BacktestConfigIn, BacktestConfigOut
from app.schemas.settings import (
    WeightConfig,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

WEIGHTS_KEY = "weight_config"

# V0.71.0：回测预设配置 key（与 weight_config 共用 settings 表，key 区分）
BACKTEST_CONFIG_KEY = "backtest_config"

# 配置内存缓存（P2-3）：权重属于低频变更数据，读库缓存 60s，保存时立即失效
WEIGHTS_CACHE_TTL = 60  # 秒
_WEIGHTS_CACHE: dict = {"ts": 0.0, "config": None}

# V0.71.0：回测配置缓存（与 weights 同 TTL）
_BACKTEST_CACHE: dict = {"ts": 0.0, "config": None}


def clear_weights_cache() -> None:
    """使配置缓存失效（保存配置 / 测试隔离时调用）。"""
    global _WEIGHTS_CACHE, _BACKTEST_CACHE, _ALERT_RULES_CACHE
    _WEIGHTS_CACHE = {"ts": 0.0, "config": None}
    _BACKTEST_CACHE = {"ts": 0.0, "config": None}
    _ALERT_RULES_CACHE = {"ts": 0.0, "config": None}


class WeightService:
    """评估权重管理：趋势维度 / 宏观因子 / 技术宏观合成比。"""

    def __init__(self, repo: SettingRepository) -> None:
        self._repo = repo

    async def get_weights(self) -> WeightConfig:
        """获取当前权重（内存缓存优先，TTL 60s，保存时失效）。"""
        global _WEIGHTS_CACHE
        if (
            _WEIGHTS_CACHE["config"] is not None
            and time.time() - _WEIGHTS_CACHE["ts"] < WEIGHTS_CACHE_TTL
        ):
            return _WEIGHTS_CACHE["config"]

        config = await self._load_weights()
        _WEIGHTS_CACHE = {"ts": time.time(), "config": config}
        return config

    async def _load_weights(self) -> WeightConfig:
        """从存储加载权重（含旧版配置迁移，失败回退默认）。"""
        raw = await self._repo.get(WEIGHTS_KEY)
        if raw:
            try:
                return WeightConfig.model_validate_json(raw)
            except Exception as exc:
                logger.warning("stored weights invalid (%s), try migrate legacy config", exc)
                migrated = _migrate_legacy(raw)
                if migrated is not None:
                    logger.info("Legacy weights migrated: %s", migrated.model_dump_json())
                    return migrated
                logger.warning("weights migration failed, fallback default")
        return WeightConfig()

    async def save_weights(self, config: WeightConfig) -> WeightConfig:
        """保存权重并返回（schema 已校验各组和=1），保存后失效缓存。"""
        await self._repo.set(WEIGHTS_KEY, config.model_dump_json())
        clear_weights_cache()
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
    except Exception:
        return None


# ───────────────────── V0.71.0：回测预设配置 ─────────────────────


async def get_backtest_config(repo: SettingRepository):
    """读取回测配置（60s 缓存，未配置返回默认 BacktestConfigIn）。"""
    global _BACKTEST_CACHE
    now = time.time()
    if _BACKTEST_CACHE["config"] is not None and now - _BACKTEST_CACHE["ts"] < WEIGHTS_CACHE_TTL:
        return _BACKTEST_CACHE["config"]
    raw = await repo.get(BACKTEST_CONFIG_KEY)
    if raw:
        try:
            cfg = BacktestConfigOut.model_validate_json(raw)
        except Exception as exc:
            logger.warning("backtest_config 解析失败 (%s), 回退默认", exc)
            cfg = BacktestConfigOut()
    else:
        cfg = BacktestConfigOut()
    _BACKTEST_CACHE = {"ts": now, "config": cfg}
    return cfg


async def save_backtest_config(repo: SettingRepository, config: BacktestConfigIn):
    """保存回测配置到 settings 表（key='backtest_config'），保存后失效缓存。"""
    from datetime import datetime

    saved = BacktestConfigOut(
        days=config.days,
        target=config.target,
        weight_grid=config.weight_grid,
        threshold_bands=config.threshold_bands,
        updated_at=datetime.now(),
    )
    await repo.set(BACKTEST_CONFIG_KEY, saved.model_dump_json())
    global _BACKTEST_CACHE
    _BACKTEST_CACHE = {"ts": time.time(), "config": saved}
    logger.info("Backtest config saved: %s", saved.model_dump_json())
    return saved


# ───────────────────── V0.72.0：告警规则（推送渠道 + 档位穿越 + 波动阈值） ─────────────────────

ALERT_RULES_KEY = "alert_rules"
# 60s 缓存（与 weights / backtest 一致）
_ALERT_RULES_CACHE: dict = {"ts": 0.0, "config": None}


def clear_alert_rules_cache() -> None:
    """测试隔离：失效告警规则缓存。"""
    global _ALERT_RULES_CACHE
    _ALERT_RULES_CACHE = {"ts": 0.0, "config": None}


async def get_alert_rules(repo: SettingRepository) -> AlertRuleOut:
    """读取告警规则（60s 缓存，未配置返回默认 AlertRuleOut）。"""
    global _ALERT_RULES_CACHE
    now = time.time()
    if _ALERT_RULES_CACHE["config"] is not None and now - _ALERT_RULES_CACHE["ts"] < WEIGHTS_CACHE_TTL:
        return _ALERT_RULES_CACHE["config"]
    raw = await repo.get(ALERT_RULES_KEY)
    if raw:
        try:
            cfg = AlertRuleOut.model_validate_json(raw)
        except Exception as exc:
            logger.warning("alert_rules 解析失败 (%s), 回退默认", exc)
            cfg = AlertRuleOut()
    else:
        cfg = AlertRuleOut()
    _ALERT_RULES_CACHE = {"ts": now, "config": cfg}
    return cfg


async def save_alert_rules(repo: SettingRepository, rules: AlertRuleIn) -> AlertRuleOut:
    """保存告警规则到 settings 表（key='alert_rules'），保存后失效缓存。

    V0.74.0 N+18：直接用 rules.model_dump() 序列化整张 AlertRuleIn
    (含异构 ``rules`` 列表 + 旧兼容字段 + channels)；AlertRuleIn.model_validator
    已经把旧扁平字段迁移到 rules,所以 AlertRuleOut.rules 就是最终生效的列表。
    """
    from datetime import datetime

    saved = AlertRuleOut(
        **rules.model_dump(),  # 保留 rules.* + 旧字段 + channels
        updated_at=datetime.now(),
    )
    await repo.set(ALERT_RULES_KEY, saved.model_dump_json())
    global _ALERT_RULES_CACHE
    _ALERT_RULES_CACHE = {"ts": time.time(), "config": saved}
    logger.info("Alert rules saved: %s", saved.model_dump_json())
    return saved


# ───────────────────── V0.72.0 P3-b：VAPID 密钥对持久化 ─────────────────────

VAPID_KEYS_KEY = "vapid_keys"
_VAPID_KEYS_CACHE: dict = {"ts": 0.0, "config": None}


def clear_vapid_keys_cache() -> None:
    """测试隔离。"""
    global _VAPID_KEYS_CACHE
    _VAPID_KEYS_CACHE = {"ts": 0.0, "config": None}


class VapidKeys(BaseModel):
    """VAPID 密钥对（私钥服务端持有，公钥发给前端 subscribe）。"""

    model_config = ConfigDict(extra="ignore")

    private_key: str  # PEM 格式（base64url encoded EC private key）
    public_key: str  # base64url encoded EC public key (uncompressed point)


async def get_vapid_keys(repo: SettingRepository) -> VapidKeys | None:
    """返回 VAPID 密钥对（不存在返回 None，启动期会按需生成）。"""
    global _VAPID_KEYS_CACHE
    now = time.time()
    if _VAPID_KEYS_CACHE["config"] is not None and now - _VAPID_KEYS_CACHE["ts"] < WEIGHTS_CACHE_TTL:
        return _VAPID_KEYS_CACHE["config"]  # type: ignore[no-any-return]
    raw = await repo.get(VAPID_KEYS_KEY)
    if not raw:
        return None
    cfg = VapidKeys.model_validate_json(raw)
    _VAPID_KEYS_CACHE = {"ts": now, "config": cfg}
    return cfg


async def save_vapid_keys(repo: SettingRepository, keys: VapidKeys) -> VapidKeys:
    """保存 VAPID 密钥对（启动期生成一次后调用）。"""
    await repo.set(VAPID_KEYS_KEY, keys.model_dump_json())
    global _VAPID_KEYS_CACHE
    _VAPID_KEYS_CACHE = {"ts": time.time(), "config": keys}
    logger.info("VAPID keys saved (public_key length=%d)", len(keys.public_key))
    return keys
