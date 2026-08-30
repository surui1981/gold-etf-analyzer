"""权重配置端点：读取/保存评估权重。"""

from fastapi import APIRouter, Depends

from app.dependencies import get_weight_service
from app.schemas.settings import WeightConfig
from app.services.settings import WeightService

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
