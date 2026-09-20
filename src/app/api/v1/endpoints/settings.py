"""权重配置端点：读取/保存评估权重。"""

from fastapi import APIRouter, Depends

from app.dependencies import get_setting_repository, get_weight_service
from app.repositories.settings import SettingRepository
from app.schemas.alert import AlertRuleIn, AlertRuleOut, AlertTestResult
from app.schemas.settings import WeightConfig
from app.services.notify import NotifierFactory
from app.services.settings import (
    WeightService,
    get_alert_rules,
    save_alert_rules,
)

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/weights", response_model=WeightConfig, summary="获取评估权重")
async def get_weights(
    service: WeightService = Depends(get_weight_service),
) -> WeightConfig:
    """返回当前权重（用户配置优先，未配置回退默认）。"""
    return await service.get_weights()


@router.put("/weights", response_model=WeightConfig, summary="保存评估权重")
async def save_weights(
    config: WeightConfig,
    service: WeightService = Depends(get_weight_service),
) -> WeightConfig:
    """保存权重（各组权重和须为 1，由 Schema 校验）。"""
    return await service.save_weights(config)


# ───────────────────── V0.72.0：告警规则 + 测试发送 ─────────────────────


@router.get("/alert-rules", response_model=AlertRuleOut, summary="获取告警规则")
async def get_alert_rules_endpoint(
    repo: SettingRepository = Depends(get_setting_repository),
) -> AlertRuleOut:
    """返回当前告警规则（档位穿越 / 波动阈值 / 静默时段 / 推送渠道）。"""
    return await get_alert_rules(repo)


@router.put("/alert-rules", response_model=AlertRuleOut, summary="保存告警规则")
async def put_alert_rules_endpoint(
    payload: AlertRuleIn,
    repo: SettingRepository = Depends(get_setting_repository),
) -> AlertRuleOut:
    """保存告警规则（schema 校验：channels 至少 1 项 + 不重复）。"""
    return await save_alert_rules(repo, payload)


@router.post("/test-email", response_model=AlertTestResult, summary="测试邮件发送")
async def test_email_endpoint() -> AlertTestResult:
    """发一封测试邮件到 NOTIFY_FROM 邮箱，验证 SMTP 配置正确。"""
    notifier = NotifierFactory.create("email")
    if notifier is None:
        return AlertTestResult(
            channel="email",
            success=False,
            message="SMTP 未配置（SMTP_HOST 为空）",
        )
    ok = await notifier.send(
        subject="黄金 ETF · 测试邮件",
        body="这是一封测试邮件，验证 SMTP 配置正确。\n\n如收到请忽略。",
    )
    return AlertTestResult(
        channel="email",
        success=ok,
        message="发送成功" if ok else "发送失败，详见 server.log",
    )


@router.post("/test-wechat", response_model=AlertTestResult, summary="测试微信发送")
async def test_wechat_endpoint() -> AlertTestResult:
    """发一条测试微信，验证 SendKey 配置正确。"""
    notifier = NotifierFactory.create("wechat")
    if notifier is None:
        return AlertTestResult(
            channel="wechat",
            success=False,
            message="SERVERCHAN_SENDKEY 未配置",
        )
    ok = await notifier.send(
        subject="黄金 ETF · 测试微信",
        body="这是一条测试消息，验证 Server 酱配置正确。\n\n如收到请忽略。",
    )
    return AlertTestResult(
        channel="wechat",
        success=ok,
        message="发送成功" if ok else "发送失败，详见 server.log",
    )