"""行情来源解析（V0.79.0）——判定一次取数是「真实行情」还是「降级产物」。

为什么单独成模块
----------------
「某个 ``target`` 的行情来源标识是什么」是**回测与复盘共同需要**的判定：
两者都要往 ``gold_price_daily`` 写价格，而该表的 ``source`` 列会被
``repositories/review._VALID_SOURCES`` 校验。若解析逻辑放在 ``services/backtest.py``，
则 ``services/review.py`` 需反向 import 它 —— 而 ``backtest.py`` 已经
``from app.services.review import judge_hit``，反向依赖会形成**循环导入**。

⚠ 实测踩过两次，规则如下：

1. **键名不是 target，是市场 key**。``TrendOut.data_sources`` 的键取自
   ``trend._FRESHNESS_KEYS``：``target='gram'``（上海金 Au99.99）在仓储层记作
   ``'sge'``；白银三标的分别复用 ``ny`` / ``etf`` 键。直接
   ``data_sources.get(target)`` 会在「数据其实是真的」时返回空串。
2. **缺失时不可兜底成 ``live``**。``live`` 表示「真实行情」，把「未知」标成
   ``live`` 等于**静默宣称数据可信**；而 ``mock``（取数失败后的降级产物）恰为
   真值会原样透传 —— 两种情形结果相反且都不可解释。正确做法是返回空串，
   由白名单统一拒绝（保守侧）。
"""

from __future__ import annotations

# 回测 / 复盘的 target → ``data_sources`` 的市场 key 候选（按优先级）。
# ⚠ 刻意**不复用** ``trend._FRESHNESS_KEYS``：那是私有名、语义为「时效/时段判定」
# 而非「行情来源」，复用会造成耦合（trend 改判定时段就会波及数据入库）。
# 两者的一致性由 ``tests/test_services/test_price_calendar_backfill.py`` 断言锁住。
_TARGET_TO_MARKET_KEY: dict[str, tuple[str, ...]] = {
    "ny": ("ny",),
    "etf": ("etf",),
    "gram": ("sge", "gram"),
    "silver_ny": ("ny", "silver_ny"),
    "silver_etf": ("etf", "silver_etf"),
    "silver_gram": ("etf", "silver_gram"),
}

# 可写入价格日历的数据源白名单。
# ⚠ **刻意不含 `mock``**（原文如此标注）：TrendService 取数失败会静默降级为 mock，
# 而 mock 收盘价入库 ⇒ 回测基于**编造的价格**算出看似正常的 Sharpe，
# 比「无数据」危险得多 —— 用户无从分辨。
# `stale` = 缓存未过期但未刷新，数据仍来自真实行情，故放行。
TRUSTED_PRICE_SOURCES: frozenset[str] = frozenset({"live", "stale", "import", "manual"})


def resolve_price_source(data_sources: dict | None, target: str) -> str:
    """取出 ``target`` 的行情来源标识；无法确定时返回空串（**不兜底 live**）。

    Args:
        data_sources: ``TrendOut.data_sources``，键为市场 key（可能为 None）。
        target: 回测 / 复盘的标的键（ny / etf / gram / silver_*）。

    Returns:
        ``live`` / ``stale`` / ``mock`` / ``stale`` 之外的来源标识；
        **无法确定时返回空串**，由调用方按白名单拒绝。
    """
    if not data_sources:
        return ""
    if target in data_sources:
        return data_sources[target] or ""
    for candidate in _TARGET_TO_MARKET_KEY.get(target, ()):
        if candidate in data_sources:
            return data_sources[candidate] or ""
    return ""


def is_trusted_price_source(source: str) -> bool:
    """该来源是否**可写入价格日历**（``mock`` 等降级产物返回 False）。"""
    return source in TRUSTED_PRICE_SOURCES
