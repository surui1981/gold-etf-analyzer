"""央行购金 Service 单测：摘要、Top 排序、明细查询。"""

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.central_bank import CentralBankPurchase
from app.repositories.central_bank import CentralBankPurchaseRepository
from app.services.central_bank import CentralBankService


async def _seed(db: AsyncSession, rows: list[dict]) -> None:
    for r in rows:
        db.add(CentralBankPurchase(**r))
    await db.commit()


def _svc(db: AsyncSession) -> CentralBankService:
    return CentralBankService(CentralBankPurchaseRepository(db))


async def test_summary_empty_db(db_session: AsyncSession) -> None:
    """空库：摘要为占位值（不抛异常）。"""
    out = await _svc(db_session).summary()
    assert out.t12m_total == 0.0
    assert out.t12m_window == "-"
    assert out.country_count == 0
    assert out.latest_data_quarter == "-"


async def test_summary_t12m_and_window(db_session: AsyncSession) -> None:
    """T12M = 最近 4 季度合计；窗口标签格式 "2025Q3–2026Q2"。"""
    rows = [
        # T12M（2025Q3–2026Q2）
        {"country_iso": "CHN", "country_name": "中国", "quarter": "2025Q3",
         "tonnes_net": 30.0, "source": "IMF IRFCL", "data_date": date(2025, 9, 30)},
        {"country_iso": "CHN", "country_name": "中国", "quarter": "2025Q4",
         "tonnes_net": 25.0, "source": "IMF IRFCL", "data_date": date(2025, 12, 31)},
        {"country_iso": "CHN", "country_name": "中国", "quarter": "2026Q1",
         "tonnes_net": 5.0, "source": "IMF IRFCL", "data_date": date(2026, 3, 31)},
        {"country_iso": "CHN", "country_name": "中国", "quarter": "2026Q2",
         "tonnes_net": 33.0, "source": "IMF IRFCL", "data_date": date(2026, 6, 30)},
        # T12M 之外（应被排除）
        {"country_iso": "CHN", "country_name": "中国", "quarter": "2025Q2",
         "tonnes_net": 999.0, "source": "IMF IRFCL", "data_date": date(2025, 6, 30)},
    ]
    await _seed(db_session, rows)

    out = await _svc(db_session).summary()
    # T12M = 30+25+5+33 = 93
    assert out.t12m_total == pytest.approx(93.0)
    assert out.t12m_window == "2025Q3–2026Q2"
    assert out.current_quarter == "2026Q2"
    # 当前季度合计：仅 CHN 33.0
    assert out.current_quarter_total == pytest.approx(33.0)
    assert out.country_count == 1


async def test_top_buyers_by_year(db_session: AsyncSession) -> None:
    """某年度 Top N：按当年 4 季度合计降序。"""
    rows = [
        {"country_iso": "CHN", "country_name": "中国", "quarter": "2025Q1",
         "tonnes_net": 30.0, "source": "IMF IRFCL", "data_date": date(2025, 3, 31)},
        {"country_iso": "CHN", "country_name": "中国", "quarter": "2025Q2",
         "tonnes_net": 25.0, "source": "IMF IRFCL", "data_date": date(2025, 6, 30)},
        {"country_iso": "POL", "country_name": "波兰", "quarter": "2025Q1",
         "tonnes_net": 50.0, "source": "IMF IRFCL", "data_date": date(2025, 3, 31)},
        {"country_iso": "TUR", "country_name": "土耳其", "quarter": "2025Q2",
         "tonnes_net": 40.0, "source": "IMF IRFCL", "data_date": date(2025, 6, 30)},
        # 2024 年（应被排除）
        {"country_iso": "CHN", "country_name": "中国", "quarter": "2024Q4",
         "tonnes_net": 999.0, "source": "IMF IRFCL", "data_date": date(2024, 12, 31)},
    ]
    await _seed(db_session, rows)

    top = await _svc(db_session).top_buyers(year=2025, limit=3)
    assert len(top) == 3
    # CHN 累计 30+25=55 > POL 50 > TUR 40
    assert top[0].country_iso == "CHN"
    assert top[0].rank == 1
    assert top[0].tonnes_net == pytest.approx(55.0)
    assert top[1].country_iso == "POL"
    assert top[2].country_iso == "TUR"


async def test_list_purchases_filters(db_session: AsyncSession) -> None:
    """list_purchases 支持 (from_q, to_q, country) 过滤。"""
    rows = [
        {"country_iso": "CHN", "country_name": "中国", "quarter": "2025Q1",
         "tonnes_net": 30.0, "source": "IMF IRFCL", "data_date": date(2025, 3, 31)},
        {"country_iso": "CHN", "country_name": "中国", "quarter": "2026Q2",
         "tonnes_net": 33.0, "source": "IMF IRFCL", "data_date": date(2026, 6, 30)},
        {"country_iso": "POL", "country_name": "波兰", "quarter": "2026Q2",
         "tonnes_net": 51.0, "source": "IMF IRFCL", "data_date": date(2026, 6, 30)},
    ]
    await _seed(db_session, rows)

    out = await _svc(db_session).list_purchases(from_quarter="2026Q1")
    quarters = {it.quarter for it in out.items}
    assert quarters == {"2026Q2"}

    out = await _svc(db_session).list_purchases(country_iso="CHN")
    assert {it.country_iso for it in out.items} == {"CHN"}
    assert len(out.items) == 2

    out = await _svc(db_session).list_purchases(from_quarter="2026Q1", country_iso="CHN")
    assert len(out.items) == 1
    assert out.items[0].quarter == "2026Q2"


async def test_list_purchases_summary_and_top_included(db_session: AsyncSession) -> None:
    """list_purchases 响应同时包含 summary + top_buyers + items 三段。"""
    rows = [
        {"country_iso": "CHN", "country_name": "中国", "quarter": "2026Q2",
         "tonnes_net": 33.0, "source": "IMF IRFCL", "data_date": date(2026, 6, 30)},
        {"country_iso": "POL", "country_name": "波兰", "quarter": "2026Q2",
         "tonnes_net": 51.0, "source": "IMF IRFCL", "data_date": date(2026, 6, 30)},
    ]
    await _seed(db_session, rows)

    out = await _svc(db_session).list_purchases()
    # T12M 算法：当前季度往前推 4 个季度；最新是 2026Q2，窗口 = 2025Q3–2026Q2
    assert out.summary.t12m_window == "2025Q3–2026Q2"
    assert out.summary.current_quarter_total == pytest.approx(84.0)
    assert len(out.top_buyers) == 2
    assert out.top_buyers[0].country_iso == "POL"  # 51 > 33


# 延迟导入 pytest 避免 collect 阶段命名冲突
import pytest  # noqa: E402
