"""消息面服务：客户对主流财经网站投行黄金展望的每日评估打分。

V0.65.0 起每日提供 **3 次打分机会**（slot 1/2/3，按序占用，各自记录提交时刻），
当日有效分值按「越晚权重越高」的 1:2:3 加权合成，汇入每日评估：
综合趋势指数 = 技术×30% + 宏观×40% + 消息面×30%。

加权口径（槽位 i 权重 = i）::

    effective = Σ(weight_i × score_i) / Σ(weight_i)

仅第 1 次打分为该次分值；第 2 次起按 1:2 / 1:2:3 归一加权，
使最新研判对当日指数影响最大。

V0.66.0：补充结构化研判依据（``basis``）、事后复盘批注（``review_note``），
并支持按指定日期**补录**历史研判（标记 ``backfilled``，复盘统计默认排除）。
"""

import json
from datetime import date, datetime, timezone

from app.models.news import MAX_DAILY_SLOTS
from app.repositories.news import NewsScoreRepository
from app.schemas.common import DirectionSignal
from app.schemas.news import (
    NewsHistoryItem,
    NewsHistoryOut,
    NewsScoreIn,
    NewsScoreOut,
    NewsSlotOut,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

NEUTRAL_SCORE = 50.0  # 未打分时的中性参考

# 槽位权重：越晚权重越高（第 1/2/3 次 → 1/2/3）
SLOT_WEIGHTS: dict[int, int] = {n: n for n in range(1, MAX_DAILY_SLOTS + 1)}

BULLISH_THRESHOLD = 55.0
BEARISH_THRESHOLD = 45.0


def direction_of(score: float) -> DirectionSignal:
    """按分值判定方向：>55 看多、<45 看空、其余中性。"""
    if score > BULLISH_THRESHOLD:
        return DirectionSignal.BULLISH
    if score < BEARISH_THRESHOLD:
        return DirectionSignal.BEARISH
    return DirectionSignal.NEUTRAL


def parse_basis(raw: str | None) -> list[str]:
    """把库中的 ``basis`` 文本解析为标签列表（容错：非法 JSON 返回空表）。"""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if isinstance(parsed, list):
        return [str(x) for x in parsed if str(x).strip()]
    return []


def dump_basis(tags) -> str:
    """把标签列表序列化为库中存储的 JSON 文本。"""
    if not tags:
        return ""
    cleaned = [str(t).strip() for t in tags if str(t).strip()]
    return json.dumps(cleaned, ensure_ascii=False) if cleaned else ""


def aggregate_slots(records: list) -> tuple[float, str, bool]:
    """按槽位权重合成当日有效分值 → (分值, 算式说明, 是否加权合成)。

    复盘服务（``services/review.py``）复用本函数，保证「当日有效分值」
    在打分页与复盘页口径完全一致。
    """
    if not records:
        return NEUTRAL_SCORE, "", False
    total_w = sum(SLOT_WEIGHTS.get(r.slot, 1) for r in records)
    acc = sum(SLOT_WEIGHTS.get(r.slot, 1) * float(r.score) for r in records)
    effective = round(acc / total_w, 1)
    if len(records) == 1:
        return effective, "", False
    terms = " + ".join(f"{SLOT_WEIGHTS.get(r.slot, 1)}×{float(r.score):g}" for r in records)
    return effective, f"({terms}) ÷ {total_w}", True


def _as_utc(dt: datetime | None) -> datetime | None:
    """SQLite 取出的时间戳不带时区，按 UTC 补齐，避免前端按本地时区误读。"""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


class NewsScoreService:
    """消息面每日打分管理（每日最多 3 次，加权合成当日有效分值）。"""

    def __init__(self, repo: NewsScoreRepository) -> None:
        self._repo = repo

    # ---------- 内部工具 ----------

    @staticmethod
    def _next_free(records: list) -> int | None:
        """下一个空闲槽位（取最小未用序号）；三次用尽返回 None。"""
        used = {r.slot for r in records}
        for slot in range(1, MAX_DAILY_SLOTS + 1):
            if slot not in used:
                return slot
        return None

    @staticmethod
    def _aggregate(records: list) -> tuple[float, str, bool]:
        """按槽位权重合成当日有效分值（兼容保留，实现见 ``aggregate_slots``）。"""
        return aggregate_slots(records)

    # ---------- 查询 ----------

    async def get_today(self) -> NewsScoreOut:
        """当日打分：返回 3 个槽位明细 + 加权有效分值；未打分为中性参考。"""
        today = date.today()
        records = await self._repo.list_by_date(today)
        next_slot = self._next_free(records)

        # 「沿用上次」参考位：下一个待填槽位（三次用尽时取最后槽位之后）
        slot_ref = next_slot if next_slot is not None else MAX_DAILY_SLOTS + 1
        prev = await self._repo.get_previous(today, slot_ref)

        slots = [
            NewsSlotOut(
                slot=r.slot,
                score=float(r.score),
                direction=DirectionSignal(r.direction),
                notes=r.notes or "",
                weight=SLOT_WEIGHTS.get(r.slot, 1),
                scored_at=_as_utc(r.scored_at),
                basis=parse_basis(r.basis),
                review_note=r.review_note or "",
                backfilled=bool(r.backfilled),
            )
            for r in records
        ]
        effective, formula, weighted = self._aggregate(records)
        latest_notes = records[-1].notes if records else ""

        return NewsScoreOut(
            score_date=today,
            score=effective,
            direction=direction_of(effective),
            notes=latest_notes,
            scored=bool(records),
            weighted=weighted,
            slots=slots,
            used_slots=len(records),
            max_slots=MAX_DAILY_SLOTS,
            remaining_slots=MAX_DAILY_SLOTS - len(records),
            next_slot=next_slot,
            formula=formula,
            last_score=float(prev.score) if prev is not None else None,
            last_date=prev.score_date if prev is not None else None,
            last_notes=(prev.notes or "") if prev is not None else "",
        )

    async def get_today_score(self) -> float:
        """当日消息面有效分值（供趋势服务合成）；未打分返回中性 50。"""
        out = await self.get_today()
        return out.score

    async def get_history(self, limit: int = 15) -> NewsHistoryOut:
        """最近若干条打分记录（跨日、时间倒序），供历史回看。"""
        records = await self._repo.list_recent(limit)
        items = [
            NewsHistoryItem(
                score_date=r.score_date,
                slot=r.slot,
                score=float(r.score),
                direction=DirectionSignal(r.direction),
                notes=r.notes or "",
                scored_at=_as_utc(r.scored_at),
                weight=SLOT_WEIGHTS.get(r.slot, 1),
                basis=parse_basis(r.basis),
                backfilled=bool(r.backfilled),
            )
            for r in records
        ]
        return NewsHistoryOut(items=items, total=len(items))

    # ---------- 写入 ----------

    async def save_today(self, payload: NewsScoreIn) -> NewsScoreOut:
        """保存一次打分。

        - ``slot`` 留空 → 自动占用目标日期下一个空闲槽位（第 1 → 2 → 3 次）；
        - 三次用尽后再留空提交 → 报错，避免静默覆盖既有研判；
        - 显式指定 ``slot`` → 覆盖/修改该槽位（用于修正）；
        - ``score_date`` 传历史日期 → 补录，记录标记 ``backfilled``
          （补录时已知后续走势，复盘统计默认排除，避免前视偏差）。

        Returns:
            该日期的最新打分状态（``score_date`` 对应目标日期）。
        """
        today = date.today()
        target_date = payload.score_date or today
        if target_date > today:
            raise ValueError("打分日期不能晚于今天")
        backfilled = 1 if target_date < today else 0

        records = await self._repo.list_by_date(target_date)
        used = {r.slot for r in records}

        if payload.slot is not None:
            target: int = payload.slot
            overwrite = target in used
        else:
            next_slot = self._next_free(records)
            if next_slot is None:
                raise ValueError(
                    f"{target_date} 的 {MAX_DAILY_SLOTS} 次打分机会已用完，"
                    f"如需修改请指定要覆盖的槽位（slot=1~{MAX_DAILY_SLOTS}）"
                )
            target = next_slot
            overwrite = False

        record = await self._repo.upsert(
            score_date=target_date,
            slot=target,
            score=payload.score,
            direction=payload.direction.value,
            notes=payload.notes,
            basis=dump_basis(payload.basis),
            review_note=payload.review_note,
            backfilled=backfilled,
        )
        logger.info(
            "News score saved: %s slot=%d%s%s, score=%.1f (%s)",
            record.score_date,
            record.slot,
            " [覆盖]" if overwrite else "",
            " [补录]" if backfilled else "",
            record.score,
            record.direction,
        )

        # 仅当日打分会影响综合指数 → 失效 served cache（补录历史不影响当日）
        if target_date == today:
            # 延迟导入避免循环依赖（TrendService 也引用 NewsScoreService）
            from app.services.trend import TrendService

            TrendService.invalidate_for_news()

        if target_date != today:
            return await self.get_by_date(target_date)
        return await self.get_today()

    async def get_by_date(self, score_date: date) -> NewsScoreOut:
        """指定日期的打分状态（结构与 ``get_today`` 一致，供补录后回显）。"""
        records = await self._repo.list_by_date(score_date)
        next_slot = self._next_free(records)
        slots = [
            NewsSlotOut(
                slot=r.slot,
                score=float(r.score),
                direction=DirectionSignal(r.direction),
                notes=r.notes or "",
                weight=SLOT_WEIGHTS.get(r.slot, 1),
                scored_at=_as_utc(r.scored_at),
                basis=parse_basis(r.basis),
                review_note=r.review_note or "",
                backfilled=bool(r.backfilled),
            )
            for r in records
        ]
        effective, formula, weighted = self._aggregate(records)
        latest = records[-1] if records else None
        return NewsScoreOut(
            score_date=score_date,
            score=effective,
            direction=direction_of(effective),
            notes=(latest.notes or "") if latest else "",
            scored=bool(records),
            weighted=weighted,
            slots=slots,
            used_slots=len(records),
            max_slots=MAX_DAILY_SLOTS,
            remaining_slots=MAX_DAILY_SLOTS - len(records),
            next_slot=next_slot,
            formula=formula,
        )

    async def delete_slot(self, slot: int, score_date: date | None = None) -> NewsScoreOut:
        """撤销指定日期某一次打分，释放该槽位。"""
        if not 1 <= slot <= MAX_DAILY_SLOTS:
            raise ValueError(f"槽位需在 1~{MAX_DAILY_SLOTS} 之间")
        target_date = score_date or date.today()
        removed = await self._repo.delete_slot(target_date, slot)
        if not removed:
            raise ValueError(f"{target_date} 第 {slot} 次打分不存在，无法撤销")
        logger.info("News score deleted: %s slot=%d", target_date, slot)

        if target_date == date.today():
            from app.services.trend import TrendService

            TrendService.invalidate_for_news()
        return await self.get_by_date(target_date)
