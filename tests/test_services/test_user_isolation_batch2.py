"""V0.80.0 数据隔离第 2 批：``news_scores`` / ``analysis_records`` /
``push_subscriptions`` 三张表的 ``user_id`` 隔离回归测试。

背景（第1 批遗留的缺口）
----------------------
V0.75.2 第 1 批（2026-10-06）给 ``positions`` / ``accounts`` 做了仓储层过滤，
但**这三张表当时连 ``user_id`` 列都没有** ⇒ 多用户启用后：

- A 用户的「消息面打分」（含研判依据 ``basis`` 与复盘批注 ``review_note``）
  可被 B 用户读到；
- B 用户提交打分会**命中 A 用户的记录并直接覆盖** ——
  且 ``basis`` 在 UPDATE 分支是**硬覆盖**（V0.77.2 已知），后果不可逆；
- 机会分析记录（含因子明细）跨用户可见；
- 推送订阅按 ``endpoint`` 匹配 ⇒ 同设备换用户会覆盖密钥，推送到错的人。

三条核心语义（与第 1 批一致）
----------------------------
1. 未开启认证（默认单用户）⇒ 解析为 ``LEGACY_USER_ID``，行为与旧版逐字一致；
2. 越权访问 ⇒ 表现为「不存在」（``None`` / 空列表 / ``False``），由服务层转 404；
3. ``ALL_USERS`` 是**显式**的全库哨兵值，只有服务级操作可用
   （告警广播 / 管理员验证推送）—— 不靠「忘了传 ⇒ 不过滤」实现全库查询。

⚠ 为什么不能用「同步夹具 set + teardown reset」切换身份
--------------------------------------------------------
``contextvars`` 的 Token 只能在**创建它的 Context** 里 reset，而 pytest-asyncio
给每个用例单独的 Context，teardown 必然报 ``was created in a different Context``。
故沿用第 1 批的 :func:`acting_as`（在同一协程内 set/reset）。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

import pytest

from app.models.analysis import AnalysisRecord
from app.models.news import NewsScore
from app.models.push import PushSubscription
from app.models.user import LEGACY_USER_ID
from app.repositories.analysis import AnalysisRepository
from app.repositories.news import NewsScoreRepository
from app.repositories.push import PushSubscriptionRepository
from app.utils.user_scope import ALL_USERS, reset_user_id, set_user_id


@contextmanager
def acting_as(uid: int | None) -> Iterator[None]:
    """以指定用户身份执行代码块；退出时在**同一 Context** 内还原。"""
    token = set_user_id(uid)
    try:
        yield
    finally:
        reset_user_id(token)


ALICE = 101
BOB = 202


@pytest.fixture
def news_repo(db_session) -> NewsScoreRepository:
    return NewsScoreRepository(db_session)


@pytest.fixture
def analysis_repo(db_session) -> AnalysisRepository:
    return AnalysisRepository(db_session)


@pytest.fixture
def push_repo(db_session) -> PushSubscriptionRepository:
    return PushSubscriptionRepository(db_session)


# ─────────────── news_scores ───────────────


async def test_news_read_is_isolated(news_repo: NewsScoreRepository) -> None:
    """★ 跨用户读不到：Alice 打分对 Bob 不可见。"""
    with acting_as(ALICE):
        await news_repo.upsert(
            score_date=date(2026, 10, 7), slot=1, score=70.0, direction="bullish"
        )
    with acting_as(BOB):
        assert await news_repo.list_by_date(date(2026, 10, 7)) == []
        assert await news_repo.get_by_slot(date(2026, 10, 7), 1) is None
        assert await news_repo.get_by_date(date(2026, 10, 7)) is None
        assert await news_repo.list_dates() == []
        assert await news_repo.list_recent() == []


async def test_news_upsert_does_not_overwrite_other_user(news_repo: NewsScoreRepository) -> None:
    """★★ 最严重的一条：Bob 提交**不得**覆盖 Alice 同日同槽位的记录。

    ``basis`` 在 UPDATE 分支是硬覆盖（V0.77.2 已知）⇒ 若这里越权，
    Alice 认真勾选的研判依据会被静默抹掉且不可恢复。
    """
    with acting_as(ALICE):
        await news_repo.upsert(
            score_date=date(2026, 10, 7),
            slot=1,
            score=70.0,
            direction="bullish",
            basis='["趋势转强"]',
        )
    with acting_as(BOB):
        await news_repo.upsert(
            score_date=date(2026, 10, 7),
            slot=1,
            score=30.0,
            direction="bearish",
            basis='["风险上升"]',
        )
    # Alice 的记录必须原样保留
    with acting_as(ALICE):
        rec = await news_repo.get_by_slot(date(2026, 10, 7), 1)
        assert rec is not None
        assert rec.score == 70.0
        assert rec.direction == "bullish"
        assert "趋势转强" in rec.basis
    # Bob 有自己的一条
    with acting_as(BOB):
        rec_b = await news_repo.get_by_slot(date(2026, 10, 7), 1)
        assert rec_b is not None
        assert rec_b.score == 30.0


async def test_news_delete_slot_cannot_cross_users(news_repo: NewsScoreRepository) -> None:
    """跨用户撤销返回 False（查不到即不可删）。"""
    with acting_as(ALICE):
        await news_repo.upsert(
            score_date=date(2026, 10, 7), slot=2, score=50.0, direction="neutral"
        )
    with acting_as(BOB):
        assert await news_repo.delete_slot(date(2026, 10, 7), 2) is False
    with acting_as(ALICE):
        assert await news_repo.delete_slot(date(2026, 10, 7), 2) is True


async def test_news_list_between_is_isolated(news_repo: NewsScoreRepository) -> None:
    """区间查询同样按用户过滤（复盘页用它算命中率）。"""
    with acting_as(ALICE):
        await news_repo.upsert(
            score_date=date(2026, 10, 1), slot=1, score=60.0, direction="bullish"
        )
    with acting_as(BOB):
        rows = await news_repo.list_between(date(2026, 9, 1), date(2026, 10, 31))
        assert rows == []


async def test_news_get_previous_is_isolated(news_repo: NewsScoreRepository) -> None:
    """「沿用上次」不能取到别人的历史打分。"""
    with acting_as(ALICE):
        await news_repo.upsert(
            score_date=date(2026, 10, 1), slot=1, score=61.0, direction="bullish"
        )
    with acting_as(BOB):
        assert await news_repo.get_previous(date(2026, 10, 7), 1) is None


# ─────────────── analysis_records ───────────────


async def test_analysis_create_tags_owner_and_list_isolated(
    analysis_repo: AnalysisRepository, db_session
) -> None:
    """★ create 落库带归属用户；list_recent 只返回自己的。"""
    with acting_as(ALICE):
        await analysis_repo.create(
            dxy=105.0,
            us10y_yield=4.2,
            real_rate=1.8,
            inflation_expectation=2.4,
            risk_off=3,
            score=72.0,
            window="strong",
            signal="bullish",
            factors_detail="{}",
        )
    with acting_as(BOB):
        assert await analysis_repo.list_recent() == []

    # 直接查库核对 user_id 确实落对了
    rows = (
        (await db_session.execute(__import__("sqlalchemy").select(AnalysisRecord))).scalars().all()
    )
    assert [r.user_id for r in rows] == [ALICE]


async def test_analysis_create_honors_explicit_user_id(analysis_repo: AnalysisRepository) -> None:
    """显式传 user_id 时以它为准（系统级写入路径）。"""
    await analysis_repo.create(
        user_id=BOB,
        dxy=105.0,
        us10y_yield=4.2,
        real_rate=1.8,
        inflation_expectation=2.4,
        risk_off=3,
        score=72.0,
        window="strong",
        signal="bullish",
        factors_detail="{}",
    )
    rows = await analysis_repo.list_recent(user_id=BOB)
    assert len(rows) == 1
    assert await analysis_repo.list_recent(user_id=ALICE) == []


# ─────────────── push_subscriptions ───────────────


async def test_push_upsert_same_endpoint_different_users_coexists(
    push_repo: PushSubscriptionRepository,
) -> None:
    """★★ 同设备换用户不得互相覆盖：两个用户各自一条订阅。

    改前按 ``endpoint`` 单列匹配 ⇒ B 用户会把 A 用户的密钥覆盖掉，
    推送就发到了错的人手里。
    """
    with acting_as(ALICE):
        await push_repo.upsert(endpoint="https://push.example/ALICE", p256dh="ak_A", auth="auth_A")
    with acting_as(BOB):
        await push_repo.upsert(endpoint="https://push.example/ALICE", p256dh="ak_B", auth="auth_B")

    with acting_as(ALICE):
        subs = await push_repo.list_active()
        assert len(subs) == 1
        assert subs[0].p256dh == "ak_A"
    with acting_as(BOB):
        subs = await push_repo.list_active()
        assert len(subs) == 1
        assert subs[0].p256dh == "ak_B"


async def test_push_list_active_isolated_by_default(push_repo: PushSubscriptionRepository) -> None:
    """默认只返回当前用户的订阅。"""
    with acting_as(ALICE):
        await push_repo.upsert(endpoint="https://push.example/A", p256dh="k", auth="s")
    with acting_as(BOB):
        await push_repo.upsert(endpoint="https://push.example/B", p256dh="k", auth="s")

    with acting_as(ALICE):
        subs = await push_repo.list_active()
        assert [s.endpoint for s in subs] == ["https://push.example/A"]
    with acting_as(BOB):
        subs = await push_repo.list_active()
        assert [s.endpoint for s in subs] == ["https://push.example/B"]


async def test_push_all_users_sentinel_returns_everyone(
    push_repo: PushSubscriptionRepository,
) -> None:
    """``ALL_USERS`` 显式哨兵值 ⇒ 返回全库（服务级告警广播用）。"""
    with acting_as(ALICE):
        await push_repo.upsert(endpoint="https://push.example/A", p256dh="k", auth="s")
    with acting_as(BOB):
        await push_repo.upsert(endpoint="https://push.example/B", p256dh="k", auth="s")

    with acting_as(ALICE):
        all_subs = await push_repo.list_active(user_id=ALL_USERS)
        assert {s.endpoint for s in all_subs} == {
            "https://push.example/A",
            "https://push.example/B",
        }


async def test_push_archive_and_delete_cannot_cross_users(
    push_repo: PushSubscriptionRepository,
) -> None:
    """跨用户归档 / 退订一律 False。"""
    with acting_as(ALICE):
        await push_repo.upsert(endpoint="https://push.example/X", p256dh="k", auth="s")
    with acting_as(BOB):
        assert await push_repo.archive_by_endpoint("https://push.example/X") is False
        assert await push_repo.delete_by_endpoint("https://push.example/X") is False
    with acting_as(ALICE):
        assert await push_repo.archive_by_endpoint("https://push.example/X") is True


# ─────────────── 单用户模式回归 ───────────────


async def test_single_user_mode_unchanged(news_repo: NewsScoreRepository) -> None:
    """⚠ 默认（未开启认证）⇒ 仍解析为 LEGACY_USER_ID，行为与旧版一致。"""
    await news_repo.upsert(score_date=date(2026, 10, 7), slot=1, score=66.0, direction="bullish")
    rows = await news_repo.list_by_date(date(2026, 10, 7))
    assert len(rows) == 1
    assert rows[0].user_id == LEGACY_USER_ID
    # 同一身份再读仍可见（无上下文时不抛错）
    assert len(await news_repo.list_recent()) == 1


def test_all_users_sentinel_does_not_collide_with_real_user() -> None:
    """``ALL_USERS`` 不与任何真实用户 id 冲突（真实 id 从 1 起）。"""
    assert ALL_USERS == 0
    assert LEGACY_USER_ID == 1
    assert ALL_USERS != LEGACY_USER_ID


def test_all_three_tables_have_user_id_column() -> None:
    """三张表都声明了 ``user_id``（漏一列 ⇒ 过滤条件恒真）。"""
    for model in (NewsScore, AnalysisRecord, PushSubscription):
        assert hasattr(model, "user_id"), f"{model.__tablename__} 缺 user_id 列"
