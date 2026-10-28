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

#: V0.118.x 的宏观面 8 因子**默认**权重（政府债务组加入前的默认）。
#:
#: 与 ``LEGACY_MACRO_DEFAULTS`` 同理：存量配置**恰好等于**这组值 ⇒ 用户从没
#: 自定义过（存的就是当时的默认值）⇒ 升级后应直接落到 V0.119.0 的新默认，
#: 而不是对旧默认做按比例缩放（那会得到 dxy 13.2% / cb_gold 22% 这类
#: 「谁都没设计过」的权重 —— 相对比例虽对，但绝对值是缩放出来的）。
#:
#: ⚠ 漏掉这个常量会有静默后果：8 键存量默认配置会走进按比例缩放分支，
#: 用户的「没动过权重」变成「权重被系统改过」。
LEGACY_MACRO_8_DEFAULTS: dict[str, float] = {
    "dxy": 0.15,
    "us2y": 0.06,
    "us10y": 0.08,
    "us30y": 0.06,
    "curve_10y2y": 0.10,
    "real10y": 0.20,
    "vix": 0.10,
    "cb_gold": 0.25,
}

#: V0.120.0 之前的**合成权重**默认（技术面 / 宏观面 / 消息面 三键）。
#:
#: V0.120.0 加入第 4 个面「资金流面」后，新默认变成 25 / 35 / 25 / 15。
#: 存量三键配置**恰好等于**这组值 ⇒ 用户从没自定义过 ⇒ 直接落到新默认；
#: 真正的自定义值 ⇒ 仍走按比例迁移（三个面缩到 85%，资金流面 15%），
#: 保留用户对三个面的相对偏好。
#:
#: ⚠ 漏掉这个常量会有静默后果：三键存量默认配置会走进按比例缩放分支，
#: 用户的「没动过权重」变成「权重被系统改过」（25.5/34/25.5/15 这类）。
LEGACY_COMBINE_3_DEFAULTS: dict[str, float] = {
    "tech": 0.30,
    "macro": 0.40,
    "news": 0.30,
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
    """宏观面 11 因子权重（V0.119.0 起）。

    分组：美元 13% / 名义利率（2Y+10Y+30Y）17% / 曲线形态 9% /
    实际利率 18% / 风险偏好 9% / 结构性需求 22% / 政府债务 12%（美5+中4+欧3）。

    V0.119.0：旧 8 个因子按 ×0.88 **等比缩放**（相对比例完全不动），
    腾出 12% 给新增的政府债务组 —— 详见 ``services/macro.py`` 的模块 docstring。
    """

    dxy: float = Field(0.13, ge=0, le=1, description="美元指数")
    us2y: float = Field(0.05, ge=0, le=1, description="美债2Y收益率")
    us10y: float = Field(0.07, ge=0, le=1, description="美债10Y收益率")
    us30y: float = Field(0.05, ge=0, le=1, description="美债30Y收益率")
    curve_10y2y: float = Field(0.09, ge=0, le=1, description="美债10Y-2Y利差")
    real10y: float = Field(0.18, ge=0, le=1, description="美债10Y实际利率")
    vix: float = Field(0.09, ge=0, le=1, description="VIX恐慌指数")
    cb_gold: float = Field(0.22, ge=0, le=1, description="国际央行购金量")
    us_gov_debt: float = Field(0.05, ge=0, le=1, description="美国政府债务/GDP")
    cn_gov_debt: float = Field(0.04, ge=0, le=1, description="中国政府债务/GDP")
    eu_gov_debt: float = Field(0.03, ge=0, le=1, description="欧洲政府债务/GDP")

    @model_validator(mode="before")
    @classmethod
    def _migrate_missing_factors(cls, data: Any) -> Any:
        """旧版配置 → 11 因子：新增因子按默认份额从旧因子里**按比例扣除**。

        **为什么必须做**：存进 ``app_settings`` 的权重 JSON 只有旧版那几��� key
        且合计 = 1.0。直接给新字段加默认值，合计会 > 1 →
        ``_sum_to_one`` 抛错 → ``services/settings.py::_load_weights`` 的异常兜底
        路径会**静默把用户的自定义权重重置为默认**（用户毫无察觉）。

        **迁移规则**：新增因子的默认份额（合计 ``add``）从旧因子里按各自占比扣除
        （等比例缩放，保留用户对各因子的相对偏好），再补上新因子的默认值。
        全部 key 都给全时**原样返回**，不做任何干预。

        **例外**（"旧默认值也是一种用户状态"）：存量配置**恰好等于某一版默认权重**
        （``LEGACY_MACRO_DEFAULTS`` = 5 键 / ``LEGACY_MACRO_8_DEFAULTS`` = 8 键）
        ⇒ 用户从没自定义过 ⇒ 直接落到**新默认**，不做按比例缩放。否则
        「没动过权重」的用户会拿到 dxy 13.2% / cb_gold 22% 这类从缩放算出来的
        权重。真正的自定义值不等于旧默认 ⇒ 仍走按比例迁移。
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
        for legacy in (LEGACY_MACRO_DEFAULTS, LEGACY_MACRO_8_DEFAULTS):
            if set(present) == set(legacy) and all(
                abs(present[k] - v) < 1e-9 for k, v in legacy.items()
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
            + self.us_gov_debt
            + self.cn_gov_debt
            + self.eu_gov_debt
        )
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"宏观面权重之和须为 1，当前 {total:.3f}")
        return self


class CombineWeightConfig(BaseModel):
    """综合指数合成权重：技术面 vs 宏观面 vs 消息面 vs **资金流面**（中短期 ETF 波段操作）。

    V0.120.0：新增第 4 个面 ``flow``（默认 15%），其余三个面等比降到
    25 / 35 / 25。存量 3 键配置由 ``_migrate_missing_face``（before 校验器）
    做**无损迁移** —— 不做迁移会让用户自定义的权重静默重置，见该方法 docstring。
    """

    tech: float = Field(0.25, ge=0, le=1, description="技术面占比（默认 25%）")
    macro: float = Field(0.35, ge=0, le=1, description="宏观面占比（默认 35%）")
    news: float = Field(0.25, ge=0, le=1, description="消息面占比（默认 25%，客户评估）")
    flow: float = Field(0.15, ge=0, le=1, description="资金流面占比（默认 15%，V0.120.0 新增）")

    @model_validator(mode="before")
    @classmethod
    def _migrate_missing_face(cls, data: Any) -> Any:
        """旧版 3 键配置 → 4 键：新增资金流面，其余三个面按比例缩放。

        **为什么必须做**：存进 ``app_settings`` 的合成权重 JSON 只有 tech/macro/news
        三键且合计 = 1.0。直接给新字段加默认值 0.15，合计会变成 1.15 →
        ``_sum_to_one`` 抛错 → ``services/settings.py::_load_weights`` 的异常兜底路径
        会**静默把用户的自定义权重重置为默认**（用户毫无察觉）。

        **迁移规则**：
        - 存量值**恰好等于** ``LEGACY_COMBINE_3_DEFAULTS``（旧默认值 30/40/30）
          ⇒ 用户从没自定义过 ⇒ 直接落到**新默认** 25/35/25/15；
        - 否则（真正的自定义值）⇒ 三个面按原相对比例缩放到 85%，资金流面取 15%。
        """
        if not isinstance(data, dict):
            return data
        if "flow" in data:
            return data
        present: dict[str, float] = {}
        for k in ("tech", "macro", "news"):
            v = data.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                present[k] = float(v)
        if not present:
            return data
        legacy = LEGACY_COMBINE_3_DEFAULTS
        if set(present) == set(legacy) and all(
            abs(present[k] - v) < 1e-9 for k, v in legacy.items()
        ):
            # 「用户从没自定义过」⇒ 直接换成新默认（而不是对旧默认做按比例缩放）
            return {
                "tech": 0.25,
                "macro": 0.35,
                "news": 0.25,
                "flow": 0.15,
            }
        flow = 0.15
        base = sum(present.values())
        if base <= 0:
            return data
        scale = max(0.0, base - flow) / base
        migrated = {k: round(v * scale, 6) for k, v in present.items()}
        migrated["flow"] = flow
        total = sum(migrated.values())
        if abs(total - 1.0) > 1e-9:
            anchor = max(migrated, key=migrated.get)
            migrated[anchor] = round(migrated[anchor] + (1.0 - total), 6)
        return migrated

    @model_validator(mode="after")
    def _sum_to_one(self) -> "CombineWeightConfig":
        total = self.tech + self.macro + self.news + self.flow
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"合成权重之和须为 1，当前 {total:.3f}")
        return self


class MoneyFlowWeightConfig(BaseModel):
    """资金流面 6 因子权重（V0.120.0 新增）。

    周频 54% / 月频 46%：

    ==================  ==========  =====  ==================================
    因子                  节奏         权重  符号
    ==================  ==========  =====  ==================================
    ``cot_gold_net``     周           18%   + 投机净多占 OI 越高越利多黄金
    ``cot_gold_flow``    周           14%   + 4 周净多增加 = 钱正在买黄金
    ``gold_etf_flow``    周           22%   + 4 周累计净申购（国内真金白银进场）
    ``us_liq_net``       月           14%   + 美元净流动性扩张利多黄金
    ``cn_margin_flow``   月           16%   − 股市杠杆撤退 = 黄金机会成本下降
    ``cn_money_gap``     月           16%   − 剪刀差走阔 = 存款淤积 = 抗通胀需求升
    ==================  ==========  =====  ==================================

    ``gold_etf_flow`` 权重最高（22%）：它是**唯一直接度量「国内的钱有没有买黄金」**
    的因子，而本项目的用户就是国内黄金 ETF 持有人。
    """

    cot_gold_net: float = Field(0.18, ge=0, le=1, description="黄金投机净多占 OI")
    cot_gold_flow: float = Field(0.14, ge=0, le=1, description="黄金投机净多 4 周变化")
    gold_etf_flow: float = Field(0.22, ge=0, le=1, description="黄金ETF 4 周累计净申赎")
    us_liq_net: float = Field(0.14, ge=0, le=1, description="美元净流动性 4 周变化")
    cn_margin_flow: float = Field(0.16, ge=0, le=1, description="A股融资余额月变动")
    cn_money_gap: float = Field(0.16, ge=0, le=1, description="中国 M1-M2 剪刀差")

    @model_validator(mode="after")
    def _sum_to_one(self) -> "MoneyFlowWeightConfig":
        total = (
            self.cot_gold_net
            + self.cot_gold_flow
            + self.gold_etf_flow
            + self.us_liq_net
            + self.cn_margin_flow
            + self.cn_money_gap
        )
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"资金流面权重之和须为 1，当前 {total:.3f}")
        return self


class WeightConfig(BaseModel):
    """完整权重配置（GET/PUT /settings/weights）。"""

    trend: TrendWeightConfig = Field(default_factory=TrendWeightConfig)
    macro: MacroWeightConfig = Field(default_factory=MacroWeightConfig)
    combine: CombineWeightConfig = Field(default_factory=CombineWeightConfig)
    flow: MoneyFlowWeightConfig = Field(default_factory=MoneyFlowWeightConfig)
    # V0.79.0 Step F：技术面 5 维度合成方式开关。True=组内平均（默认；降低内部相关性），
    # False=单维度加权（历史行为，向后兼容）。不影响宏观/消息面合成。
    group_combine: bool = Field(
        True,
        description="技术面 5 维度是否按组内平均合成（V0.79.0 Step F，默认开启）",
    )


# ───────────────────── V0.110.0：宏观因子手动校准 ─────────────────────

#: 手动校准覆盖的因子集合（与 ``services/macro.py::MACRO_FACTOR_RULES`` 的 key 一一对应）
#: V0.118.0：5 → 8（新增 us2y / curve_10y2y / real10y）
#: V0.119.0：8 → 11（新增 us_gov_debt / cn_gov_debt / eu_gov_debt）
MACRO_FACTOR_KEYS: tuple[str, ...] = (
    "dxy",
    "us2y",
    "us10y",
    "us30y",
    "curve_10y2y",
    "real10y",
    "vix",
    "cb_gold",
    "us_gov_debt",
    "cn_gov_debt",
    "eu_gov_debt",
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
    """11 个宏观因子的手动覆盖集合；``None`` 表示该因子走自动数据源。"""

    dxy: MacroFactorOverride | None = None
    us2y: MacroFactorOverride | None = None
    us10y: MacroFactorOverride | None = None
    us30y: MacroFactorOverride | None = None
    curve_10y2y: MacroFactorOverride | None = None
    real10y: MacroFactorOverride | None = None
    vix: MacroFactorOverride | None = None
    cb_gold: MacroFactorOverride | None = None
    us_gov_debt: MacroFactorOverride | None = None
    cn_gov_debt: MacroFactorOverride | None = None
    eu_gov_debt: MacroFactorOverride | None = None

    def active(self) -> dict[str, MacroFactorOverride]:
        """返回已设置覆盖的因子（key → override），供 MacroFactorService 消费。"""
        return {
            key: getattr(self, key)
            for key in MACRO_FACTOR_KEYS
            if getattr(self, key, None) is not None
        }

    def is_empty(self) -> bool:
        return not self.active()
