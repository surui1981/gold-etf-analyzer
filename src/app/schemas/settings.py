"""权重配置 Schema：技术面/宏观面/合成权重（各组权重和须为 1）。

V0.110.0 起另含**宏观因子手动校准**（``MacroFactorOverrideSet``）—— 解决
``dxy`` / ``vix`` 长期停在 ``STATIC_REF``（2026-08-28）导致宏观面评分失真的问题。

V0.118.0：宏观面因子从 5 个扩到 8 个（新增 ``us2y`` / ``curve_10y2y`` / ``real10y``）。
存量 5 键权重配置由 ``MacroWeightConfig._migrate_missing_factors``（before 校验器）
做**无损迁移** —— 见该方法 docstring，不做迁移会让用户的自定义权重静默重置。
"""

from datetime import date
from typing import Any

from pydantic import BaseModel, Field, model_validator

#: V0.117.x 及更早的宏观面 5 因子**默认**权重（当时 ``MacroWeightConfig`` 的字段默认值）。
#:
#: 存量配置**恰好等于**这组值 ⇒ 用户从没自定义过（存的就是当时的默认值）
#: ⇒ 升级后应直接落到 V0.118.0 的新默认，而不是对旧默认做按比例缩放
#: （那会得到 dxy 16% / us10y 12.8% / cb_gold 16% 这类「谁都没设计过」的权重）。
#: 真正的用户自定义值不等于这组值 ⇒ 仍走按比例迁移，保留相对偏好。
LEGACY_MACRO_DEFAULTS: dict[str, float] = {
    "dxy": 0.25,
    "us10y": 0.20,
    "us30y": 0.15,
    "vix": 0.15,
    "cb_gold": 0.25,
}


class TrendWeightConfig(BaseModel):
    """技术面趋势 5 维度权重。"""

    structure: float = Field(0.30, ge=0, le=1, description="结构（均线排列+MA20斜率）")
    momentum: float = Field(0.20, ge=0, le=1, description="动量（近20日涨幅）")
    support: float = Field(0.20, ge=0, le=1, description="支撑（相对MA20/40乖离）")
    momentum_rsi: float = Field(0.15, ge=0, le=1, description="动能（RSI）")
    drawdown: float = Field(0.15, ge=0, le=1, description="回撤（距高点回撤）")

    @model_validator(mode="after")
    def _sum_to_one(self) -> "TrendWeightConfig":
        total = self.structure + self.momentum + self.support + self.momentum_rsi + self.drawdown
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"技术面权重之和须为 1，当前 {total:.3f}")
        return self


class MacroWeightConfig(BaseModel):
    """宏观面 8 因子权重（V0.118.0 起）。

    分组：美元 15% / 名义利率（2Y+10Y+30Y）20% / 曲线形态 10% /
    实际利率 20% / 风险偏好 10% / 结构性需求 25%。
    """

    dxy: float = Field(0.15, ge=0, le=1, description="美元指数")
    us2y: float = Field(0.06, ge=0, le=1, description="美债2Y收益率")
    us10y: float = Field(0.08, ge=0, le=1, description="美债10Y收益率")
    us30y: float = Field(0.06, ge=0, le=1, description="美债30Y收益率")
    curve_10y2y: float = Field(0.10, ge=0, le=1, description="美债10Y-2Y利差")
    real10y: float = Field(0.20, ge=0, le=1, description="美债10Y实际利率")
    vix: float = Field(0.10, ge=0, le=1, description="VIX恐慌指数")
    cb_gold: float = Field(0.25, ge=0, le=1, description="国际央行购金量")

    @model_validator(mode="before")
    @classmethod
    def _migrate_missing_factors(cls, data: Any) -> Any:
        """旧版 5 因子配置 → 8 因子：新增因子按默认份额从旧因子里**按比例扣除**。

        **为什么必须做**：V0.118.0 之前存进 ``app_settings`` 的权重 JSON 只有
        5 个 key 且合计 = 1.0。直接给 3 个新字段加默认值，合计会变成 1.36 →
        ``_sum_to_one`` 抛错 → ``services/settings.py::_load_weights`` 的异常兜底
        路径会**静默把用户的自定义权重重置为默认**（用户毫无察觉）。

        **迁移规则**：新增因子的默认份额（合计 ``add``）从旧因子里按各自占比扣除
        （等比例缩放，保留用户对各因子的相对偏好），再补上新因子的默认值。
        全部 8 个 key 都给全时**原样返回**，不做任何干预。

        **例外（V0.118.0 补）**：存量配置**恰好等于旧版默认权重**
        （``LEGACY_MACRO_DEFAULTS``）⇒ 用户从没自定义过 ⇒ 直接落到**新默认**，
        不做按比例缩放。否则「没动过权重」的用户会拿到
        dxy 16% / us10y 12.8% / us30y 9.6% / vix 9.6% / cb_gold 16%
        这组谁都没设计过的权重 —— 与本版设计（15 / 8 / 6 / 10 / 25 + 新增 36%）
        不符。真正的自定义值不等于旧默认 ⇒ 仍走按比例迁移。
        """
        if not isinstance(data, dict):
            return data
        fields = cls.model_fields
        missing = [k for k in fields if k not in data]
        if not missing:
            return data
        present: dict[str, float] = {}
        for k, v in data.items():
            if k in fields and isinstance(v, (int, float)) and not isinstance(v, bool):
                present[k] = float(v)
        if not present:
            return data
        # 「用户从没自定义过」⇒ 直接换成新默认（而不是对旧默认做按比例缩放）
        if set(present) == set(LEGACY_MACRO_DEFAULTS) and all(
            abs(present[k] - v) < 1e-9 for k, v in LEGACY_MACRO_DEFAULTS.items()
        ):
            return {k: float(fields[k].default) for k in fields}
        add = sum(float(fields[k].default) for k in missing)
        base = sum(present.values())
        if base <= 0:
            return data
        scale = max(0.0, base - add) / base
        migrated = {k: round(v * scale, 6) for k, v in present.items()}
        for k in missing:
            migrated[k] = float(fields[k].default)
        # 舍入误差归到权重最大的那个因子上，保证合计精确为 1
        total = sum(migrated.values())
        if abs(total - 1.0) > 1e-9:
            anchor = max(migrated, key=migrated.get)
            migrated[anchor] = round(migrated[anchor] + (1.0 - total), 6)
        return migrated

    @model_validator(mode="after")
    def _sum_to_one(self) -> "MacroWeightConfig":
        total = (
            self.dxy
            + self.us2y
            + self.us10y
            + self.us30y
            + self.curve_10y2y
            + self.real10y
            + self.vix
            + self.cb_gold
        )
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"宏观面权重之和须为 1，当前 {total:.3f}")
        return self


