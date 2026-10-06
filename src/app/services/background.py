"""进程级后台任务追踪（避免 ruff RUF006 与测试悬挂）。

背景
----
``asyncio.create_task`` 只持**弱引用**：若调用方不保存返回值，任务可能在执行途中
被 GC，导致后台协程无声中断（典型症状：「明明触发了异步回测，却什么都没发生」）。

现有做法（V0.67.0 起）：``main.py::_spawn_background`` 维护一个模块级 ``set[Task]``
持有强引用，任务结束时通过 ``add_done_callback`` 自动 ``discard``。但 ``main.py``
是顶层入口，无法被 ``api/v1/endpoints/*`` 安全 import（会形成循环依赖）。

故将追踪机制提取到此独立模块，让 endpoint 也能复用同一份 set —— 同一进程下所有
``_spawn_background`` 调用共享同一引用表，便于：
  1. ``conftest._reset_db`` 用 ``asyncio.gather(*_BACKGROUND_TASKS)`` 在
     ``DROP TABLE`` 前等所有后台协程退出（否则 aiosqlite 「database is locked」）。
  2. 未来 ``lifespan`` 关闭时统一 ``cancel_all``（V0.79.0 不做）。
"""

from __future__ import annotations

import asyncio

_BACKGROUND_TASKS: set[asyncio.Task] = set()


def spawn(coro) -> asyncio.Task:
    """创建后台任务并持有强引用，避免被 GC 回收。返回 Task 对象（一般调用方丢弃）。"""
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return task


def drain(timeout: float | None = None) -> None:
    """同步等待所有后台任务完成（测试隔离 / lifespan 关闭）。

    ⚠ **不可在运行中的事件循环里调用**：会触发 ``RuntimeError: this loop is already
    running``。测试 / lifespan 通常有更直接的 await 路径，本函数保留为占位。
    """
    raise NotImplementedError("使用 asyncio.gather(*_BACKGROUND_TASKS, ...) 代替")
