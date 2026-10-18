"""每日评估快照服务：捕获当日参数与评估值，建立本地历史数据。"""

import json
from datetime import date

from app.models.snapshot import DailySnapshot
from app.repositories.snapshot import SnapshotRepository
from app.schemas.snapshot import SnapshotListOut, SnapshotOut
from app.services.price_source import resolve_price_source
from app.services.trend import GUIDE_TARGET, TrendService
from app.utils.logger import get_logger

logger = get_logger(__name__)


class DailySnapshotService:
    """每日快照：价格参数 + 技术/宏观/综合评估值，按日 upsert。"""

    def __init__(
        self,
        repo: SnapshotRepository,
        trend: TrendService,
        # V0.92.0：写时 hook 触发打分数据宽表 ETL；可空（CLI / 单测不传）
        wide_svc=None,
    ) -> None:
        self._repo = repo
        self._trend = trend
        self._wide_svc = wide_svc

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

        # 行情来源：复用 #161 的解析（target→市场 key 映射，gram 记作 sge）。
        # ⚠ 缺失时返回空串而**不兜底 live** —— 那会静默宣称数据可信。
        source = resolve_price_source(trend.data_sources, GUIDE_TARGET)

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
            # V0.100：消息面未打分时 trend.news.score=None；快照表 NOT NULL 兜底为 50.0，
            # 配合 scored 字段（落 macro_detail JSON）让客户事后可知当日未打分
            news_index=trend.news.score if trend.news.score is not None else 50.0,
            trend_index=trend.index.score,
            index_level=trend.index.level.value,
            macro_detail=macro_detail,
            tech_detail=tech_detail,
            # ⚠ V0.79.0 任务 #163：落行情来源，否则事后无法区分真值与 mock 产物
            # （实测历史上 5 条快照的 close 是 mock 序列末值，且无从辨识）。
            data_source=source,
        )
        await self._repo.upsert(snapshot)
        logger.info(
            "Snapshot captured: %s, close=%.3f, trend=%.1f (%s), tech=%.1f, macro=%.1f, news=%s",
            snapshot.snapshot_date,
            snapshot.close,
            snapshot.trend_index,
            snapshot.index_level,
            snapshot.tech_index,
            snapshot.macro_index,
            snapshot.news_index,
        )
        # V0.92.0：写时 hook 触发打分数据宽表 ETL。
        # 宽表写失败 log.warning 但**不**回滚源表（V0.79.0 任务 #162 教训）。
        # ``wide_svc`` 可空（CLI / 单测不传），缺则跳过。
        if self._wide_svc is not None:
            await self._wide_svc.rebuild(snapshot.snapshot_date)
        else:
            # V0.92.0：DI 没注入时回退到 lifespan 阶段挂载的进程级单例
            from app.dependencies import _get_or_build_wide_svc

            wide_svc = _get_or_build_wide_svc()
            if wide_svc is not None:
                await wide_svc.rebuild(snapshot.snapshot_date)
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

    async def get_by_date(self, snapshot_date: date) -> SnapshotOut | None:
        """V0.90.0：按日期取单日快照（含 macro_detail 反序列化），无则 None。

        用于 ``GET /api/v1/snapshots/by-date/{date}`` —— 决策时间线回放的
        决策点状态卡片核心查询。
        """
        row = await self._repo.get_by_date(snapshot_date)
        return SnapshotOut.model_validate(row) if row else None

    async def get_in_range(
        self, start: date, end: date
    ) -> list[SnapshotOut]:
        """V0.90.0：按日期区间取快照列表（含 ``macro_detail`` 反序列化）。

        薄包装：转发到 ``SnapshotRepository.list_in_range``，把 ORM rows 转
        ``SnapshotOut``（schema validator 自动反序列化 macro_detail JSON）。

        用于：
        - ``GET /api/v1/snapshots/in-range?start=&end=``：日趋势对比窗口
        - ``TimelineService.build``：批量取时间窗内快照内存对齐 trades

        入参边界同仓储层（``start > end`` → 空 list；含首尾）。
        """
        rows = await self._repo.list_in_range(start, end)
        return [SnapshotOut.model_validate(r) for r in rows]
