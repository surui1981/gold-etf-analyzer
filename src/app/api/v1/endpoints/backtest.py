"""回测端点（V0.71.0）：参数扫描 + Sharpe / 最大回撤 / 校准曲线。

提供 2 个端点：
- ``POST /api/v1/backtest/run``：执行回测（5 分钟节流）
- ``GET /api/v1/backtest/coverage``：回测数据覆盖期报告

回测预设配置（GET/PUT）挂在 settings 模块下：
- ``GET /api/v1/settings/backtest``
- ``PUT /api/v1/settings/backtest``
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.dependencies import (
    get_backtest_service,
    get_setting_repository,
)
from app.repositories.settings import SettingRepository
from app.schemas.backtest import (
    BacktestConfigIn,
    BacktestConfigOut,
    BacktestCoverageOut,
    BacktestRequestIn,
    BacktestResultOut,
)
from app.services.backtest import BacktestService
from app.services.settings import get_backtest_config, save_backtest_config

router = APIRouter(prefix="/backtest", tags=["backtest"])


@router.post("/run", response_model=BacktestResultOut, summary="执行回测（V0.71.0）")
async def run_backtest(
    payload: BacktestRequestIn,
    response: Response,
    service: BacktestService = Depends(get_backtest_service),
) -> BacktestResultOut:
    """执行参数扫描：5 分钟节流命中时返回 cached=True + X-Backtest-Cached header。

    请求体包含 days / target / weight_grid（3 维）/ threshold_bands（4 节点阈值）；
    网格组合数 > 125（5×5×5）时由 Schema 校验拒绝。
    """
    result = await service.run(payload)
    response.headers["X-Backtest-Cached"] = "true" if result.cached else "false"
    return result


@router.get(
    "/coverage",
    response_model=BacktestCoverageOut,
    summary="回测数据覆盖期报告",
)
async def backtest_coverage(
    target: str = Query("etf", pattern="^(ny|etf|gram|silver_ny|silver_etf)$"),
    days: int = Query(90, ge=20, le=365),
    service: BacktestService = Depends(get_backtest_service),
) -> BacktestCoverageOut:
    """报告 daily_snapshots 覆盖期与可用样本天数（V0.71.0 必填：明示样本窗口）。"""
    return await service.coverage(target=target, days=days)


# ─────────────── 回测预设配置（settings） ───────────────


@router.get("/config", response_model=BacktestConfigOut, summary="获取回测预设配置")
async def get_backtest_config_endpoint(
    repo: SettingRepository = Depends(get_setting_repository),
) -> BacktestConfigOut:
    """读取用户保存的回测配置（未配置返回默认 60s 缓存模型）。"""
    return await get_backtest_config(repo)


@router.put("/config", response_model=BacktestConfigOut, summary="保存回测预设配置")
async def save_backtest_config_endpoint(
    config: BacktestConfigIn,
    repo: SettingRepository = Depends(get_setting_repository),
) -> BacktestConfigOut:
    """保存回测配置到 settings 表（key='backtest_config'）。"""
    try:
        return await save_backtest_config(repo, config)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc