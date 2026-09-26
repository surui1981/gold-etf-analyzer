"""告警规则（V0.74.0 N+18 · discriminated union 重构）。

V0.72.0 旧 schema 为扁平 boolean（level_crossing + volatility + quiet_hours）。
V0.74.0 升级为 ``rules: list[RuleSpec]`` + 4 种 kind：
  - volatility    单日波动 ≥ 阈值
  - crossing      指数跨档（主轴 2 档 / 细粒度 4 档）
  - window        自定义时段（quiet 反义 / active 仅窗口内才推）
  - t_plus_n      信号后第 N 天实际涨跌达预测方向 + 阈值（接 review/calibration）

向后兼容：PUT 旧扁平字段（level_crossing_enabled / volatility_enabled / volatility_pct
+ quiet_hours）时由 ``_legacy_migrate`` 自动转换为 list[RuleSpec]。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# V0.72.0：通知渠道 4 选 1（与 UI 通知偏好勾选对应）
NotifyChannel = Literal["browser", "webpush", "email", "wechat"]

# V0.74.0 N+18：规则 kind 枚举（discriminator）
RuleKind = Literal["volatility", "crossing", "window", "t_plus_n"]


class QuietHours(BaseModel):
    """V0.72.0 旧版静默时段（HH:MM 格式，BJT）。V0.74.0 N+18 仍保留，
    作为 window mode='quiet' 的单实例兼容壳；新规则统一用 WindowSpec。"""

    start: str = Field(
        "22:00",
        description="静默起始（HH:MM，BJT）",
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$",
    )
    end: str = Field(
        "07:00",
        description="静默结束（HH:MM，BJT）",
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$",
    )


class WindowSpec(BaseModel):
    """V0.74.0 N+18 · 自定义时段窗口。

    mode='quiet'  ── 该时段内告警入队不推送（兼容旧 QuietHours 语义）
    mode='active' ── 仅该时段内才推送（反向）
    """

    mode: Literal["quiet", "active"] = Field(
        "quiet",
        description="quiet=静默 / active=仅窗口内才推送",
    )
    start: str = Field(
        "22:00",
        description="窗口起始 HH:MM BJT",
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$",
    )
    end: str = Field(
        "07:00",
        description="窗口结束 HH:MM BJT（跨夜:start > end）",
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$",
    )
    weekdays: list[int] | None = Field(
        None,
        description="0=周一 ... 6=周日;None=每天;列表内才生效",
    )


# ── 4 种 RuleSpec(以 kind 为 discriminator 的 union) ──


class _Base(BaseModel):
    """RuleSpec 共用字段。"""

    enabled: bool = Field(True, description="是否启用；False 时该规则永不触发")
    note: str = Field("", max_length=120, description="用户备注（前端展示）")


class VolatilityRule(_Base):
    """单日波动告警：纽约金 |日涨跌幅| ≥ 阈值。"""

    kind: Literal["volatility"]
    threshold_pct: float = Field(3.0, ge=0.1, le=20.0, description="波动阈值百分比 0.1-20")


class CrossingRule(_Base):
    """指数跨档：主轴 2 档 (BULLISH↔BEARISH) 或 4 档 (UP/STRONG_UP/DOWN/STRONG_DOWN)。
    axis_levels=2 时与旧版 level_crossing_enabled 等价；=4 时细粒度跨档。
    """

    kind: Literal["crossing"]
    axis_levels: int = Field(2, description="档位粒度:2=主轴 / 4=细粒度(含 STRONG_UP/STRONG_DOWN)")


class WindowRule(_Base):
    """自定义时段：quiet/active 双模式。"""

    kind: Literal["window"]
    window: WindowSpec = Field(default_factory=WindowSpec)


class TPlusNRule(_Base):
    """T+N 命中：过去 N 个交易日内有 buy/sell 信号,当前价相对信号日涨跌
    达预测方向 + 阈值时触发。接 review/calibration 数据源。
    """

    kind: Literal["t_plus_n"]
    t_plus_n_days: int = Field(3, ge=1, le=30, description="回看天数 N(1-30 交易日)")
    t_plus_n_pct: float = Field(1.5, ge=0.1, le=10.0, description="命中阈值百分比 0.1-10")


RuleSpec = Annotated[
    VolatilityRule | CrossingRule | WindowRule | TPlusNRule,
    Field(discriminator="kind"),
]


class AlertRuleIn(BaseModel):
    """V0.74.0 N+18 · 用户提交的告警规则。"""

    # 新规则列表（主字段）
    rules: list[RuleSpec] = Field(
        default_factory=list,
        description="V0.74.0 · 异构规则列表（volatility/crossing/window/t_plus_n）",
    )
    # 旧字段保留（向后兼容 PUT；model_validator 自动迁移到 rules）
    level_crossing_enabled: bool | None = Field(
        None,
        description="V0.72.0 旧字段;None 表示未传",
    )
    volatility_enabled: bool | None = Field(None, description="V0.72.0 旧字段")
    volatility_pct: float | None = Field(None, ge=0.1, le=20.0, description="V0.72.0 旧字段")
    quiet_hours: QuietHours | None = Field(None, description="V0.72.0 旧字段")
    # 共用
    channels: list[NotifyChannel] = Field(
        default_factory=lambda: ["browser"],
        description="推送渠道",
    )

    @field_validator("channels")
    @classmethod
    def _check_unique(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("channels 至少包含 1 个渠道")
        seen = set()
        for ch in value:
            if ch in seen:
                raise ValueError(f"channels 重复：{ch}")
            seen.add(ch)
        return value

    @model_validator(mode="before")
    @classmethod
    def _legacy_migrate(cls, data: Any) -> Any:
        """V0.72.0 → V0.74.0 向后兼容：旧扁平字段 → rules 列表。

        规则：
          - 若 PUT 体同时含 rules 与旧字段 → rules 优先(新格式),旧字段忽略
          - 若 PUT 体仅含旧字段 → 自动构造 rules 列表
            - level_crossing_enabled=True  → crossingRule(axis=2)
            - volatility_enabled=True      → volatilityRule(pct=volatility_pct)
            - quiet_hours 非空              → windowRule(mode=quiet)
          - 若两者都为空 → 保持默认空 rules 列表
        """
        if not isinstance(data, dict):
            return data
        has_new = "rules" in data and data["rules"] is not None
        legacy_keys = {
            "level_crossing_enabled",
            "volatility_enabled",
            "volatility_pct",
            "quiet_hours",
        }
        has_legacy = any(data.get(k) is not None for k in legacy_keys)
        if has_new or not has_legacy:
            return data  # 新格式或不需迁移,直通
        migrated: list[dict] = []
        if data.get("level_crossing_enabled"):
            migrated.append({"kind": "crossing", "axis_levels": 2, "enabled": True})
        if data.get("volatility_enabled"):
            migrated.append(
                {
                    "kind": "volatility",
                    "threshold_pct": data.get("volatility_pct") or 3.0,
                    "enabled": True,
                }
            )
        qh = data.get("quiet_hours")
        if qh:
            # qh 可能是 dict(PUT 直传)或 QuietHours model(从 DB 回放);都安全取字段
            qh_start = qh["start"] if isinstance(qh, dict) else getattr(qh, "start", "22:00")
            qh_end = qh["end"] if isinstance(qh, dict) else getattr(qh, "end", "07:00")
            migrated.append(
                {
                    "kind": "window",
                    "window": {"mode": "quiet", "start": qh_start, "end": qh_end},
                    "enabled": True,
                }
            )
        data["rules"] = migrated
        return data


class AlertRuleOut(AlertRuleIn):
    """告警规则输出（含保存时间）。"""

    updated_at: datetime | None = Field(None)


class AlertTestResult(BaseModel):
    """测试发送结果（POST /settings/test-email + test-wechat 返回）。"""

    channel: NotifyChannel
    success: bool
    message: str = Field("", description="成功 / 失败原因摘要")


class AlertEventIn(BaseModel):
    """手工触发告警（POST /settings/test-alert 入参，调试用）。"""

    subject: str = Field(..., min_length=1, max_length=200, description="告警标题")
    body: str = Field("", description="告警正文（可空）")
    channels: list[NotifyChannel] | None = Field(
        None,
        description="覆盖默认 channels；为空则用 AlertRule.channels",
    )


__all__ = [
    "AlertEventIn",
    "AlertRuleIn",
    "AlertRuleOut",
    "AlertTestResult",
    "CrossingRule",
    "QuietHours",
    "RuleKind",
    "RuleSpec",
    "TPlusNRule",
    "VolatilityRule",
    "WindowRule",
    "WindowSpec",
]
