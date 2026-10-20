"""权重配置服务：读取/保存用户自定义权重，未配置时返回默认值。"""

import json
import time
from datetime import date

from pydantic import BaseModel, ConfigDict

from app.repositories.settings import SettingRepository
from app.schemas.alert import AlertRuleIn, AlertRuleOut
from app.schemas.backtest import BacktestConfigIn, BacktestConfigOut
from app.schemas.settings import (
    MacroFactorOverride,
    MacroFactorOverrideSet,
    WeightConfig,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

WEIGHTS_KEY = "weight_config"

# V0.71.0：回测预设配置 key（与 weight_config 共用 settings 表，key 区分）
BACKTEST_CONFIG_KEY = "backtest_config"

# V0.110.0：宏观因子手动校准 key（独立于 weight_config，避免权重保存时相互覆盖）
MACRO_OVERRIDE_KEY = "macro_factor_overrides"

# 配置内存缓存（P2-3）：权重属于低频变更数据，读库缓存 60s，保存时立即失效
WEIGHTS_CACHE_TTL = 60  # 秒
_WEIGHTS_CACHE: dict = {"ts": 0.0, "config": None}

# V0.71.0：回测配置缓存（与 weights 同 TTL）
_BACKTEST_CACHE: dict = {"ts": 0.0, "config": None}

# V0.110.0：宏观因子手动校准缓存（与 weights 同 TTL）
_MACRO_OVERRIDE_CACHE: dict = {"ts": 0.0, "config": None}


def clear_weights_cache() -> None:
    """使配置缓存失效（保存配置 / 测试隔离时调用）。"""
    global _WEIGHTS_CACHE, _BACKTEST_CACHE, _ALERT_RULES_CACHE, _MACRO_OVERRIDE_CACHE
    _WEIGHTS_CACHE = {"ts": 0.0, "config": None}
    _BACKTEST_CACHE = {"ts": 0.0, "config": None}
    _ALERT_RULES_CACHE = {"ts": 0.0, "config": None}
    _MACRO_OVERRIDE_CACHE = {"ts": 0.0, "config": None}


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

    async def group_combine(self) -> bool:
        """技术面 5 维度是否按组内平均合成（V0.79.0 Step F）。

        True（默认）：trend / overbought / risk 3 组组内先平均，再按 GROUP_WEIGHTS 加权；
        False：保持单维度加权（历史行为，向后兼容）。
        """
        return (await self.get_weights()).group_combine

    # ── V0.110.0：宏观因子手动校准 ─────────────────────────────

    async def macro_overrides(self) -> MacroFactorOverrideSet:
        """当前生效的宏观因子手动覆盖集合（未设置过则返回全 None 的空集合）。

        挂在 ``WeightService`` 上而不是新建服务，是因为 ``MacroFactorService`` 已经
        注入了本对象 —— 复用同一条 ``SettingRepository`` 链路，无需新增 DI 依赖。
        """
        global _MACRO_OVERRIDE_CACHE
        now = time.time()
        if (
            _MACRO_OVERRIDE_CACHE["config"] is not None
            and now - _MACRO_OVERRIDE_CACHE["ts"] < WEIGHTS_CACHE_TTL
        ):
            return _MACRO_OVERRIDE_CACHE["config"]
        raw = await self._repo.get(MACRO_OVERRIDE_KEY)
        if raw:
            try:
                cfg = MacroFactorOverrideSet.model_validate_json(raw)
            except Exception as exc:
                logger.warning("macro_factor_overrides 解析失败 (%s), 回退为空覆盖", exc)
                cfg = MacroFactorOverrideSet()
        else:
            cfg = MacroFactorOverrideSet()
        _MACRO_OVERRIDE_CACHE = {"ts": now, "config": cfg}
        return cfg

    async def save_macro_overrides(
        self, overrides: MacroFactorOverrideSet
    ) -> MacroFactorOverrideSet:
        """保存宏观因子手动覆盖（整体替换语义；全 None 等价于「清除全部覆盖」）。

        保存后立即失效内存缓存，让下一次宏观面评分就用上新值 —— 否则用户改完
        数字回到首页看到的还是旧指数，会以为「没生效」。
        """
        await self._repo.set(MACRO_OVERRIDE_KEY, overrides.model_dump_json())
        global _MACRO_OVERRIDE_CACHE
        _MACRO_OVERRIDE_CACHE = {"ts": time.time(), "config": overrides}
        logger.info("Macro factor overrides saved: %s", overrides.model_dump_json())
        return overrides


def override_lag_days(override: MacroFactorOverride, *, today: date | None = None) -> int:
    """手动覆盖值落后今天多少个交易日（用于 UI 滞后提示；当天填的返回 0）。

    V0.110.0：复用 ``utils.market_clock.trading_days_between``，与白银页面的
    staleness 判定同口径（周一至周五；SGE / A 股同日休市）。该函数**含两端**，
    所以同一天返回 1 —— 这里减 1 才是用户理解的"滞后天数"。

    与 V0.109.2 的 stale 判定保持一致：``trading_days_between(as_of, today) > 1``
    等价于本函数 ``> 0``，即"不是当天填的就提示滞后"。
    """
    from app.utils.market_clock import trading_days_between

    return max(0, trading_days_between(override.as_of, today or date.today()) - 1)


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
    if (
        _ALERT_RULES_CACHE["config"] is not None
        and now - _ALERT_RULES_CACHE["ts"] < WEIGHTS_CACHE_TTL
    ):
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
    if (
        _VAPID_KEYS_CACHE["config"] is not None
        and now - _VAPID_KEYS_CACHE["ts"] < WEIGHTS_CACHE_TTL
    ):
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
