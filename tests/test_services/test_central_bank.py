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
        {
            "country_iso": "CHN",
            "country_name": "中国",
            "quarter": "2025Q3",
            "tonnes_net": 30.0,
            "source": "IMF IRFCL",
            "data_date": date(2025, 9, 30),
        },
        {
            "country_iso": "CHN",
            "country_name": "中国",
            "quarter": "2025Q4",
            "tonnes_net": 25.0,
            "source": "IMF IRFCL",
            "data_date": date(2025, 12, 31),
        },
        {
            "country_iso": "CHN",
            "country_name": "中国",
            "quarter": "2026Q1",
            "tonnes_net": 5.0,
            "source": "IMF IRFCL",
            "data_date": date(2026, 3, 31),
        },
        {
            "country_iso": "CHN",
            "country_name": "中国",
            "quarter": "2026Q2",
            "tonnes_net": 33.0,
            "source": "IMF IRFCL",
            "data_date": date(2026, 6, 30),
        },
        # T12M 之外（应被排除）
        {
            "country_iso": "CHN",
            "country_name": "中国",
            "quarter": "2025Q2",
            "tonnes_net": 999.0,
            "source": "IMF IRFCL",
            "data_date": date(2025, 6, 30),
        },
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
        {
            "country_iso": "CHN",
            "country_name": "中国",
            "quarter": "2025Q1",
            "tonnes_net": 30.0,
            "source": "IMF IRFCL",
            "data_date": date(2025, 3, 31),
        },
        {
            "country_iso": "CHN",
            "country_name": "中国",
            "quarter": "2025Q2",
            "tonnes_net": 25.0,
            "source": "IMF IRFCL",
            "data_date": date(2025, 6, 30),
        },
        {
            "country_iso": "POL",
            "country_name": "波兰",
            "quarter": "2025Q1",
            "tonnes_net": 50.0,
            "source": "IMF IRFCL",
            "data_date": date(2025, 3, 31),
        },
        {
            "country_iso": "TUR",
            "country_name": "土耳其",
            "quarter": "2025Q2",
            "tonnes_net": 40.0,
            "source": "IMF IRFCL",
            "data_date": date(2025, 6, 30),
        },
        # 2024 年（应被排除）
        {
            "country_iso": "CHN",
            "country_name": "中国",
            "quarter": "2024Q4",
            "tonnes_net": 999.0,
            "source": "IMF IRFCL",
            "data_date": date(2024, 12, 31),
        },
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
        {
            "country_iso": "CHN",
            "country_name": "中国",
            "quarter": "2025Q1",
            "tonnes_net": 30.0,
            "source": "IMF IRFCL",
            "data_date": date(2025, 3, 31),
        },
        {
            "country_iso": "CHN",
            "country_name": "中国",
            "quarter": "2026Q2",
            "tonnes_net": 33.0,
            "source": "IMF IRFCL",
            "data_date": date(2026, 6, 30),
        },
        {
            "country_iso": "POL",
            "country_name": "波兰",
            "quarter": "2026Q2",
            "tonnes_net": 51.0,
            "source": "IMF IRFCL",
            "data_date": date(2026, 6, 30),
        },
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
        {
            "country_iso": "CHN",
            "country_name": "中国",
            "quarter": "2026Q2",
            "tonnes_net": 33.0,
            "source": "IMF IRFCL",
            "data_date": date(2026, 6, 30),
        },
        {
            "country_iso": "POL",
            "country_name": "波兰",
            "quarter": "2026Q2",
            "tonnes_net": 51.0,
            "source": "IMF IRFCL",
            "data_date": date(2026, 6, 30),
        },
    ]
    await _seed(db_session, rows)

    out = await _svc(db_session).list_purchases()
    # T12M 算法：当前季度往前推 4 个季度；最新是 2026Q2，窗口 = 2025Q3–2026Q2
    assert out.summary.t12m_window == "2025Q3–2026Q2"
    assert out.summary.current_quarter_total == pytest.approx(84.0)
    assert len(out.top_buyers) == 2
    assert out.top_buyers[0].country_iso == "POL"  # 51 > 33


# ──────────────── 全球合计行（WGC_AGGR）不得重复计数（V0.121.4） ────────────────


