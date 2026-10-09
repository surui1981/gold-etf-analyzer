"""回测端点（V0.71.0）：参数扫描 + Sharpe / 最大回撤 / 校准曲线。

V0.79.0 Step G：新增 2 个端点（异步回测 + 结果查询）：
- ``POST /api/v1/backtest/run-async``：异步回测，返回 `task_id` 立即 202
- ``GET /api/v1/backtest/result/{task_id}``：轮询查询任务状态与结果

提供 2 个端点：
- ``POST /api/v1/backtest/run``：执行回测（5 分钟节流）
- ``GET /api/v1/backtest/coverage``：回测数据覆盖期报告

回测预设配置（GET/PUT）挂在 settings 模块下：
- ``GET /api/v1/settings/backtest``
- ``PUT /api/v1/settings/backtest``
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.dependencies import (
    get_backtest_service,
    get_setting_repository,
    get_task_registry,
)
from app.middleware.admin_auth import require_admin_session
from app.repositories.settings import SettingRepository
from app.schemas.backtest import (
    BacktestConfigIn,
    BacktestConfigOut,
    BacktestCoverageOut,
    BacktestRequestIn,
    BacktestResultOut,
    BacktestTaskAcceptedOut,
    BacktestTaskResultOut,
)
from app.services import task_registry
from app.services.background import spawn as _spawn_background
from app.services.backtest import BacktestService
from app.services.settings import get_backtest_config, save_backtest_config
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/backtest", tags=["backtest"])


@router.post(
    "/run",
    response_model=BacktestResultOut,
    summary="执行回测（V0.71.0）",
    dependencies=[Depends(require_admin_session)],
)
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
    target: str = Query("etf", pattern="^(ny|etf|gram|silver_ny|silver_etf|silver_gram)$"),
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


# ─────────────── V0.79.0 Step G · 异步回测 + 任务查询 ───────────────


async def _run_backtest_task(
    task_id: str,
    payload: BacktestRequestIn,
    service: BacktestService,
) -> None:
    """后台任务包装：标记 running → 调 service.run() → 标记 completed/failed。

    必须捕获**所有**异常并标记 failed —— 否则任务状态会永远停在 running，
    客户端轮询超时前拿不到错误信息。
    """
    try:
        task_registry.start(task_id)
        result = await service.run(payload)
        task_registry.complete(task_id, result.model_dump())
        logger.info("Async backtest task %s completed", task_id)
    except Exception as exc:
        logger.exception("Async backtest task %s failed", task_id)
        task_registry.fail(task_id, f"{type(exc).__name__}: {exc}")


@router.post(
    "/run-async",
    response_model=BacktestTaskAcceptedOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="异步执行回测（V0.79.0 Step G）",
    dependencies=[Depends(require_admin_session)],
)
async def run_backtest_async(
    payload: BacktestRequestIn,
    response: Response,
    service: BacktestService = Depends(get_backtest_service),
    registry=Depends(get_task_registry),
) -> BacktestTaskAcceptedOut:
    """异步回测：注册任务 → 立即 202 返回 → 客户端轮询 ``GET /result/{task_id}``。

    触发条件：
      - 嵌套网格大（trend_5/macro_5 启用后 grid 上限 1000）；
      - 或前端「强制异步」开关打开（``asyncOn`` checkbox，UI 层控制）。

    与 ``POST /run`` 的区别：
      - ``/run`` 同步返回（5 分钟节流缓存层挡命中），单次请求最坏 30s+；
      - ``/run-async`` 不阻塞响应，202 + Location 头指向 result 端点。
    """
    task_id = registry.create()
    poll_url = f"/api/v1/backtest/result/{task_id}"
    response.headers["Location"] = poll_url

    # ⚠ 用 ``_spawn_background`` 启动后台协程（与 ``main.py:_spawn_background`` 同型
    # —— ``asyncio.create_task`` + 强引用 set，防止「任务还在跑却被 GC」）。
    # 任务生命期由 registry 管理（task_id 是查询入口）；如果异常未被
    # ``_run_backtest_task`` 捕获、状态永远 running，registry TTL=1h 会懒清过期条目。
    _spawn_background(_run_backtest_task(task_id, payload, service))

    entry = registry.get(task_id)
    assert entry is not None  # 刚刚 create 的
    return BacktestTaskAcceptedOut(
        task_id=task_id,
        poll_url=poll_url,
        accepted_at=entry.accepted_at,
    )


@router.get(
    "/result/{task_id}",
    response_model=BacktestTaskResultOut,
    summary="查询异步回测任务状态与结果（V0.79.0 Step G）",
)
async def get_backtest_result(
    task_id: str,
    registry=Depends(get_task_registry),
) -> BacktestTaskResultOut:
    """按 ``task_id`` 返回任务状态与可选结果。

    返回：
      - 404：task_id 未注册 / 已过期（TTL 1h）
      - 200 + status=pending/running：仅有时间戳，无 result
      - 200 + status=completed：含完整 ``BacktestResultOut``（model_dump 形态）
      - 200 + status=failed：含 error 字符串，无 result
    """
    entry = registry.get(task_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=f"task {task_id} not found (or expired)",
        )
    result_out: BacktestResultOut | None = None
    if entry.status == "completed" and entry.result is not None:
        result_out = BacktestResultOut(**entry.result)
    return BacktestTaskResultOut(
        task_id=entry.task_id,
        status=entry.status,
        accepted_at=entry.accepted_at,
        started_at=entry.started_at,
        finished_at=entry.finished_at,
        progress=entry.progress,
        error=entry.error,
        result=result_out,
    )
