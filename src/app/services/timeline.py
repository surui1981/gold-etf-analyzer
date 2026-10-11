"""决策时间线回放服务（V0.90.0）。

把 ``TradeRecord`` + ``Position`` 三元组（``TradeWithPosition``）与每日
``DailySnapshot`` 按日期对齐，输出 ``TimelineSegment`` 序列：

- **decision** 段：trade 当日 + 对齐快照（当日缺快照时回退到最近前一日）
- **idle** 段：连续空闲期；超过 ``compress_threshold_days`` 折叠为 1 个 ``compressed=True`` 段
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.position import PositionRepository, TradeWithPosition
from app.repositories.snapshot import SnapshotRepository
from app.schemas.snapshot import SnapshotOut
from app.schemas.timeline import TimelineOut, TimelineSegment
from app.schemas.trade import TradeHistoryItem
from app.services.snapshot import DailySnapshotService
from app.utils.logger import get_logger

logger = get_logger(__name__)


# 决策点对齐策略：「同日或最近前一日」快照的最大允许跨度。
# 防 trade 落在快照历史空洞期太久（数据缺失），误拿远古快照。
_MAX_ALIGN_BACKFILL_DAYS = 30


@dataclass(slots=True)
class _ResolvedTrade:
    """trade + 对齐快照（service 内部中间态，避免 schema 字段污染）。"""
    trade: TradeHistoryItem
    snapshot: SnapshotOut | None
    trade_date: date


class TimelineService:
    """决策时间线回放服务。"""

    def __init__(
        self,
        session: AsyncSession,
        position_repo: PositionRepository | None = None,
        snapshot_repo: SnapshotRepository | None = None,
        snapshot_service: DailySnapshotService | None = None,
    ) -> None:
        self._session = session
        self._position_repo = position_repo or PositionRepository(session)
        self._snapshot_repo = snapshot_repo or SnapshotRepository(session)
        self._snapshot_service = snapshot_service or DailySnapshotService(
            self._snapshot_repo, trend=None  # type: ignore[arg-type]
        )

    async def build(
        self,
        *,
        account_id: int | None,
        from_date: date,
        to_date: date,
        compress_threshold_days: int = 7,
    ) -> TimelineOut:
        """构建时间线：trades + snapshots 按日期对齐 + 空闲段折叠。

        Args:
            account_id: 账本筛选；不传=全部（与 ``trades/list`` 一致）
            from_date: 区间下界（含）
            to_date: 区间上界（含）
            compress_threshold_days: 空闲段折叠阈值（默认 7）
                0 = 不折叠；负数视作 0

        Returns:
            TimelineOut —— segments 序列按时间升序排列
        """
        if compress_threshold_days < 0:
            compress_threshold_days = 0

        # 1. 拉 trades（service 自己处理 user_id 解析）
        trade_rows = await self._position_repo.query_trades(
            account_id=account_id,
            start=from_date,
            end=to_date,
        )

        # 2. 拉快照范围（批量，避免 N+1）
        snapshot_rows = await self._snapshot_repo.list_in_range(from_date, to_date)
        # 转 dict for O(1) lookup；按日期正序
        snapshot_by_date: dict[date, SnapshotOut] = {
            s.snapshot_date: s for s in [SnapshotOut.model_validate(r) for r in snapshot_rows]
        }

        # 3. 把 trade 按 trade_date 分桶（一日可能多笔 → 各自一个 segment）
        resolved: list[_ResolvedTrade] = []
        for row in trade_rows:
            item = self._to_trade_item(row)
            trade_date = row.trade.traded_at.date()
            aligned = self._align_snapshot(
                trade_date=trade_date,
                snapshot_by_date=snapshot_by_date,
                earliest=from_date,
            )
            resolved.append(_ResolvedTrade(
                trade=item,
                snapshot=aligned,
                trade_date=trade_date,
            ))

        # 4. 构建 segments（决策点 + 空闲段交替）
        segments = self._build_segments(
            resolved=resolved,
            from_date=from_date,
            to_date=to_date,
            compress_threshold_days=compress_threshold_days,
        )

        # 5. 活跃天数：trade_date + snapshot_date 的并集
        active_set: set[date] = set(snapshot_by_date.keys())
        for r in resolved:
            active_set.add(r.trade_date)

        span = (to_date - from_date).days + 1
        return TimelineOut(
            from_date=from_date,
            to_date=to_date,
            span_days=span,
            active_days=len(active_set),
            decision_count=len(resolved),
            segments=segments,
        )

    # ────────────── private helpers ──────────────

    def _to_trade_item(self, row: TradeWithPosition) -> TradeHistoryItem:
        """``TradeWithPosition`` 三元组 → ``TradeHistoryItem``（复用 trades list 的 schema）。"""
        from app.schemas.trade import TradeHistoryItem

        trade = row.trade
        position = row.position
        return TradeHistoryItem(
            id=trade.id,
            position_id=trade.position_id,
            account_id=position.account_id,
            account_name=row.account_name or "",
            symbol=position.symbol,
            name=position.name,
            side=trade.side,
            quantity=trade.quantity,
            price=trade.price,
            fee=trade.fee,
            amount=round(trade.quantity * trade.price, 4),
            realized_pnl=None,  # timeline 不算均价回放（与 detail 不同）
            post_quantity=None,
            traded_at=trade.traded_at,
        )

    def _align_snapshot(
        self,
        *,
        trade_date: date,
        snapshot_by_date: dict[date, SnapshotOut],
        earliest: date,
    ) -> SnapshotOut | None:
        """trade 当日 → 同日快照；缺则回退最近前一日（上限 _MAX_ALIGN_BACKFILL_DAYS）。"""
        if trade_date in snapshot_by_date:
            return snapshot_by_date[trade_date]
        # 回退：trade_date - 1, - 2, ... 直到 earliest 或 _MAX_ALIGN_BACKFILL_DAYS
        backfill_cutoff = max(
            earliest,
            trade_date - timedelta(days=_MAX_ALIGN_BACKFILL_DAYS),
        )
        for offset in range(1, _MAX_ALIGN_BACKFILL_DAYS + 1):
            candidate = trade_date - timedelta(days=offset)
            if candidate < backfill_cutoff:
                break
            if candidate in snapshot_by_date:
                return snapshot_by_date[candidate]
        return None

    def _build_segments(
        self,
        *,
        resolved: list[_ResolvedTrade],
        from_date: date,
        to_date: date,
        compress_threshold_days: int,
    ) -> list[TimelineSegment]:
        """按日期升序遍历，构建 decision + idle 交替序列。"""
        # 按日期分组（一日多笔 → 按 id 顺序串接为多个 decision 段）
        resolved_sorted = sorted(resolved, key=lambda r: (r.trade_date, r.trade.id))

        # 全程无 trade：返回 1 个 idle 段覆盖全范围（边界 case）
        if not resolved_sorted:
            return [self._make_idle(
                start=from_date,
                end=to_date,
                compress_threshold_days=compress_threshold_days,
            )]

        segments: list[TimelineSegment] = []
        cursor = from_date

        for r in resolved_sorted:
            if cursor < r.trade_date:
                # 段间空闲：cursor ~ (trade_date - 1)
                segments.append(self._make_idle(
                    start=cursor,
                    end=r.trade_date - timedelta(days=1),
                    compress_threshold_days=compress_threshold_days,
                ))
            elif cursor > r.trade_date:
                # 同一日期多笔 trade——cursor 不前进；保持上一段后追加
                pass
            segments.append(TimelineSegment(
                type="decision",
                start=r.trade_date,
                end=r.trade_date,
                trade=r.trade,
                snapshot=r.snapshot,
            ))
            # cursor 推到「当日」末尾（下一笔 trade 若是同日则不进位）
            if r.trade_date > cursor:
                cursor = r.trade_date

        # 收尾空闲（最后一笔 trade 之后到 to_date）
        if cursor < to_date:
            segments.append(self._make_idle(
                start=cursor + timedelta(days=1),
                end=to_date,
                compress_threshold_days=compress_threshold_days,
            ))

        return segments

    def _make_idle(
        self,
        *,
        start: date,
        end: date,
        compress_threshold_days: int,
    ) -> TimelineSegment:
        """构造空闲段；跨度 > 阈值则 compressed=True。"""
        if start > end:
            # 边界保护：cursor 推进过程中可能反向（不应发生）
            return TimelineSegment(
                type="idle",
                start=start,
                end=start,
                idle_days=1,
                compressed=False,
            )
        idle_days = (end - start).days + 1
        compressed = (
            compress_threshold_days > 0 and idle_days > compress_threshold_days
        )
        return TimelineSegment(
            type="idle",
            start=start,
            end=end,
            idle_days=idle_days,
            compressed=compressed,
        )