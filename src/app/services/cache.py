"""当日已服务结果缓存：核心评估每日仅生成一次，页面直接命中秒级返回。

设计目标
--------
- 评估核心数据（趋势指数 + 宏观因子明细 + 消息面）每日仅重算一次；
  页面加载直接返回内存中的 GoldTrendOut，避免每次请求都走一次 K 线 + 宏观 + 合成。
- 缓存以 ``(target, snapshot_date)`` 为 key，过期机制：跨日自然失效（旧 key 不再被命中）。
- 失效时机：
  - 消息面评分更新 → ``invalidate(target)``（下次请求全量重算）
  - 调度器 07:00 BJT 自动重生成 → 直接覆盖写入

线程安全
--------
FastAPI 依赖注入每次请求都新建 TrendService 实例，但所有实例共享同一份进程级缓存。
使用 threading.Lock 保护读写；asyncio 协程内部不阻塞（只在解析 JSON/IO 时短暂持锁）。
"""

from datetime import date
from threading import Lock

from app.schemas.market import GoldTrendOut
from app.utils.logger import get_logger

logger = get_logger(__name__)

_CACHE: dict[tuple[str, date], GoldTrendOut] = {}
_LOCK = Lock()


def get_served(target: str, on_date: date | None = None) -> GoldTrendOut | None:
    """获取指定日期 + 标的已服务结果。默认取今日；命中返回 ``GoldTrendOut``，未命中 None。"""
    on_date = on_date or date.today()
    with _LOCK:
        return _CACHE.get((target, on_date))


def set_served(target: str, result: GoldTrendOut, on_date: date | None = None) -> None:
    """写入已服务结果。``on_date`` 缺省取今日（与 GoldTrendOut 实际生成日期一致）。"""
    on_date = on_date or date.today()
    with _LOCK:
        _CACHE[(target, on_date)] = result
    logger.info("Served cache set: target=%s, date=%s, index=%.1f", target, on_date, result.index.score)


def invalidate(target: str | None = None) -> int:
    """失效缓存。

    Args:
        target: 仅失效指定 target；为 None 时清空全部。

    Returns:
        失效的条目数。
    """
    with _LOCK:
        if target is None:
            n = len(_CACHE)
            _CACHE.clear()
        else:
            keys = [k for k in _CACHE if k[0] == target]
            for k in keys:
                _CACHE.pop(k, None)
            n = len(keys)
    if n:
        logger.info("Served cache invalidated: target=%s, count=%d", target, n)
    return n


def cache_size() -> int:
    """当前缓存条目数（仅供测试/调试）。"""
    with _LOCK:
        return len(_CACHE)