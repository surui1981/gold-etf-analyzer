"""权重配置端点：读取/保存评估权重。"""

from fastapi import APIRouter, Depends

from app.dependencies import get_setting_repository, get_weight_service
from app.middleware.admin_auth import require_admin_session
from app.repositories.settings import SettingRepository
from app.schemas.alert import AlertRuleIn, AlertRuleOut, AlertTestResult
from app.schemas.settings import MacroFactorOverrideSet, WeightConfig
from app.services.macro import clear_macro_cache
from app.services.notify import NotifierFactory
from app.services.settings import (
    WeightService,
    get_alert_rules,
    save_alert_rules,
)
from app.services.trend import TrendService

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/weights", response_model=WeightConfig, summary="获取评估权重")
async def get_weights(
    service: WeightService = Depends(get_weight_service),
) -> WeightConfig:
    """返回当前权重（用户配置优先，未配置回退默认）。"""
    return await service.get_weights()


@router.put(
    "/weights",
    response_model=WeightConfig,
    summary="保存评估权重",
    dependencies=[Depends(require_admin_session)],
)
async def save_weights(
    config: WeightConfig,
    service: WeightService = Depends(get_weight_service),
) -> WeightConfig:
    """保存权重（各组权重和须为 1，由 Schema 校验）。

    V0.110.0：保存后必须失效 ``served_cache`` —— 权重直接参与综合指数合成，
    不失效的话用户保存完看到的仍是旧指数（默认 600s），与"保存没生效"无法区分。
    """
    saved = await service.save_weights(config)
    clear_macro_cache()  # 宏观面内部用 group_by 权重，同样是宏观评分的输入
    TrendService.invalidate_cached_results()
    return saved


# ───────────────────── V0.110.0：宏观因子手动校准 ─────────────────────


@router.get(
    "/macro-overrides",
    response_model=MacroFactorOverrideSet,
    summary="获取宏观因子手动覆盖",
)
async def get_macro_overrides(
    service: WeightService = Depends(get_weight_service),
) -> MacroFactorOverrideSet:
    """返回用户手动校准的宏观因子读数（未设置过则 5 项全为 null）。

    公开读：页面需要显示"当前生效的手动值 vs 自动源值"，与 ``/settings/weights``
    保持同样的读权限口径。
    """
    return await service.macro_overrides()


@router.put(
    "/macro-overrides",
    response_model=MacroFactorOverrideSet,
    summary="保存宏观因子手动覆盖",
    dependencies=[Depends(require_admin_session)],
)
async def put_macro_overrides(
    payload: MacroFactorOverrideSet,
    service: WeightService = Depends(get_weight_service),
) -> MacroFactorOverrideSet:
    """整体替换宏观因子手动覆盖（传全 null 即清除全部覆盖）。

    ``dxy`` / ``vix`` 无自动源、长期停在 2026-08-28 的静态常量；本端点允许用户
    从行情终端抄入当日真实读数顶替。

    保存后要失效**两层**缓存：``MacroFactorService._CACHE``（600s）与
    ``TrendService`` 的 ``served_cache``（600s，在前者之上）。只清前者时
    ``/market/gold/trend`` 会从 served_cache 回放覆盖前的响应 —— 实测确认：
    覆盖已落库、GET 仍返回 ``dxy 96.5 · 2026-08-28``。
    """
    saved = await service.save_macro_overrides(payload)
    clear_macro_cache()
    TrendService.invalidate_cached_results()
    return saved


# ───────────────────── V0.72.0：告警规则 + 测试发送 ─────────────────────


@router.get("/alert-rules", response_model=AlertRuleOut, summary="获取告警规则")
async def get_alert_rules_endpoint(
    repo: SettingRepository = Depends(get_setting_repository),
) -> AlertRuleOut:
    """返回当前告警规则（档位穿越 / 波动阈值 / 静默时段 / 推送渠道）。"""
    return await get_alert_rules(repo)


@router.put(
    "/alert-rules",
    response_model=AlertRuleOut,
    summary="保存告警规则",
    dependencies=[Depends(require_admin_session)],
)
async def put_alert_rules_endpoint(
    payload: AlertRuleIn,
    repo: SettingRepository = Depends(get_setting_repository),
) -> AlertRuleOut:
    """保存告警规则（schema 校验：channels 至少 1 项 + 不重复）。"""
    return await save_alert_rules(repo, payload)


@router.post(
    "/test-email",
    response_model=AlertTestResult,
    summary="测试邮件发送",
    dependencies=[Depends(require_admin_session)],
)
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


@router.post(
    "/test-wechat",
    response_model=AlertTestResult,
    summary="测试微信发送",
    dependencies=[Depends(require_admin_session)],
)
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
