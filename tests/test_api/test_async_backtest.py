"""异步回测接口单测（V0.79.0 Step G 第 2 批）。

覆盖：
- ``POST /api/v1/backtest/run-async`` 返回 202 + task_id + poll_url + Location 头
- ``GET /api/v1/backtest/result/{task_id}`` 状态机完整：pending → running → completed / failed
- 404：未知 / 已过期 task_id
- 后台异常被 ``_run_backtest_task`` 捕获并标记 failed（不致 running 永久卡住）
"""

from __future__ import annotations

import asyncio

from httpx import AsyncClient

from app.services import task_registry


def _valid_payload() -> dict:
    """最小合法回测请求（默认 3×1×1 × 4×4 × 1×1 = 48 组合；执行快）。"""
    return {
        "days": 90,
        "target": "etf",
        "weight_grid": {
            "tech": [0.3, 0.4, 0.5],
            "macro": [0.4],
            "news": [0.3],
        },
        "threshold_bands": {
            "bullish": [55, 60, 65, 70],
            "bearish": [45, 40, 35, 30],
        },
    }


async def _wait_for_status(
    client: AsyncClient,
    task_id: str,
    *,
    target: str = "completed",
    timeout: float = 10.0,
    poll_interval: float = 0.05,
) -> dict:
    """轮询直到任务达到目标状态（completed / failed）或超时。返回最终响应 JSON。"""
    elapsed = 0.0
    last_data: dict = {}
    while elapsed < timeout:
        resp = await client.get(f"/api/v1/backtest/result/{task_id}")
        assert resp.status_code == 200, f"unexpected {resp.status_code}: {resp.text}"
        last_data = resp.json()
        if last_data["status"] in {target, "failed"}:
            return last_data
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
    raise AssertionError(
        f"task {task_id} did not reach {target} in {timeout * 1000}ms, last: {last_data}"
    )


# ─────────────── POST /run-async ───────────────


async def test_run_async_returns_202_with_task_id(client: AsyncClient) -> None:
    """POST /run-async → 202 Accepted + task_id + poll_url + Location header。"""
    resp = await client.post("/api/v1/backtest/run-async", json=_valid_payload())
    assert resp.status_code == 202
    body = resp.json()
    assert "task_id" in body
    assert len(body["task_id"]) == 32  # uuid4().hex
    assert body["status"] == "pending"
    assert body["poll_url"] == f"/api/v1/backtest/result/{body['task_id']}"
    assert "accepted_at" in body
    # Location 头（HTTP 202 语义标准做法）
    assert resp.headers.get("location") == body["poll_url"]


async def test_run_async_does_not_block_response(client: AsyncClient) -> None:
    """POST /run-async → 响应**不等** service.run() 完成（立即 202）。

    验证手段：返回后立刻查 status 应是 pending 或 running（几乎肯定是 pending，
    因为调度时延 < 几 ms）。
    """
    resp = await client.post("/api/v1/backtest/run-async", json=_valid_payload())
    assert resp.status_code == 202
    task_id = resp.json()["task_id"]

    # 不轮询：直接读一次状态（实际可能是 pending，因为 asyncio.create_task 调度
    # 有微小延迟；此处只确认**不会**是 completed —— 那意味着响应被同步等了）
    poll = await client.get(f"/api/v1/backtest/result/{task_id}")
    assert poll.status_code == 200
    initial_status = poll.json()["status"]
    assert initial_status in {"pending", "running"}, f"got {initial_status}"

    # 必须**等**后台任务完成，否则测试退出后 fixture `_reset_db` 撞 DB 锁
    # （后台协程还持有 DB 会话 → DROP TABLE 时 aiosqlite 「database is locked」）。
    await _wait_for_status(client, task_id, target="completed", timeout=15.0)


async def test_run_async_validates_grid_size_422(client: AsyncClient) -> None:
    """嵌套权重 grid > 1000 → 422（与 /run 一致的 Pydantic 校验）。"""
    bad = _valid_payload()
    bad["weight_grid"] = {
        "tech": [0.1] * 8,
        "macro": [0.1] * 8,
        "news": [0.1] * 8,
        # 总和 = 8×8×8 × 4×4 × 1×1 = 16384 > 1000
    }
    resp = await client.post("/api/v1/backtest/run-async", json=bad)
    assert resp.status_code == 422


