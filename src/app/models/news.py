"""消息面评估 ORM 模型：客户对投行黄金展望的每日打分。

V0.65.0 起由「每日一条」升级为「每日最多 3 次打分机会」：
同一 ``score_date`` 下按 ``slot`` 1/2/3 序号占用槽位，每次记录实际提交时刻，
当日有效分值按「越晚权重越高」的 1:2:3 加权合成（见 ``services/news.py``）。

V0.66.0 起为每条打分补充**结构化研判依据**（``basis`` 标签数组）与
**复盘支持字段**（``review_note`` 事后批注、``backfilled`` 补录标记），
供 ``services/review.py`` 按日期归档并统计「研判 → 后续金价」的命中率。
"""

from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# 每日打分机会上限（第 1/2/3 次）
MAX_DAILY_SLOTS = 3


class NewsScore(Base):
    """消息面每日打分（客户评估），每日最多 ``MAX_DAILY_SLOTS`` 条。

    - ``slot`` 1-3：当日第几次打分（序号制，不绑定具体时段）
    - ``scored_at``：该次打分的实际提交时刻（前端展示、判断先后）
    - ``score`` 0-100：>55 看多展望、<45 看空、50 中性
    - ``notes`` 客户研判备注（参考的投行观点/链接）
    - ``basis`` 研判依据（JSON 字符串数组，标签来自 ``services/review.py`` 预置清单）
    - ``backfilled`` 1 表示事后补录：补录时已知道后续走势，统计默认排除
    """

    __tablename__ = "news_scores"
    # ⚠ V0.80.0 数据隔离：唯一键从 ``(score_date, slot)`` 改为
    # ``(user_id, score_date, slot)``。
    #
    # 改前**只含日期与槽位** ⇒ 两个用户在同一日同一槽位**根本无法共存**
    # （实测 Bob 提交时 IntegrityError: UNIQUE constraint failed）。
    # 那不只是测试问题：它意味着「每个用户各自打分」在数据库层被禁止，
    # 多用户下第二个人根本无法使用打分功能。
    __table_args__ = (
        UniqueConstraint("user_id", "score_date", "slot", name="uq_news_scores_user_date_slot"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    score_date: Mapped[date] = mapped_column(
        Date, index=True, comment="打分日期（每日最多 3 条，按 slot 区分）"
    )
    slot: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", comment="当日第几次打分：1/2/3"
    )
    score: Mapped[float] = mapped_column(Float, comment="消息面看多强度 0-100")
    direction: Mapped[str] = mapped_column(
        String(12), default="neutral", comment="bullish/bearish/neutral"
    )
    notes: Mapped[str] = mapped_column(
        Text, default="", comment="客户研判备注（参考投行观点/链接）"
    )
    basis: Mapped[str] = mapped_column(Text, default="", comment="研判依据标签（JSON 数组字符串）")
    review_note: Mapped[str] = mapped_column(
        Text, default="", comment="事后复盘批注（结果出来后的反思）"
    )
    backfilled: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", comment="1=事后补录（统计默认排除）"
    )
    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="该次打分的提交时刻",
    )
    # ⚠ V0.80.0 数据隔离（任务 #159 第 2 批）：归属用户。
    # 此前本表**无 user_id** ⇒ 多用户启用后，一个用户能看到/改另一个用户的打分。
    # 取值 LEGACY_USER_ID(=1) 是单用户模式的既有语义，与 positions/accounts 一致。
    user_id: Mapped[int] = mapped_column(
        Integer, default=1, index=True, comment="归属用户 users.id（V0.75.2 加列）"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
