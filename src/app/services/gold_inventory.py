"""COMEX 黄金库存业务服务：抓取落库 + 多窗口变化率。"""

import asyncio
from datetime import date, timedelta

from app.models.gold_inventory import GoldInventoryDaily
from app.repositories.gold_inventory import GoldInventoryRepository
from app.repositories.gold_inventory_data import (
    GoldInventorySourceError,
    fetch_comex_inventory,
)
from app.schemas.gold_inventory import (
    GoldInventoryChange,
    GoldInventoryOut,
    GoldInventoryPoint,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 回看窗口：label → 自然日数。
# ⚠ 用**自然日**而不是「最近 N 行」：库存是交易日频，一个周末就少两点，
# 按行索引回看会让「近 1 月」在不同星期几算出 20 个交易日 vs 23 个交易日的差别，
# 同一个口径两周内漂两次。改成按日历日找基线，口径稳定。
WINDOWS: tuple[tuple[str, int], ...] = (("1w", 7), ("1m", 30), ("3m", 90), ("1y", 365))

DEFAULT_DAYS = 90


class GoldInventoryService:
    """COMEX 黄金库存服务。"""

    def __init__(self, repo: GoldInventoryRepository) -> None:
        self._repo = repo

    async def refresh(self) -> int:
        """抓源 + upsert 落库。

        Returns:
            受影响行数；源不可用返回 0（**不抛** —— 调度循环不该被单源打挂）。
        """
        try:
            points = await asyncio.to_thread(fetch_comex_inventory)
        except GoldInventorySourceError as exc:
            logger.error("COMEX 库存刷新失败：%s", exc)
            return 0
        except Exception as exc:
            logger.error("COMEX 库存刷新异常：%s", exc)
            return 0

        records = [
            GoldInventoryDaily(
                inv_date=p.inv_date,
                tonnes=p.tonnes,
                ounces=p.ounces,
                source=p.source,
            )
            for p in points
        ]
        try:
            n = await self._repo.upsert_bulk(records)
        except Exception as exc:
            logger.error("COMEX 库存落库失败：%s", exc)
            return 0
        logger.info("COMEX 库存落库 %d 行（最新 %s）", n, points[-1].inv_date)
        return n

    async def is_stale(self, *, max_age_days: int = 1) -> bool:
        """表空、或最新观测早于 ``max_age_days`` 天 → 需要回填。

        供 scheduler 的 bootstrap 分支用：只有「从没抓过」或「隔太久没更新」
        才在启动后补一次，避免每次重启都全量 upsert 1200+ 行。
        """
        latest = await self._repo.latest()
        if latest is None:
            return True
        return (date.today() - latest.inv_date).days > max_age_days

    @staticmethod
    def _change(
        points: list[GoldInventoryPoint], latest: GoldInventoryPoint, label: str, days: int
    ) -> GoldInventoryChange:
        """按日历日回看算变化率；窗口内无基线 → None（不是 0）。"""
        target = latest.date - timedelta(days=days)
        base: GoldInventoryPoint | None = None
        for p in reversed(points):  # points 升序 ⇒ 倒着找第一个 <= target 的
            if p.date <= target:
                base = p
                break
        if base is None or base.tonnes == 0:
            return GoldInventoryChange(window=label, days=days, base_date=None, change_pct=None)
        pct = (latest.tonnes - base.tonnes) / base.tonnes * 100
        return GoldInventoryChange(
            window=label, days=days, base_date=base.date, change_pct=round(pct, 2)
        )

    async def snapshot(self, days: int = DEFAULT_DAYS) -> GoldInventoryOut:
        """读库组装输出。

        空表返回 ``points=[]`` + ``latest_tonnes=None`` + ``degraded=True``
        —— 前端据此显示「—」与空态提示，**不编一个数出来**。
        """
        # ⚠ 回看起点必须锚在**最新观测日**而不是今天。
        # 源是交易日频，周末/停更时最新观测会比今天早 2-3 天；用
        # ``date.today() - 365d`` 当起点就会把「1 年前」的基线推出查询窗口，
        # 于是 1y 恒为 None —— 第一次实现就是这么写的，实测 1m/3m 有值、
        # 1y 永远是 null，理由看着还挺像样。
        latest_rec = await self._repo.latest()
        if latest_rec is None:
            return GoldInventoryOut(
                source="COMEX",
                points=[],
                changes=[
                    GoldInventoryChange(window=w, days=d, base_date=None, change_pct=None)
                    for w, d in WINDOWS
                ],
                degraded=True,
            )

        max_lookback = max(d for _, d in WINDOWS)
        records = await self._repo.list_since(latest_rec.inv_date - timedelta(days=max_lookback))
        if not records:
            return GoldInventoryOut(
                source="COMEX",
                points=[],
                changes=[
                    GoldInventoryChange(window=w, days=d, base_date=None, change_pct=None)
                    for w, d in WINDOWS
                ],
                degraded=True,
            )

        all_points = [GoldInventoryPoint(date=r.inv_date, tonnes=r.tonnes) for r in records]
        latest = all_points[-1]
        # 对外只给 days 窗口的序列；变化率仍基于全量 points（否则 days=90 时 1y 无基线）
        cutoff = latest.date - timedelta(days=days)
        window_points = [p for p in all_points if p.date >= cutoff]

        changes = [self._change(all_points, latest, label, d) for label, d in WINDOWS]

        # 最新观测距今超过 3 天（长周末 / 源停更）→ 标 degraded，让前端能提示
        stale_days = (date.today() - latest_rec.inv_date).days
        return GoldInventoryOut(
            source=latest_rec.source,
            as_of=latest_rec.inv_date,
            latest_tonnes=round(latest.tonnes, 2),
            points=window_points,
            changes=changes,
            degraded=stale_days > 3,
        )
