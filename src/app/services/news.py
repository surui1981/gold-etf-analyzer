"""消息面服务：客户对主流财经网站投行黄金展望的每日评估打分。

消息面指数 0-100（>55 看多、<45 看空、50 中性），由客户研判后打分，
汇入每日评估（综合趋势指数 = 技术×30% + 宏观×40% + 消息面×30%）。
"""

from datetime import date

from app.repositories.news import NewsScoreRepository
from app.schemas.common import DirectionSignal
from app.schemas.news import NewsScoreIn, NewsScoreOut
from app.utils.logger import get_logger

logger = get_logger(__name__)

NEUTRAL_SCORE = 50.0  # 未打分时的中性参考


class NewsScoreService:
    """消息面每日打分管理。"""

    def __init__(self, repo: NewsScoreRepository) -> None:
        self._repo = repo

    async def get_today(self) -> NewsScoreOut:
        """当日打分；未打返回中性参考（scored=False）并附带上一次打分。"""
        today = date.today()
        record = await self._repo.get_by_date(today)
        prev = await self._repo.get_latest_before(today)

        last_score = float(prev.score) if prev is not None else None
        last_date = prev.score_date if prev is not None else None
        last_notes = prev.notes if prev is not None else ""
        if record is None:
            return NewsScoreOut(
                score_date=date.today(),
                score=NEUTRAL_SCORE,
                direction=DirectionSignal.NEUTRAL,
                notes="",
                scored=False,
                last_score=last_score,
                last_date=last_date,
                last_notes=last_notes,
            )
        return NewsScoreOut(
            score_date=record.score_date,
            score=record.score,
            direction=DirectionSignal(record.direction),
            notes=record.notes,
            scored=True,
            last_score=last_score,
            last_date=last_date,
            last_notes=last_notes,
        )

    async def get_today_score(self) -> float:
        """当日消息面指数（供趋势服务合成）；未打分返回中性 50。"""
        out = await self.get_today()
        return out.score

    async def save_today(self, payload: NewsScoreIn) -> NewsScoreOut:
        """保存当日打分（同日覆盖）。"""
        record = await self._repo.upsert(
            score_date=date.today(),
            score=payload.score,
            direction=payload.direction.value,
            notes=payload.notes,
        )
        logger.info(
            "News score saved: %s, score=%.1f (%s)",
            record.score_date, record.score, record.direction,
        )
        return NewsScoreOut(
            score_date=record.score_date,
            score=record.score,
            direction=DirectionSignal(record.direction),
            notes=record.notes,
            scored=True,
        )
