"""日志工具：统一 logger 配置，避免重复初始化。"""

import logging
import sys

_CONFIGURED = False


def get_logger(name: str) -> logging.Logger:
    """获取带统一格式的 logger。

    首次调用时初始化 root logger 配置（幂等）。
    """
    global _CONFIGURED
    if not _CONFIGURED:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
        )
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.addHandler(handler)
        _CONFIGURED = True
    return logging.getLogger(name)
