"""告警规则（V0.72.0）：档位穿越 / 单日波动阈值 + 推送渠道偏好 + 静默时段。

落库到 ``app_settings`` 表（key='alert_rules'），与 weight_config / backtest_config 共表。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# V0.72.0：通知渠道 4 选 1（与 UI 通知偏好勾选对应）
NotifyChannel = Literal["browser", "webpush", "email", "wechat"]


class QuietHours(BaseModel):
    """静默时段（HH:MM 格式，BJT 时区）。该时段内告警入队但不推送。"""

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


class AlertRuleIn(BaseModel):
    """用户提交的告警规则（PUT /settings/alert-rules 入参）。"""

    level_crossing_enabled: bool = Field(
        True,
        description="档位穿越告警（指数跨档时触发：≥75 strong_up / ≥55 up / ≥45 sideways / ≥25 down）",
    )
    volatility_enabled: bool = Field(
        True,
        description="单日波动告警（按 volatility_pct 阈值）",
    )
    volatility_pct: float = Field(
        3.0,
        ge=0.1,
        le=20.0,
        description="单日波动阈值百分比（绝对值 ≥ 此值触发；默认 3.0）",
    )
    quiet_hours: QuietHours = Field(
        default_factory=QuietHours,
        description="静默时段（BJT）",
    )
    channels: list[NotifyChannel] = Field(
        default_factory=lambda: ["browser"],
        description="推送渠道偏好（browser / webpush / email / wechat），按顺序尝试",
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

    @model_validator(mode="after")
    def _check_channels_match_enabled(self) -> AlertRuleIn:
        """至少 1 个渠道偏好启用。"""
        if not self.channels:
            raise ValueError("channels 至少 1 项")
        return self


class AlertRuleOut(AlertRuleIn):
    """告警规则输出（含保存时间）。"""

    updated_at: datetime | None = Field(
        None,
        description="上次保存时间（BJT）",
    )


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