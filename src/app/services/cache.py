"""当日已服务结果缓存：核心评估日内可设 TTL，页面直接命中秒级返回。

设计目标
--------
- 评估核心数据（趋势指数 + 宏观因子明细 + 消息面）每日仅重算一次（基础口径）；
  页面加载直接返回内存中的 GoldTrendOut，避免每次请求都走一次 K 线 + 宏观 + 合成。
- 缓存以 ``(target, snapshot_date)`` 为 key；
  失效机制（V0.60.0 升级）：
    1. 跨日自然失效（旧 key 不再被命中）；
    2. 日内 TTL（``max_age_seconds``）：超期返回 None，强制下次请求全量重算；
    3. 主动 invalidate：消息面打分更新 / 调度器重生成。

线程安全
--------
FastAPI 依赖注入每次请求都新建 TrendService 实例，但所有实例共享同一份进程级缓存。
使用 threading.Lock 保护读写；asyncio 协程内部不阻塞（只在解析 JSON/IO 时短暂持锁）。
"""

from datetime import date, datetime, timezone
from threading import Lock

from app.schemas.market import GoldTrendOut
from app.utils.logger import get_logger

logger = get_logger(__name__)

# V0.60.0：value 由 GoldTrendOut 改为 (GoldTrendOut, set_at_utc)，
# 以支持日内 TTL（max_age_seconds）派生。
# V0.64.0：key 由 (target, date) 扩展为 (target, interval, date)，
# 以支持多时间框架（D/W/M）独立缓存，避免 W/M 结果被 D 请求误命中。
_CACHE: dict[tuple[str, str, date], tuple[GoldTrendOut, datetime]] = {}
_LOCK = Lock()


def _key(target: str, interval: str, on_date: date) -> tuple[str, str, date]:
    """统一构造缓存 key，interval 归一化为大写单字母（D/W/M）。"""
    return (target, (interval or "D").upper()[:1], on_date)


def get_served(
    target: str,
    on_date: date | None = None,
    *,
    max_age_seconds: int | None = None,
    interval: str = "D",
) -> GoldTrendOut | None:
    """获取指定日期 + 标的已服务结果。默认取今日。

    Args:
        target: 标的类型（"ny" / "etf" / "gram"）。
        on_date: 缓存键中的日期；缺省取今日。
        max_age_seconds: V0.60.0 新增。None = 仅按 date 命中（旧行为）；
            非 None 时，若 cache entry 的 set_at 距今超过该秒数，返回 None（强制重算）。
            ``<=0`` 视同 None（永不按 TTL 失效）。
        interval: V0.64.0 新增。K 线聚合粒度（D / W / M），缺省 "D"。
            不同 interval 独立缓存，避免 W/M 结果被 D 请求误命中。

    Returns:
        GoldTrendOut 或 None（命中失败 / 跨日 / TTL 超期）。
    """
    on_date = on_date or date.today()
    with _LOCK:
        entry = _CACHE.get(_key(target, interval, on_date))
    if entry is None:
        return None
    if max_age_seconds is not None and max_age_seconds > 0:
        age = (datetime.now(timezone.utc) - entry[1]).total_seconds()
        if age > max_age_seconds:
            logger.debug(
                "Served cache TTL expired: target=%s interval=%s age=%.1fs > %ds",
                target,
                interval,
                age,
                max_age_seconds,
            )
            return None
    return entry[0]


def set_served(
    target: str,
    result: GoldTrendOut,
    on_date: date | None = None,
    *,
    interval: str = "D",
) -> None:
    """写入已服务结果 + 记录 set_at 时间戳（供日内 TTL 判定）。

    ``on_date`` 缺省取今日（与 GoldTrendOut 实际生成日期一致）。
    ``interval`` 缺省 "D"（V0.64.0 新增维度）。
    """
    on_date = on_date or date.today()
    with _LOCK:
        _CACHE[_key(target, interval, on_date)] = (result, datetime.now(timezone.utc))
    logger.info(
        "Served cache set: target=%s interval=%s date=%s index=%.1f",
        target,
        interval,
        on_date,
        result.index.score,
    )


def invalidate(target: str | None = None, interval: str | None = None) -> int:
    """失效缓存。

    Args:
        target: 仅失效指定 target；为 None 时清空全部。
        interval: V0.64.0 新增。指定时仅失效 (target, interval) 维度；
            缺省时失效该 target 的所有 interval。None + interval=None = 全清。

    Returns:
        失效的条目数。
    """
    with _LOCK:
        if target is None:
            n = len(_CACHE)
            _CACHE.clear()
        else:
            keys = [
                k
                for k in _CACHE
                if k[0] == target and (interval is None or k[1] == (interval or "D").upper()[:1])
            ]
            for k in keys:
                _CACHE.pop(k, None)
            n = len(keys)
    if n:
        logger.info("Served cache invalidated: target=%s interval=%s count=%d", target, interval, n)
    return n


def cache_size() -> int:
    """当前缓存条目数（仅供测试/调试）。"""
    with _LOCK:
        return len(_CACHE)


def _entry_set_at(
    target: str,
    on_date: date | None = None,
    *,
    interval: str = "D",
) -> datetime | None:
    """返回指定缓存条目的 set_at 时间戳（仅供测试）。

    Args:
        target: 标的类型。
        on_date: 缓存日期；缺省取今日。
        interval: V0.64.0 新增。

    Returns:
        datetime 或 None（条目不存在）。
    """
    on_date = on_date or date.today()
    with _LOCK:
        entry = _CACHE.get(_key(target, interval, on_date))
    return entry[1] if entry is not None else None
