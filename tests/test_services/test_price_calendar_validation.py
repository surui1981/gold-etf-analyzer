"""V0.67.0 价格日历 schema 校验测试。

覆盖 :func:`app.repositories.review._validate_bar` / :_validate_change_pct`
及 :meth:`GoldPriceRepository.upsert_many` 在脏数据场景下的行为：

- ``close <= 0`` → 整批拒绝（防脏数据污染）
- ``close`` 为 NaN → 整批拒绝
- ``source`` 不在白名单 ``{live, manual, import}`` → 整批拒绝
- 单日涨跌幅 > ±50% → 跳过该条目，其余条目仍写入
- 混合数据（一条脏 + 多条正常）→ 整批拒绝（防半成功状态）
- 合法数据正常写入且涨跌幅正确
"""

from __future__ import annotations

from datetime import date

import pytest

from app.repositories.db import async_session_factory
from app.repositories.review import GoldPriceRepository, _validate_bar, _validate_change_pct

# ---------- 单元：_validate_bar ----------


def test_v067_validate_bar_accepts_positive_close_and_valid_source() -> None:
    """合法 close + 合法 source 通过校验。"""
    assert _validate_bar("ny", date(2026, 1, 1), 100.0, "live") is None
    assert _validate_bar("etf", date(2026, 1, 1), 5.67, "manual") is None
    assert _validate_bar("gram", date(2026, 1, 1), 720.5, "import") is None


def test_v067_validate_bar_rejects_zero_close() -> None:
    """close = 0 视为无效（行情源失败兜底常返回 0）。"""
    err = _validate_bar("ny", date(2026, 1, 1), 0.0, "live")
    assert err is not None
    assert "must be > 0" in err


def test_v067_validate_bar_rejects_negative_close() -> None:
    """close < 0 视为无效（不可能出现负价）。"""
    err = _validate_bar("ny", date(2026, 1, 1), -1.5, "live")
    assert err is not None
    assert "must be > 0" in err


def test_v067_validate_bar_rejects_nan_close() -> None:
    """close 为 NaN 时拒绝（NaN != NaN，可区分）。"""
    err = _validate_bar("ny", date(2026, 1, 1), float("nan"), "live")
    assert err is not None
    assert "must be > 0" in err


def test_v067_validate_bar_rejects_unknown_source() -> None:
    """source 不在白名单时拒绝（白名单：live / manual / import / test）。"""
    err = _validate_bar("ny", date(2026, 1, 1), 100.0, "evil_source")
    assert err is not None
    assert "invalid source" in err


def test_v067_validate_bar_accepts_empty_source() -> None:
    """source=''（默认占位）放行：允许调用方延后回填来源。"""
    assert _validate_bar("ny", date(2026, 1, 1), 100.0, "") is None


# ---------- 单元：_validate_change_pct ----------


def test_v067_validate_change_pct_within_range() -> None:
    """±50% 内通过。"""
    assert _validate_change_pct(0.0) is True
    assert _validate_change_pct(25.5) is True
    assert _validate_change_pct(-49.99) is True
    assert _validate_change_pct(50.0) is True  # 边界值放行


def test_v067_validate_change_pct_exceeds_range() -> None:
    """超出 ±50% 拒绝（除拆股 / 熔断等极端情况不应出现）。"""
    assert _validate_change_pct(50.01) is False
    assert _validate_change_pct(-80.0) is False
    assert _validate_change_pct(200.0) is False


# ---------- 集成：upsert_many ----------


@pytest.mark.asyncio
async def test_v067_upsert_many_normal_writes_all() -> None:
    """合法数据整批写入。"""
    async with async_session_factory() as session:
        repo = GoldPriceRepository(session)
        n = await repo.upsert_many(
            target="ny",
            bars=[(date(2026, 1, 1), 100.0), (date(2026, 1, 2), 102.0)],
            source="live",
        )
        assert n == 2


@pytest.mark.asyncio
async def test_v067_upsert_many_rejects_batch_with_zero_close() -> None:
    """批内任一 close=0 → 整批拒绝（防半成功状态）。"""
    async with async_session_factory() as session:
        repo = GoldPriceRepository(session)
        with pytest.raises(ValueError, match="must be > 0"):
            await repo.upsert_many(
                target="ny",
                bars=[(date(2026, 1, 1), 100.0), (date(2026, 1, 2), 0.0)],
                source="live",
            )
        # 关键断言：脏批次被整批拒绝，库中不应有任何残留
        rows = await repo.list_range("ny", start=date(2026, 1, 1), end=date(2026, 1, 2))
        assert rows == []


@pytest.mark.asyncio
async def test_v067_upsert_many_rejects_batch_with_bad_source() -> None:
    """批内 source 非法 → 整批拒绝。"""
    async with async_session_factory() as session:
        repo = GoldPriceRepository(session)
        with pytest.raises(ValueError, match="invalid source"):
            await repo.upsert_many(
                target="ny",
                bars=[(date(2026, 2, 1), 100.0)],
                source="untrusted",
            )


@pytest.mark.asyncio
async def test_v067_upsert_many_skips_big_swing_keeps_others() -> None:
    """单日涨跌幅超 ±50% → 跳过该条目，其余条目正常写入。"""
    async with async_session_factory() as session:
        repo = GoldPriceRepository(session)
        # 100 → 1000（+900%）超界应跳过；100 → 102 与 1000 → 1100（+10%）正常
        n = await repo.upsert_many(
            target="ny",
            bars=[
                (date(2026, 3, 1), 100.0),
                (date(2026, 3, 2), 1000.0),  # 超界跳过
                (date(2026, 3, 3), 1100.0),
            ],
            source="live",
        )
        assert n == 2  # 仅 2 条写入
        rows = await repo.list_range("ny", start=date(2026, 3, 1), end=date(2026, 3, 5))
        dates = {r.price_date: r for r in rows}
        assert date(2026, 3, 1) in dates
        assert date(2026, 3, 2) not in dates  # 跳过
        assert date(2026, 3, 3) in dates


@pytest.mark.asyncio
async def test_v067_upsert_many_nan_close_rejected() -> None:
    """NaN close → 整批拒绝（避免 SQL 写入 NaN 后下游统计异常）。"""
    async with async_session_factory() as session:
        repo = GoldPriceRepository(session)
        bars = [(date(2026, 4, 1), float("nan"))]
        with pytest.raises(ValueError):
            await repo.upsert_many(target="ny", bars=bars, source="live")


@pytest.mark.asyncio
async def test_v067_upsert_many_empty_bars_no_validation_error() -> None:
    """空 bars 走原早退路径（不触发任何校验）。"""
    async with async_session_factory() as session:
        repo = GoldPriceRepository(session)
        # 防御性：空 bars 不应抛错（与 V0.66.0 行为兼容）
        n = await repo.upsert_many(target="ny", bars=[], source="live")
        assert n == 0
