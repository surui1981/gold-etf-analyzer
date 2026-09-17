"""日志工具：统一 logger 配置 + trace_id 自动附加（V0.67.0 起）。

调用方式::

    from app.utils.logger import get_logger
    log = get_logger(__name__)
    log.info("处理完成")

**trace_id 集成（V0.67.0）**：通过 :mod:`app.middleware.trace` 注入到
``contextvars``，本模块在 ``logging.Filter`` 中读取并附加到 ``LogRecord.trace_id``，
随后由 :class:`_Formatter` 输出到日志行尾——所有日志（HTTP 入口 / 业务 / 后台任务）
均能自动串联同一请求，无需手动传参。
"""

from __future__ import annotations

import logging
import sys

from app.middleware.trace import get_current_trace_id

_CONFIGURED = False


class TraceIdFilter(logging.Filter):
    """把当前 trace_id 注入每条 ``LogRecord.trace_id`` 字段。

    Filter 而非 Formatter 直接读 contextvars 的原因：Formatter 在
    ``logging.Handler.format`` 阶段独立运行，调用 ``get_current_trace_id()``
    会拿到调用方所在协程的上下文——但 ``logging.Filter.filter`` 也是，
    所以两者等价。Filter 的好处是「统一一次写入 Record」，便于测试断言
    ``record.trace_id == ...``。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_current_trace_id()
        return True


class _Formatter(logging.Formatter):
    """日志格式：``时间 | 级别 | trace_id | logger | 消息``。"""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s | %(levelname)-7s | %(trace_id)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        # 若上游未通过 Filter 注入，则补一个 "-" 占位
        if not hasattr(record, "trace_id"):
            record.trace_id = "-"
        return super().format(record)


def configure_root() -> None:
    """幂等初始化 root logger（handler + formatter + filter）。"""
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_Formatter())
    handler.addFilter(TraceIdFilter())
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # 避免重复添加（uvicorn 也会配 root）——通过 _Formatter 类标识
    if not any(
        isinstance(h, logging.StreamHandler) and h.formatter.__class__ is _Formatter
        for h in root.handlers
    ):
        root.addHandler(handler)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """获取带统一格式 + trace_id 自动附加的 logger。"""
    configure_root()
    return logging.getLogger(name)


__all__ = ["TraceIdFilter", "configure_root", "get_logger"]
