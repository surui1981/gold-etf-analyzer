"""世界央行黄金购买 业务服务：摘要 + Top 排序 + 明细查询。"""

from app.repositories.central_bank import CentralBankPurchaseRepository
from app.repositories.central_bank_data import COUNTRY_NAMES
from app.schemas.central_bank import (
    CentralBankListOut,
    CentralBankPurchaseOut,
    CentralBankSummaryOut,
    CentralBankTopBuyer,
)


def _resolve_country_name(iso: str, db_name: str | None) -> str:
    """V0.73.0 N+9：country_name 改 Optional；兜底链 DB 字段 → ISO→中文 dict → ISO。

    永不返回 None，避免前端拿到 null 显示 undefined。
    """
    if db_name:
        return db_name
    return COUNTRY_NAMES.get(iso, iso)


class CentralBankService:
    """编排央行购金数据查询与摘要计算。

    设计原则：
    - 简单 CRUD 透传到 Repository（保持仓储纯净）；
    - T12M 计算 + Top 排序在此聚合（业务语义在 Service 层）。
    """

    def __init__(self, repo: CentralBankPurchaseRepository) -> None:
        self._repo = repo

    async def summary(self) -> CentralBankSummaryOut:
        """首页摘要：T12M + 当前季度 + 参与国家数 + 数据截止季。"""
        items = await self._repo.list_all()
        if not items:
            return CentralBankSummaryOut(
                t12m_total=0.0,
                t12m_window="-",
                current_quarter="-",
                current_quarter_total=0.0,
                country_count=0,
                latest_data_quarter="-",
                last_refresh=None,
            )

        # T12M
        t12m = await self._repo.t12m_total()
        t12m_total, t12m_window, latest_q = t12m if t12m else (0.0, "-", items[0].quarter)

        # 当前季度合计（latest_q）
        current_total = sum(float(it.tonnes_net) for it in items if it.quarter == latest_q)

        # 参与国家数（distinct country_iso）
        country_count = len({it.country_iso for it in items})

        # 最后刷新
        last_refresh = await self._repo.latest_refresh()

        return CentralBankSummaryOut(
            t12m_total=round(t12m_total, 1),
            t12m_window=t12m_window,
            current_quarter=latest_q,
            current_quarter_total=round(current_total, 1),
            country_count=country_count,
            latest_data_quarter=latest_q,
            last_refresh=last_refresh,
        )

    async def top_buyers(self, year: int, limit: int = 10) -> list[CentralBankTopBuyer]:
        """某年度 Top N 买家（按当年累计净购金降序）。"""
        items = await self._repo.list_by_range(
            from_quarter=f"{year}Q1",
            to_quarter=f"{year}Q4",
        )
        # 按国家聚合
        country_total: dict[str, tuple[str, float]] = {}  # iso → (name, total)
        for it in items:
            iso, name, tonnes = it.country_iso, it.country_name, float(it.tonnes_net)
            if iso in country_total:
                country_total[iso] = (country_total[iso][0], country_total[iso][1] + tonnes)
            else:
                country_total[iso] = (name, tonnes)

        ranked = sorted(country_total.items(), key=lambda kv: kv[1][1], reverse=True)
        out: list[CentralBankTopBuyer] = []
        for rank, (iso, (name, total)) in enumerate(ranked[:limit], start=1):
            out.append(
                CentralBankTopBuyer(
                    rank=rank,
                    country_iso=iso,
                    # V0.73.0 N+9：兜底链保证永不返回 None
                    country_name=_resolve_country_name(iso, name),
                    tonnes_net=round(total, 1),
                )
            )
        return out

    async def list_purchases(
        self,
        from_quarter: str | None = None,
        to_quarter: str | None = None,
        country_iso: str | None = None,
    ) -> CentralBankListOut:
        """央行购金明细 + 摘要 + Top 10 买家（一次返回，便于前端单次渲染）。"""
        items = await self._repo.list_by_range(from_quarter, to_quarter, country_iso)
        summary = await self.summary()
        # Top 10 买家按 T12M 窗口
        top = await self._top_buyers_t12m(limit=10)

        return CentralBankListOut(
            items=[_to_out(it) for it in items],
            summary=summary,
            top_buyers=top,
        )

    async def _top_buyers_t12m(self, limit: int = 10) -> list[CentralBankTopBuyer]:
        """按 T12M 窗口聚合的 Top 买家。"""
        t12m = await self._repo.t12m_total()
        if t12m is None:
            return []
        _, _window, latest_q = t12m
        # 解析窗口
        from app.repositories.central_bank_data import _previous_quarter

        quarters = [latest_q]
        for _ in range(3):
            quarters.append(_previous_quarter(quarters[-1]))
        quarters.reverse()

        items = await self._repo.list_by_range(
            from_quarter=quarters[0],
            to_quarter=quarters[-1],
        )
        agg: dict[str, tuple[str, float]] = {}
        for it in items:
            iso, name, tonnes = it.country_iso, it.country_name, float(it.tonnes_net)
            if iso in agg:
                agg[iso] = (agg[iso][0], agg[iso][1] + tonnes)
            else:
                agg[iso] = (name, tonnes)

        ranked = sorted(agg.items(), key=lambda kv: kv[1][1], reverse=True)
        return [
            CentralBankTopBuyer(
                rank=i + 1,
                country_iso=iso,
                # V0.73.0 N+9：兜底链保证永不返回 None
                country_name=_resolve_country_name(iso, name),
                tonnes_net=round(total, 1),
            )
            for i, (iso, (name, total)) in enumerate(ranked[:limit])
        ]


def _to_out(it) -> CentralBankPurchaseOut:
    """ORM → Pydantic Out。

    V0.73.0 N+9：country_name 改 Optional；前端 ISO→字典渲染优先，
    此处用兜底链（DB 字段 → COUNTRY_NAMES[iso] → iso）保证永不返回 None。
    """
    return CentralBankPurchaseOut(
        country_iso=it.country_iso,
        country_name=_resolve_country_name(it.country_iso, it.country_name),
        quarter=it.quarter,
        tonnes_net=float(it.tonnes_net),
        source=it.source,
        data_date=it.data_date,
    )
