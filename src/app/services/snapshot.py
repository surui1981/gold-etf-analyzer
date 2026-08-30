"""每日评估快照服务：捕获当日参数与评估值，建立本地历史数据。"""

import json
from datetime import date

from app.models.snapshot import DailySnapshot
from app.repositories.snapshot import SnapshotRepository
from app.schemas.snapshot import SnapshotListOut, SnapshotOut
from app.services.trend import TrendService
from app.utils.logger import get_logger

logger = get_logger(__name__)


class DailySnapshotService:
    """每日快照：价格参数 + 技术/宏观/综合评估值，按日 upsert。"""

    def __init__(
        self,
        repo: SnapshotRepository,
        trend: TrendService,
    ) -> None:
        self._repo = repo
        self._trend = trend

    async def capture_today(self) -> SnapshotOut:
        """捕获并持久化当日评估快照（同日重复捕获为更新）。"""
        trend = await self._trend.analyze(days=60, target="etf")
        m = trend.metrics
        macro = trend.macro
        tech_index = round(sum(i.contribution for i in trend.indicators), 1)

        macro_detail = json.dumps(
            {
                f.key: {
                    "value": f.value,
                    "score": f.score,
                    "direction": f.direction.value,
                    "unit": f.unit,
                    "data_date": f.data_date,
                }
                for f in macro.factors
            },
            ensure_ascii=False,
        )

        snapshot = DailySnapshot(
            snapshot_date=date.today(),
            symbol=trend.symbol,
            name=trend.name,
            close=m.end_price,
            change_pct=m.change_pct,
            high=m.high,
            low=m.low,
            ma20=m.ma20 or 0.0,
            ma40=m.ma40 or 0.0,
            direction=m.direction.value,
            tech_index=tech_index,
            macro_index=macro.score,
            news_index=trend.news.score,
            trend_index=trend.index.score,
            index_level=trend.index.level.value,
            macro_detail=macro_detail,
        )
        await self._repo.upsert(snapshot)
        logger.info(
            "Snapshot captured: %s, close=%.3f, trend=%.1f (%s), tech=%.1f, macro=%.1f, news=%.1f",
            snapshot.snapshot_date, snapshot.close,
            snapshot.trend_index, snapshot.index_level, snapshot.tech_index, snapshot.macro_index, snapshot.news_index,
        )
        return SnapshotOut.model_validate(snapshot)

    async def list_history(self, days: int = 30) -> SnapshotListOut:
        """最近 N 天历史快照；当日尚无快照时自动捕获（惰性，保证当日数据在场）。"""
        if await self._repo.get_by_date(date.today()) is None:
            try:
                await self.capture_today()
            except Exception as exc:  # noqa: BLE001 —— 数据源故障不阻塞历史返回
                logger.warning("auto capture failed (%s), return history only", exc)

        snapshots = await self._repo.list_recent(days)
        return SnapshotListOut(
            total=len(snapshots),
            snapshots=[SnapshotOut.model_validate(s) for s in snapshots],
        )
