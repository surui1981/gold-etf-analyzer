"""数据时效与交易时段服务（UX 6.1：数据时效与语境透明）。

职责：
- 读取仓储层的采集元信息（数据源状态 / 采集时刻 / 数据截止日）；
- 结合交易时段判定，输出各市场的**时效等级**（实时/延时/T-1/滞后/缓存/演示）；
- 供全站顶部时效条（``/api/v1/market/freshness``）与趋势页内嵌时效标注复用。

冷启动兜底：若某市场尚未采集过（无数据截止日），触发一次限时采集，
避免出现长期停留在「未采集」的空态。
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone

from app.repositories.market_data import MarketDataRepository
from app.schemas.market import (
    DataFreshnessOut,
    FreshnessOut,
    MarketSessionOut,
)
from app.utils.logger import get_logger
from app.utils.market_clock import (
    MarketSession,
    classify_freshness,
    etf_session,
    freshness_label,
    ny_gold_session,
    sge_session,
)

logger = get_logger(__name__)

# 市场 key → (展示名, 时段判定函数)
_MARKETS: dict[str, tuple[str, object]] = {
    "ny": ("纽约金（COMEX GC）", ny_gold_session),
    "sge": ("上海金（SGE Au99.99）", sge_session),
    "etf": ("黄金ETF（518880）", etf_session),
}

# 冷启动采集超时（秒）：避免时效接口被慢数据源拖住
_WARM_TIMEOUT = 25.0
_WARM_DAYS = 5


def build_data_freshness(
    market: str,
    *,
    status: str = "-",
    data_date: date | None = None,
    fetched_at: datetime | None = None,
    now: datetime | None = None,
) -> DataFreshnessOut:
    """构造单个市场的数据时效输出（供本服务与趋势分析复用）。

    Args:
        market: 市场标识 ny / sge / etf
        status: 数据源状态 live / stale / mock
        data_date: 数据截止日（最后一根 K 线日期）
        fetched_at: 数据采集时刻（UTC）
        now: 计算时刻（UTC）；缺省取当前时间

    Returns:
        该市场的数据时效输出
    """
    now = now or datetime.now(timezone.utc)
    name, session_fn = _MARKETS[market]  # type: ignore[misc]
    session: MarketSession = session_fn(now)  # type: ignore[operator]
    level = classify_freshness(
        status=status,
        data_date=data_date,
        session_state=session.state,
        now=now,
    )
    age_minutes = (
        round((now - fetched_at).total_seconds() / 60, 1) if fetched_at is not None else -1.0
    )
    return DataFreshnessOut(
        market=market,
        name=name,
        status=status,
        freshness=level,
        freshness_label=freshness_label(level),
        data_date=data_date.isoformat() if data_date else "",
        fetched_at=fetched_at.isoformat() if fetched_at else "",
        age_minutes=age_minutes,
        session=MarketSessionOut(
            market=session.market,
            name=session.name,
            state=session.state.value,
            state_label=session.state_label,
            windows=list(session.windows),
            next_event=session.next_event,
            note=session.note,
        ),
        note=session.note,
    )


class FreshnessService:
    """数据时效报告：时效等级 + 交易时段 + 采集时间戳。"""

    def __init__(self, repo: MarketDataRepository) -> None:
        self._repo = repo

    async def report(self, now: datetime | None = None) -> FreshnessOut:
        """生成全站数据时效报告。

        Args:
            now: 计算时刻（UTC）；缺省取当前时间

        Returns:
            各市场时效明细 + 降级标识 + 一句话汇总
        """
        now = now or datetime.now(timezone.utc)
        meta = self._read_meta()

        # 冷启动：尚未采集过的市场触发一次限时采集，避免长期「未采集」
        missing = [k for k in _MARKETS if not meta.get(k, {}).get("last_date")]
        if missing:
            await asyncio.gather(*(self._warm(k) for k in missing), return_exceptions=True)
            meta = self._read_meta()

        markets: dict[str, DataFreshnessOut] = {}
        for key in _MARKETS:
            item = meta.get(key, {})
            markets[key] = build_data_freshness(
                key,
                status=item.get("status", "-"),
                data_date=item.get("last_date"),
                fetched_at=item.get("fetched_at"),
                now=now,
            )

        degraded = any(v.status in {"mock", "stale"} for v in markets.values())
        summary = " ｜ ".join(
            f"{v.name.split('（')[0]} {v.session.state_label}·{v.freshness_label}"
            for v in markets.values()
        )
        return FreshnessOut(
            server_time=now.isoformat(),
            markets=markets,
            degraded=degraded,
            summary=summary,
        )

    def _read_meta(self) -> dict[str, dict]:
        """读取仓储层采集元信息（兼容无 source_meta 的替身对象）。"""
        getter = getattr(self._repo, "source_meta", None)
        return getter() if callable(getter) else {}

    async def _warm(self, market: str) -> None:
        """对尚未采集的市场做一次限时采集（失败不影响主流程）。"""
        try:
            if market == "ny":
                coro = self._repo.get_us_gold_history(days=_WARM_DAYS)
            elif market == "sge":
                coro = self._repo.get_gold_gram_history(days=_WARM_DAYS)
            else:
                coro = self._repo.get_gold_history(days=_WARM_DAYS)
            await asyncio.wait_for(coro, timeout=_WARM_TIMEOUT)
        except Exception as exc:  # noqa: BLE001 —— 冷启动兜底失败仅记录
            logger.warning("freshness warm-up failed (%s): %s", market, exc)
