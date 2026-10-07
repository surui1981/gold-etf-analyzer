"""消息面打分仓储（V0.65.0：每日最多 3 次，按 slot 区分）。

V0.66.0 起补充研判依据（``basis``）与复盘支持：区间批量查询、补录标记。

⚠ **V0.80.0 数据隔离（任务 #159 第 2 批）**：全部方法加 ``user_id`` 参数，
默认 ``None`` = 取当前请求上下文（``utils.user_scope.resolve_user_id``）。
改前**所有方法都没有任何用户过滤** ⇒ 开启多用户后，一个用户能读到/改到
另一个用户的打分记录（含研判依据与复盘批注）。
"""

from datetime import date, datetime, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news import NewsScore
from app.utils.user_scope import resolve_user_id


class NewsScoreRepository:
    """消息面每日打分数据访问。

    V0.75.2 数据隔离：**所有查询按当前用户过滤**；越权访问表现为「查不到」
    （返回空列表 / ``None``）—— 不用 403，避免泄露「该日期/槽位是否被别人用过」。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_date(self, score_date: date, user_id: int | None = None) -> list[NewsScore]:
        """当日已打分的全部槽位，按 slot 升序（第 1 次 → 第 3 次）。"""
        user_id = resolve_user_id(user_id)
        stmt = (
            select(NewsScore)
            .where(NewsScore.score_date == score_date, NewsScore.user_id == user_id)
            .order_by(NewsScore.slot)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_between(
        self, start: date, end: date, user_id: int | None = None
    ) -> list[NewsScore]:
        """区间内全部打分记录，按 (日期, 槽位) 升序（供复盘按日归档）。"""
        user_id = resolve_user_id(user_id)
        stmt = (
            select(NewsScore)
            .where(
                NewsScore.score_date >= start,
                NewsScore.score_date <= end,
                NewsScore.user_id == user_id,
            )
            .order_by(NewsScore.score_date, NewsScore.slot)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_dates(self, user_id: int | None = None) -> list[date]:
        """存在打分记录的全部日期（升序），用于决定复盘起始点。"""
        user_id = resolve_user_id(user_id)
        stmt = (
            select(NewsScore.score_date)
            .where(NewsScore.user_id == user_id)
            .distinct()
            .order_by(NewsScore.score_date)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_by_slot(
        self, score_date: date, slot: int, user_id: int | None = None
    ) -> NewsScore | None:
        """取指定日期 + 槽位的记录。"""
        user_id = resolve_user_id(user_id)
        stmt = select(NewsScore).where(
            NewsScore.score_date == score_date,
            NewsScore.slot == slot,
            NewsScore.user_id == user_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_date(self, score_date: date, user_id: int | None = None) -> NewsScore | None:
        """取当日**最新一次**打分（兼容旧调用：单值语义取最后一个槽位）。"""
        user_id = resolve_user_id(user_id)
        stmt = (
            select(NewsScore)
            .where(NewsScore.score_date == score_date, NewsScore.user_id == user_id)
            .order_by(NewsScore.slot.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_previous(
        self, score_date: date, slot: int, user_id: int | None = None
    ) -> NewsScore | None:
        """查询 (score_date, slot) 之前最近一次打分（供「沿用上次」）。

        同日更早槽位与历史日期都算，便于第 2/3 次打分一键沿用上一次研判。
        """
        user_id = resolve_user_id(user_id)
        stmt = (
            select(NewsScore)
            .where(
                or_(
                    NewsScore.score_date < score_date,
                    and_(NewsScore.score_date == score_date, NewsScore.slot < slot),
                ),
                NewsScore.user_id == user_id,
            )
            .order_by(NewsScore.score_date.desc(), NewsScore.slot.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_recent(self, limit: int = 15, user_id: int | None = None) -> list[NewsScore]:
        """最近若干条打分（跨日，按时间倒序），供历史回看。"""
        user_id = resolve_user_id(user_id)
        stmt = (
            select(NewsScore)
            .where(NewsScore.user_id == user_id)
            .order_by(NewsScore.score_date.desc(), NewsScore.slot.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def upsert(
        self,
        *,
        score_date: date,
        slot: int,
        score: float,
        direction: str,
        notes: str = "",
        basis: str = "",
        review_note: str = "",
        backfilled: int = 0,
        user_id: int | None = None,
    ) -> NewsScore:
        """写入指定槽位；已存在则覆盖（用于修正），并刷新打分时刻。

        ⚠ V0.80.0：``existing`` 的查找**必须按 user_id 过滤** ——
        否则 A 用户提交会命中 B 用户同日同槽位的记录并**直接覆盖**
        （V0.77.2 已知 ``basis`` 在 UPDATE 分支是硬覆盖 ⇒ 后果不可逆）。
        """
        user_id = resolve_user_id(user_id)
        now = datetime.now(timezone.utc)
        existing = await self.get_by_slot(score_date, slot, user_id=user_id)
        if existing is None:
            record = NewsScore(
                user_id=user_id,
                score_date=score_date,
                slot=slot,
                score=score,
                direction=direction,
                notes=notes,
                basis=basis,
                review_note=review_note,
                backfilled=backfilled,
                scored_at=now,
            )
            self._session.add(record)
        else:
            existing.score = score
            existing.direction = direction
            existing.notes = notes
            existing.basis = basis
            # 复盘批注可就地补充，不必重打分数
            existing.review_note = review_note or existing.review_note
            existing.backfilled = backfilled
            existing.scored_at = now
            record = existing
        await self._session.commit()
        await self._session.refresh(record)
        return record

    async def delete_slot(self, score_date: date, slot: int, user_id: int | None = None) -> bool:
        """撤销某次打分；不存在返回 False。

        V0.80.0：跨用户撤销一律返回 False（查不到即不可删）。
        """
        record = await self.get_by_slot(score_date, slot, user_id=user_id)
        if record is None:
            return False
        await self._session.delete(record)
        await self._session.commit()
        return True
