"""每日评估快照服务：捕获当日参数与评估值，建立本地历史数据。"""

import json
from datetime import date

from app.models.snapshot import DailySnapshot
from app.repositories.snapshot import SnapshotRepository
from app.schemas.snapshot import SnapshotListOut, SnapshotOut
from app.services.trend import GUIDE_TARGET, TrendService
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
        trend = await self._trend.analyze(days=60, target=GUIDE_TARGET)
        m = trend.metrics
        macro = trend.macro
        # ⚠ V0.79.0 修：原为 ``sum(i.contribution for i in trend.indicators)``，
        # 而 **V0.78.0 Step D 起数据不足维度的 ``contribution`` 是 ``None``**
        # （`trend.py:736` 起显式置 None 以区分「没算出来」与「算出来是中性」）
        # ⇒ 任一维度不足即 ``TypeError: unsupported operand type(s) for +: 'int' and 'NoneType'``，
        # **整次快照捕获崩溃**（Step D 改了 trend.py 却漏了这条路径）。
        # 正确口径：只累加参与合成的有效维度；全不可用时 tech_index=0.0
        # （与 ``_build_index`` 的 total=None→0.0 语义一致，见 trend.py:754）。
        tech_index = round(
            sum(i.contribution for i in trend.indicators if i.contribution is not None),
            1,
        )

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

        # V0.79.0 任务 #162：落技术面 5 维度分（trend_5 网格回测的前置）。
        # ⚠ **只落 score 非 None 的维度** —— 数据不足的维度其 score 为 None
        # （V0.78.0 Step D 语义），**不可用 50 兜底**，否则「没算出来」会被
        # 下游读成「算出来是中性」。缺失即键不存在，由消费方显式处理。
        tech_detail_obj = {
            i.name: {
                "score": i.score,
                "weight": i.weight,
                "contribution": i.contribution,
            }
            for i in trend.indicators
            if i.score is not None
        }
        tech_detail = json.dumps(tech_detail_obj, ensure_ascii=False) if tech_detail_obj else None

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
            tech_detail=tech_detail,
        )
        await self._repo.upsert(snapshot)
        logger.info(
            "Snapshot captured: %s, close=%.3f, trend=%.1f (%s), tech=%.1f, macro=%.1f, news=%.1f",
            snapshot.snapshot_date,
            snapshot.close,
            snapshot.trend_index,
            snapshot.index_level,
            snapshot.tech_index,
            snapshot.macro_index,
            snapshot.news_index,
        )
        # V0.79.0：落库子维度数需可诊断 —— 为 0 说明 5 个维度全部数据不足
        # （或 W/M 视图旁路），此时 tech_detail 为 NULL，消费方须显式跳过。
        logger.info(
            "Snapshot tech_detail: date=%s dims=%d%s",
            snapshot.snapshot_date,
            len(tech_detail_obj),
            "" if tech_detail_obj else " (tech_detail=NULL)",
        )
        return SnapshotOut.model_validate(snapshot)

    async def list_history(self, days: int = 30) -> SnapshotListOut:
        """最近 N 天历史快照；当日尚无快照时自动捕获（惰性，保证当日数据在场）。"""
        if await self._repo.get_by_date(date.today()) is None:
            try:
                await self.capture_today()
            except Exception as exc:
                logger.warning("auto capture failed (%s), return history only", exc)

        snapshots = await self._repo.list_recent(days)
        return SnapshotListOut(
            total=len(snapshots),
            snapshots=[SnapshotOut.model_validate(s) for s in snapshots],
        )

    async def get_previous(self, before: date) -> SnapshotOut | None:
        """V0.72.0：取 ``before`` 之前最近一个交易日的快照（用于告警档位穿越检测）。"""
        prev = await self._repo.get_latest_before(before)
        return SnapshotOut.model_validate(prev) if prev else None