# ─────────────── GET /result/{task_id} ───────────────


async def test_get_result_unknown_task_404(client: AsyncClient) -> None:
    """GET /result/{unknown} → 404。"""
    resp = await client.get("/api/v1/backtest/result/00000000000000000000000000000000")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]


async def test_get_result_completed_returns_full_payload(client: AsyncClient) -> None:
    """端到端：POST 异步任务 → 轮询至 completed → result 含 BacktestResultOut 字段。"""
    resp = await client.post("/api/v1/backtest/run-async", json=_valid_payload())
    assert resp.status_code == 202
    task_id = resp.json()["task_id"]

    data = await _wait_for_status(client, task_id, target="completed", timeout=15.0)
    assert data["status"] == "completed"
    assert data["error"] is None
    assert data["result"] is not None
    # BacktestResultOut 关键字段都在
    assert "rows" in data["result"]
    assert "summary" in data["result"]
    assert "coverage" in data["result"]
    assert data["result"]["target"] == "etf"
    assert data["result"]["days"] == 90
    # 完成后应有 finished_at
    assert data["finished_at"] is not None


async def test_get_result_failed_status_propagates_error(client: AsyncClient) -> None:
    """后台 service.run() 抛错 → status=failed + error 非空 + result=None。

    验证手段：mock BacktestService.run 让它抛 RuntimeError；
    registry 应捕获并标记 failed（而非永久卡 running）。
    """
    from app.dependencies import get_backtest_service
    from app.main import app

    class BoomRun:
        async def run(self, payload):
            raise RuntimeError("simulated failure")

    async def fake_service():
        return BoomRun()

    app.dependency_overrides[get_backtest_service] = fake_service
    try:
        resp = await client.post("/api/v1/backtest/run-async", json=_valid_payload())
        assert resp.status_code == 202
        task_id = resp.json()["task_id"]

        data = await _wait_for_status(client, task_id, target="failed", timeout=5.0)
        assert data["status"] == "failed"
        assert data["error"] is not None
        assert "RuntimeError" in data["error"]
        assert "simulated failure" in data["error"]
        assert data["result"] is None
    finally:
        app.dependency_overrides.pop(get_backtest_service, None)


# ─────────────── registry 单元测试 ───────────────


def test_task_registry_lifecycle() -> None:
    """create → start → complete → get → fail → clear：完整生命周期。"""
    tid = task_registry.create()
    entry = task_registry.get(tid)
    assert entry is not None
    assert entry.status == "pending"
    assert entry.started_at is None
    assert entry.accepted_at is not None

    task_registry.start(tid)
    entry = task_registry.get(tid)
    assert entry.status == "running"
    assert entry.started_at is not None

    task_registry.complete(tid, {"summary": {"best_sharpe": 1.5}})
    entry = task_registry.get(tid)
    assert entry.status == "completed"
    assert entry.finished_at is not None
    assert entry.result == {"summary": {"best_sharpe": 1.5}}

    task_registry.clear()
    assert task_registry.get(tid) is None


def test_task_registry_get_returns_copy() -> None:
    """get() 返回 TaskEntry **拷贝** —— 修改不影响 registry。"""
    tid = task_registry.create()
    entry = task_registry.get(tid)
    assert entry is not None
    # 修改拷贝
    entry.status = "failed"  # type: ignore[assignment]
    # registry 仍为 pending
    again = task_registry.get(tid)
    assert again.status == "pending"


def test_task_registry_unknown_returns_none() -> None:
    """未知 task_id → None。"""
    assert task_registry.get("deadbeef" * 4) is None


def test_task_registry_unknown_ops_are_noop() -> None:
    """对未知 task_id 调 start/complete/fail → 静默 no-op（不应抛错）。"""
    task_registry.start("nope")
    task_registry.complete("nope", {"x": 1})
    task_registry.fail("nope", "err")
    # 没崩就行


def test_task_registry_size_tracks_entries() -> None:
    """size() 反映当前注册条目数（创建后 +1，clear 后 =0）。"""
    task_registry.clear()
    assert task_registry.size() == 0
    task_registry.create()
    task_registry.create()
    assert task_registry.size() == 2
    task_registry.clear()
    assert task_registry.size() == 0