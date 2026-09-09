"""央行黄金购买 REST 端点。"""

from fastapi import APIRouter, Depends, Query

from app.dependencies import get_central_bank_service
from app.schemas.central_bank import (
    CentralBankListOut,
    CentralBankSummaryOut,
    CentralBankTopBuyer,
)
from app.services.central_bank import CentralBankService

router = APIRouter(prefix="/central-bank", tags=["central-bank"])


@router.get(
    "/purchases",
    response_model=CentralBankListOut,
    summary="央行购金明细 + 摘要 + Top 10（T12M）",
)
async def list_purchases(
    from_q: str | None = Query(
        None, pattern=r"^\d{4}Q[1-4]$", description="起始季度（含），如 2025Q1"
    ),
    to_q: str | None = Query(
        None, pattern=r"^\d{4}Q[1-4]$", description="结束季度（含），如 2026Q2"
    ),
    country: str | None = Query(
        None, min_length=3, max_length=3, description="ISO 3 字母代码筛选，如 CHN"
    ),
    service: CentralBankService = Depends(get_central_bank_service),
) -> CentralBankListOut:
    """按 (季度范围, 国家) 过滤的央行购金明细；响应同时包含全局摘要与 Top 10 买家。

    - 不带任何参数时返回全量历史；
    - ``from_q`` / ``to_q`` 字典序比较（YYYYQn），所以 "2025Q1" ≤ "2025Q2"；
    - ``country`` 大小写敏感（库内统一大写，如 CHN/POL/UZB）。
    """
    return await service.list_purchases(
        from_quarter=from_q,
        to_quarter=to_q,
        country_iso=country.upper() if country else None,
    )


@router.get(
    "/top-buyers",
    response_model=list[CentralBankTopBuyer],
    summary="某年度 Top N 买家（按当年累计净购金降序）",
)
async def top_buyers(
    year: int = Query(..., ge=2020, le=2030, description="年份"),
    limit: int = Query(10, ge=1, le=20, description="Top N 上限"),
    service: CentralBankService = Depends(get_central_bank_service),
) -> list[CentralBankTopBuyer]:
    """某年度 Top N 买家：当年 4 季度累计净购金降序。"""
    return await service.top_buyers(year=year, limit=limit)


@router.get(
    "/summary",
    response_model=CentralBankSummaryOut,
    summary="全局摘要（T12M + 最新季度 + 参与国家数）",
)
async def summary(
    service: CentralBankService = Depends(get_central_bank_service),
) -> CentralBankSummaryOut:
    """轻量摘要：单独端点供 trend 页宏观因子快速取值，避免拉全量明细。"""
    return await service.summary()
