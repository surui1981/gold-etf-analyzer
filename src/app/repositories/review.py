"""黄金价格日历仓储（V0.66.0）：研判复盘的客观价格基准。

价格日历独立于 ``daily_snapshots``：

- 快照表记录**评估值**，随口径变化；
- 价格表只存客观收盘价，可由行情接口一次性回填并长期积累，
  作为「当日研判 → 之后 N 个交易日表现」的对比基准。
"""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.review import GoldPriceDaily


class GoldPriceRepository:
    """黄金每日收盘价数据访问。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_range(
        self,
        target: str,
        *,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> list[GoldPriceDaily]:
        """按日期升序返回价格区间（供按交易日对齐取 T+N）。"""
        stmt = select(GoldPriceDaily).where(GoldPriceDaily.target == target)
        if start is not None:
            stmt = stmt.where(GoldPriceDaily.price_date >= start)
        if end is not None:
            stmt = stmt.where(GoldPriceDaily.price_date <= end)
        stmt = stmt.order_by(GoldPriceDaily.price_date)
        if limit is not None:
            stmt = stmt.limit(limit)
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_on(self, target: str, price_date: date) -> GoldPriceDaily | None:
        """取指定交易日的价格记录。"""
        stmt = select(GoldPriceDaily).where(
            GoldPriceDaily.target == target, GoldPriceDaily.price_date == price_date
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def latest_before(self, target: str, price_date: date) -> GoldPriceDaily | None:
        """取早于指定日期最近的一条（用于推算涨跌幅基准）。"""
        stmt = (
            select(GoldPriceDaily)
            .where(GoldPriceDaily.target == target, GoldPriceDaily.price_date < price_date)
            .order_by(GoldPriceDaily.price_date.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def latest(self, target: str) -> GoldPriceDaily | None:
        """取该标的最近一条价格。"""
        stmt = (
            select(GoldPriceDaily)
            .where(GoldPriceDaily.target == target)
            .order_by(GoldPriceDaily.price_date.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def count(self, target: str) -> int:
        """该标的已积累的交易日数量。"""
        stmt = select(func.count()).select_from(GoldPriceDaily).where(
            GoldPriceDaily.target == target
        )
        return int((await self._session.execute(stmt)).scalar() or 0)

    async def upsert_many(
        self,
        *,
        target: str,
        bars: list[tuple[date, float]],
        source: str = "",
    ) -> int:
        """批量写入日收盘价（按 ``target`` + 日期幂等，重复回填为更新）。

        涨跌幅在**合并后的时间序列**上重算：既参考本次传入的相邻点，
        也参考库中已存在的前一个交易日，避免重复回填时把首日涨跌幅清零。

        Args:
            target: 标的标识（ny/etf/gram）。
            bars: ``[(交易日, 收盘价), ...]``，无需预先排序。
            source: 数据来源标识，写入记录便于溯源。

        Returns:
            写入（新增 + 更新）的条数。
        """
        if not bars:
            return 0

        ordered_bars = sorted(bars, key=lambda b: b[0])
        first_date = ordered_bars[0][0]
        last_date = ordered_bars[-1][0]

        existing = {
            r.price_date: r
            for r in await self.list_range(target, start=first_date, end=last_date)
        }

        # 合并序列：库中更早的一条 + 区间内已有收盘 + 本次传入收盘
        closes: dict[date, float] = {}
        prev = await self.latest_before(target, first_date)
        if prev is not None:
            closes[prev.price_date] = float(prev.close)
        for d, row in existing.items():
            closes[d] = float(row.close)
        for d, close in ordered_bars:
            closes[d] = float(close)

        ordered_dates = sorted(closes)
        position = {d: i for i, d in enumerate(ordered_dates)}

        written = 0
        for price_date, close in ordered_bars:
            idx = position[price_date]
            prev_close = closes[ordered_dates[idx - 1]] if idx > 0 else None
            change_pct = (
                round((close - prev_close) / prev_close * 100, 2)
                if prev_close
                else 0.0
            )

            row = existing.get(price_date)
            if row is None:
                self._session.add(
                    GoldPriceDaily(
                        target=target,
                        price_date=price_date,
                        close=close,
                        change_pct=change_pct,
                        source=source,
                    )
                )
            else:
                row.close = close
                # 无基准可算时保留原值，避免回填把已有涨跌幅抹平
                if prev_close:
                    row.change_pct = change_pct
                row.source = source or row.source
            written += 1

        await self._session.commit()
        return written