def _agg_row(quarter: str, tonnes: float) -> dict:
    return {
        "country_iso": "WGC_AGGR",
        "country_name": "全球合计",
        "quarter": quarter,
        "tonnes_net": tonnes,
        "source": "WGC GDT Q3 2026 合计行",
        "data_date": date(2026, 9, 30),
    }


async def test_summary_prefers_aggregate_over_country_sum(db_session: AsyncSession) -> None:
    """⚠️ 核心回归：合计行与各国行**不可相加**。

    实测旧口径（2026Q2）：全表求和 336.7 = 合计 288.9 + 各国 47.8 ⇒ 重复计数。
    现在 current_quarter_total 必须取**合计行**，不是相加。
    """
    rows = [
        _agg_row("2026Q2", 288.9),
        {
            "country_iso": "CHN",
            "country_name": "中国",
            "quarter": "2026Q2",
            "tonnes_net": 40.0,
            "source": "WGC GDT Q2 2026 H1",
            "data_date": date(2026, 6, 30),
        },
        {
            "country_iso": "POL",
            "country_name": "波兰",
            "quarter": "2026Q2",
            "tonnes_net": 7.8,
            "source": "WGC GDT Q2 2026 H1",
            "data_date": date(2026, 6, 30),
        },
    ]
    await _seed(db_session, rows)

    out = await _svc(db_session).summary()
    # 288.9，而不是 288.9 + 40.0 + 7.8 = 336.7
    assert out.current_quarter_total == pytest.approx(288.9)
    # 合计行**不是国家** ⇒ country_count 不含它
    assert out.country_count == 2


async def test_t12m_total_prefers_aggregate(db_session: AsyncSession) -> None:
    """T12M 合计取「合计行之和」，不取「合计 + 各国」。"""
    rows = [
        _agg_row("2025Q4", 209.9),
        _agg_row("2026Q1", 57.7),
        _agg_row("2026Q2", 296.3),
        _agg_row("2026Q3", 321.2),
        {
            "country_iso": "CHN",
            "country_name": "中国",
            "quarter": "2026Q2",
            "tonnes_net": 40.0,
            "source": "WGC GDT Q2 2026 H1",
            "data_date": date(2026, 6, 30),
        },
    ]
    await _seed(db_session, rows)

    out = await _svc(db_session).summary()
    # 209.9 + 57.7 + 296.3 + 321.2 = 885.1（不含 CHN 的 40）
    assert out.t12m_total == pytest.approx(885.1)
    assert out.t12m_window == "2025Q4–2026Q3"
    assert out.current_quarter == "2026Q3"
    assert out.current_quarter_total == pytest.approx(321.2)


async def test_top_buyers_excludes_aggregate_row(db_session: AsyncSession) -> None:
    """合计行不进 Top 排名（它是合计口径，不是「买家」）。"""
    rows = [
        _agg_row("2026Q1", 57.7),
        _agg_row("2026Q2", 296.3),
        {
            "country_iso": "POL",
            "country_name": "波兰",
            "quarter": "2026Q2",
            "tonnes_net": 7.8,
            "source": "WGC GDT Q2 2026 H1",
            "data_date": date(2026, 6, 30),
        },
    ]
    await _seed(db_session, rows)

    top = await _svc(db_session).top_buyers(year=2026, limit=10)
    assert [t.country_iso for t in top] == ["POL"]
    assert top[0].tonnes_net == pytest.approx(7.8)


async def test_summary_falls_back_to_country_sum_without_aggregate(
    db_session: AsyncSession,
) -> None:
    """没有合计行时退回各国之和（口径不同，但好过没有数）。"""
    rows = [
        {
            "country_iso": "CHN",
            "country_name": "中国",
            "quarter": "2026Q2",
            "tonnes_net": 33.0,
            "source": "IMF IRFCL",
            "data_date": date(2026, 6, 30),
        },
        {
            "country_iso": "POL",
            "country_name": "波兰",
            "quarter": "2026Q2",
            "tonnes_net": 51.0,
            "source": "IMF IRFCL",
            "data_date": date(2026, 6, 30),
        },
    ]
    await _seed(db_session, rows)

    out = await _svc(db_session).summary()
    assert out.current_quarter_total == pytest.approx(84.0)
    assert out.country_count == 2


# 延迟导入 pytest 避免 collect 阶段命名冲突
import pytest  # noqa: E402
