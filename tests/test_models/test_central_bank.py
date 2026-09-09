"""中央银行购金 ORM 模型单测：表结构 + 唯一约束 + upsert。"""

from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.central_bank import CentralBankPurchase


async def test_model_create_and_persist(db_session: AsyncSession) -> None:
    """新建一条记录 → 字段完整落库 → 重新查询可读回。"""
    rec = CentralBankPurchase(
        country_iso="CHN",
        country_name="中国",
        quarter="2026Q2",
        tonnes_net=33.0,
        source="IMF IRFCL",
        data_date=date(2026, 6, 30),
    )
    db_session.add(rec)
    await db_session.commit()

    got = await db_session.get(CentralBankPurchase, rec.id)
    assert got is not None
    assert got.country_iso == "CHN"
    assert got.country_name == "中国"
    assert got.quarter == "2026Q2"
    assert got.tonnes_net == pytest.approx(33.0)
    assert got.source == "IMF IRFCL"
    assert got.data_date == date(2026, 6, 30)
    assert got.created_at is not None
    assert got.updated_at is not None


async def test_unique_country_quarter(db_session: AsyncSession) -> None:
    """同一 (country_iso, quarter) 第二次插入违反唯一约束。"""
    db_session.add(
        CentralBankPurchase(
            country_iso="POL",
            country_name="波兰",
            quarter="2026Q2",
            tonnes_net=51.0,
            source="IMF IRFCL",
            data_date=date(2026, 6, 30),
        )
    )
    await db_session.commit()

    db_session.add(
        CentralBankPurchase(
            country_iso="POL",
            country_name="波兰",
            quarter="2026Q2",
            tonnes_net=99.0,  # 不同值，但唯一约束会拒绝
            source="IMF IRFCL",
            data_date=date(2026, 6, 30),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_negative_tonnes_allowed(db_session: AsyncSession) -> None:
    """负值（卖出）允许落库，匹配俄罗斯/土耳其历史卖出场景。"""
    rec = CentralBankPurchase(
        country_iso="RUS",
        country_name="俄罗斯",
        quarter="2020Q2",
        tonnes_net=-26.1,
        source="IMF IRFCL",
        data_date=date(2020, 6, 30),
    )
    db_session.add(rec)
    await db_session.commit()

    got = await db_session.get(CentralBankPurchase, rec.id)
    assert got.tonnes_net == pytest.approx(-26.1)
    assert got.tonnes_net < 0


async def test_repr_contains_key_fields(db_session: AsyncSession) -> None:
    """__repr__ 包含 ISO/季度/吨数（便于日志）。"""
    rec = CentralBankPurchase(
        country_iso="CHN",
        country_name="中国",
        quarter="2026Q2",
        tonnes_net=33.0,
        source="IMF IRFCL",
        data_date=date(2026, 6, 30),
    )
    text = repr(rec)
    assert "CHN" in text
    assert "2026Q2" in text
    assert "+33.0t" in text
