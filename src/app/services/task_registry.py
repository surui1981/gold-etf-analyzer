"""异步任务注册表（V0.79.0 Step G）。

为回测等长耗时操作提供 ``task_id`` → 状态查询通道。设计：

- 模块级 ``dict[task_id, TaskEntry]`` + ``threading.Lock``（与 ``backtest_throttle``
  同型 —— 仅 microsecond 级 dict 突变，``threading.Lock`` 已足够，
  与项目内 ``cache.py:32`` / ``central_bank_data.py:102`` 保持一致）；
- ``task_id`` 形如 ``uuid4().hex``（32 hex），与 ``middleware/trace.py:53`` 一致；
- 生命周期：``pending → running → completed / failed``；
- TTL 1 小时（懒过期）；``MAX_ENTRIES = 256`` 超限 eager-evict；
- 无持久化（与 ``backtest_throttle`` 一致；进程重启则 in-flight 任务丢失），
  契合项目「单机部署、不跨进程」定位。

调用方：

  - ``POST /api/v1/backtest/run-async`` 接收请求 → ``create()`` 注册 →
    ``asyncio.create_task(_run(...))`` → 立即返回 202 + ``task_id``；
  - 后台协程负责 ``start() → service.run() → complete() / fail()``；
  - ``GET /api/v1/backtest/result/{task_id}`` 由 ``get(task_id)`` 返回当前状态。

⚠ **V0.79.0 Step G 不做**（写入 V0.79.x 维护线）：
  - 进度上报 —— ``progress`` 字段接口已留位，但实际按行号 / 时间片估算
    留 V0.79.1；
  - ``lifespan`` 关闭时的 ``cancel_all()`` —— 当前与 ``scheduler.py`` 行为
    一致（直接 GC），无清理钩子；
  - 持久化到 SQLite —— 与项目其它 in-memory cache 同型，无需跨进程。
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

TaskStatus = Literal["pending", "running", "completed", "failed"]

# TTL 1 小时：回测通常 5~30s，1 小时远大于实际需要；用于测试 / 客户端拉取
# 历史较慢的情况。过期条目在 ``get()`` 时被懒清。
TTL_SECONDS = 3600

# 最大并发 / 累计条目数：超过则清空全部（罕见，10× 较实际场景宽松）
MAX_ENTRIES = 256


@dataclass
class TaskEntry:
    """单任务状态快照。"""

    task_id: str
    status: TaskStatus
    accepted_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: float | None = None  # 0.0–1.0；V0.79.0 接口位，不主动更新
    error: str | None = None
    result: dict[str, Any] | None = None  # completed 时填充（model_dump() 形式）


_LOCK = threading.Lock()
_ENTRIES: dict[str, TaskEntry] = {}


def _now() -> datetime:
    return datetime.now()


def _eager_evict_if_oversized() -> None:
    """满 MAX_ENTRIES 直接清空（极端参数扫描场景的兜底）。"""
    if len(_ENTRIES) >= MAX_ENTRIES:
        _ENTRIES.clear()


def _purge_expired() -> None:
    """懒清已过期条目（不持有锁版本，调用方负责）。"""
    cutoff = _now() - timedelta(seconds=TTL_SECONDS)
    expired = [tid for tid, e in _ENTRIES.items() if e.accepted_at < cutoff]
    for tid in expired:
        _ENTRIES.pop(tid, None)


def create() -> str:
    """注册新任务（status=pending），返回 task_id。

    UUID4 hex —— 32 字符，碰撞概率 ~2⁻¹²⁸，实际为零。
    """
    task_id = uuid.uuid4().hex
    with _LOCK:
        _eager_evict_if_oversized()
        _ENTRIES[task_id] = TaskEntry(
            task_id=task_id,
            status="pending",
            accepted_at=_now(),
        )
    return task_id


def start(task_id: str) -> None:
    """标记任务进入 running。未注册时静默 no-op（不应发生 —— 仅在 race 下）。"""
    with _LOCK:
        entry = _ENTRIES.get(task_id)
        if entry is None:
            return
        entry.status = "running"
        entry.started_at = _now()


def set_progress(task_id: str, progress: float) -> None:
    """更新进度（V0.79.0 Step G 接口预留，不主动调用）。"""
    with _LOCK:
        entry = _ENTRIES.get(task_id)
        if entry is None:
            return
        entry.progress = progress


def complete(task_id: str, result: dict[str, Any]) -> None:
    """标记完成 + 写入 result。"""
    with _LOCK:
        entry = _ENTRIES.get(task_id)
        if entry is None:
            return
        entry.status = "completed"
        entry.finished_at = _now()
        entry.result = result


def fail(task_id: str, error: str) -> None:
    """标记失败 + 写入 error。"""
    with _LOCK:
        entry = _ENTRIES.get(task_id)
        if entry is None:
            return
        entry.status = "failed"
        entry.finished_at = _now()
        entry.error = error


def get(task_id: str) -> TaskEntry | None:
    """读取任务状态。过期或缺失返回 None。

    注：返回的是 TaskEntry **拷贝**（dataclass 默认行为），调用方修改
    不会影响 registry —— 符合「只读查询」语义。
    """
    with _LOCK:
        _purge_expired()
        entry = _ENTRIES.get(task_id)
        if entry is None:
            return None
    # dataclass(field_copy) 默认就是浅拷贝；足以应对只读展示
    return TaskEntry(
        task_id=entry.task_id,
        status=entry.status,
        accepted_at=entry.accepted_at,
        started_at=entry.started_at,
        finished_at=entry.finished_at,
        progress=entry.progress,
        error=entry.error,
        result=dict(entry.result) if entry.result is not None else None,
    )


def clear() -> None:
    """显式清空（测试隔离 / 手动重置）。"""
    with _LOCK:
        _ENTRIES.clear()


def size() -> int:
    """当前条目数（供诊断 / 单元测试）。"""
    with _LOCK:
        return len(_ENTRIES)
