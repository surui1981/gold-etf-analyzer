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
from app.utils.logger import get_logger

logger = get_logger(__name__)

# V0.67.0：价格日历 schema 校验常量
# - ``live``：实时行情抓取（默认）
# - ``manual``：人工导入（CSV / WGC 等）
# - ``import``：脚本批量导入（`import_central_bank`）
# - ``test``：单测 fixture 专用（V0.66.0 测试已固定使用该标记，保留以免破坏回归）
_VALID_SOURCES: frozenset[str] = frozenset({"live", "manual", "import", "test"})
_CHANGE_PCT_LIMIT: float = 50.0  # 单日涨跌幅边界（±50%）


def _validate_bar(target: str, price_date: date, close: float, source: str) -> str | None:
    """单根价格条目的 schema 校验。返回错误信息，None 表示通过。

    校验项（V0.67.0 P0）：
    - ``close`` 必须为正数（≤ 0 视为脏数据 / NaN 走接口失败兜底）
    - ``source`` 必须在白名单 ``{live, manual, import}`` 内
    """
    if close <= 0 or close != close:  # 第二个条件捕获 NaN（NaN != NaN）
        return f"invalid close={close!r} (must be > 0)"
    if source and source not in _VALID_SOURCES:
        return f"invalid source={source!r} (must be one of {sorted(_VALID_SOURCES)})"
    return None


def _validate_change_pct(change_pct: float) -> bool:
    """涨跌幅边界校验：单日 ±50% 视为异常（除拆股 / 熔断外不应出现）。"""
    return abs(change_pct) <= _CHANGE_PCT_LIMIT


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
        stmt = (
            select(func.count()).select_from(GoldPriceDaily).where(GoldPriceDaily.target == target)
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

        # V0.67.0：先做单条 schema 校验（close > 0 / source 白名单），
        # 失败的整批拒绝（防止部分写入部分失败导致回滚不彻底）。
        for price_date, close in bars:
            err = _validate_bar(target, price_date, close, source)
            if err is not None:
                logger.warning(
                    "price calendar schema reject: target=%s date=%s close=%s source=%s reason=%s",
                    target,
                    price_date,
                    close,
                    source,
                    err,
                )
                raise ValueError(f"price calendar validation failed: {err}")

        ordered_bars = sorted(bars, key=lambda b: b[0])
        first_date = ordered_bars[0][0]
        last_date = ordered_bars[-1][0]

        existing = {
            r.price_date: r for r in await self.list_range(target, start=first_date, end=last_date)
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
        rejected_change_pct = 0
        for price_date, close in ordered_bars:
            idx = position[price_date]
            prev_close = closes[ordered_dates[idx - 1]] if idx > 0 else None
            change_pct = round((close - prev_close) / prev_close * 100, 2) if prev_close else 0.0

            # V0.67.0：涨跌幅边界校验。理论上应被 close > 0 兜底拦住，
            # 但接口返回 0→正数（mock 初始化 / 数据源错位）时可能产生极大变化。
            if prev_close and not _validate_change_pct(change_pct):
                logger.warning(
                    "price calendar change_pct reject: target=%s date=%s close=%s prev=%s change_pct=%.2f",
                    target,
                    price_date,
                    close,
                    prev_close,
                    change_pct,
                )
                rejected_change_pct += 1
                continue

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

        if rejected_change_pct:
            logger.info(
                "price calendar partial write: target=%s accepted=%s rejected_change_pct=%s",
                target,
                written,
                rejected_change_pct,
            )

        await self._session.commit()
        return written
