"""健康检查端点。"""

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings

router = APIRouter(tags=["health"])


@router.get("/health", summary="服务健康检查")
async def health_check(
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """返回服务存活状态与运行环境信息。"""
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.app_env,
    }