class CombineWeightConfig(BaseModel):
    """综合指数合成权重：技术面 vs 宏观面 vs 消息面（中短期 ETF 波段操作）。"""

    tech: float = Field(0.30, ge=0, le=1, description="技术面占比（默认 30%）")
    macro: float = Field(0.40, ge=0, le=1, description="宏观面占比（默认 40%）")
    news: float = Field(0.30, ge=0, le=1, description="消息面占比（默认 30%，客户评估）")

    @model_validator(mode="after")
    def _sum_to_one(self) -> "CombineWeightConfig":
        if abs(self.tech + self.macro + self.news - 1.0) > 0.001:
            raise ValueError(f"合成权重之和须为 1，当前 {self.tech + self.macro + self.news:.3f}")
        return self


class WeightConfig(BaseModel):
    """完整权重配置（GET/PUT /settings/weights）。"""

    trend: TrendWeightConfig = Field(default_factory=TrendWeightConfig)
    macro: MacroWeightConfig = Field(default_factory=MacroWeightConfig)
    combine: CombineWeightConfig = Field(default_factory=CombineWeightConfig)
    # V0.79.0 Step F：技术面 5 维度合成方式开关。True=组内平均（默认；降低内部相关性），
    # False=单维度加权（历史行为，向后兼容）。不影响宏观/消息面合成。
    group_combine: bool = Field(
        True,
        description="技术面 5 维度是否按组内平均合成（V0.79.0 Step F，默认开启）",
    )


# ───────────────────── V0.110.0：宏观因子手动校准 ─────────────────────

#: 手动校准覆盖的因子集合（与 ``services/macro.py::MACRO_FACTOR_RULES`` 的 key 一一对应）
#: V0.118.0：5 → 8（新增 us2y / curve_10y2y / real10y）
MACRO_FACTOR_KEYS: tuple[str, ...] = (
    "dxy",
    "us2y",
    "us10y",
    "us30y",
    "curve_10y2y",
    "real10y",
    "vix",
    "cb_gold",
)


class MacroFactorOverride(BaseModel):
    """单个宏观因子的手动读数覆盖。

    背景（V0.110.0）：``dxy`` / ``vix`` 没有实时源，长期使用 ``STATIC_REF`` 里
    2026-08-28 的硬编码值（96.5 / 18.5）。这两个因子在宏观面内部合计权重 0.40，
    宏观面又占综合指数 0.40 —— 相当于**综合指数的 16% 建立在两个半月前的常量上**。
    本模型允许用户从行情终端抄入当日真实读数临时顶替内置静态值。

    V0.118.0：``dxy`` / ``vix`` 已有自动源（Yahoo / FRED），手动覆盖退化为
    「自动源不可用时的兜底 + 用户对读数的直接修正」。
    """

    value: float = Field(..., description="覆盖值（与因子单位一致：点位 / % / 吨每年）")
    as_of: date = Field(..., description="该读数对应的交易日；用于计算滞后天数")
    note: str | None = Field(None, max_length=120, description="备注（可选，如数据来源）")


class MacroFactorOverrideSet(BaseModel):
    """8 个宏观因子的手动覆盖集合；``None`` 表示该因子走自动数据源。"""

    dxy: MacroFactorOverride | None = None
    us2y: MacroFactorOverride | None = None
    us10y: MacroFactorOverride | None = None
    us30y: MacroFactorOverride | None = None
    curve_10y2y: MacroFactorOverride | None = None
    real10y: MacroFactorOverride | None = None
    vix: MacroFactorOverride | None = None
    cb_gold: MacroFactorOverride | None = None

    def active(self) -> dict[str, MacroFactorOverride]:
        """返回已设置覆盖的因子（key → override），供 MacroFactorService 消费。"""
        return {
            key: getattr(self, key)
            for key in MACRO_FACTOR_KEYS
            if getattr(self, key, None) is not None
        }

    def is_empty(self) -> bool:
        return not self.active()
