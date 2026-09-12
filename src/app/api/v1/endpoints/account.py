"""账本端点：清单 / 新建 / 修改 / 归档 / 恢复（P1 #6 单用户多账本）。"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_account_service
from app.schemas.account import (
    AccountArchiveOut,
    AccountCreate,
    AccountListOut,
    AccountOut,
    AccountUpdate,
)
from app.services.account import AccountService

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("", response_model=AccountListOut, summary="账本清单（含持仓/流水统计）")
async def list_accounts(
    include_archived: bool = Query(False, description="是否包含已归档账本"),
    service: AccountService = Depends(get_account_service),
) -> AccountListOut:
    """列出全部账本，按「默认账本置顶 → 排序值 → ID」排序。

    每个账本附带持仓数 / 未平仓数 / 流水笔数 / 最近成交时间，
    供前端账本切换器与账本管理面板直接展示。
    """
    return await service.list(include_archived=include_archived)


@router.post("", response_model=AccountOut, status_code=201, summary="新建账本")
async def create_account(
    request: AccountCreate,
    service: AccountService = Depends(get_account_service),
) -> AccountOut:
    """新建账本；名称与在用账本重复时返回 400。"""
    try:
        return await service.create(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{account_id}", response_model=AccountOut, summary="账本详情")
async def get_account(
    account_id: int,
    service: AccountService = Depends(get_account_service),
) -> AccountOut:
    """单个账本详情（含统计）。"""
    try:
        return await service.get(account_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{account_id}", response_model=AccountOut, summary="修改账本")
async def update_account(
    account_id: int,
    request: AccountUpdate,
    service: AccountService = Depends(get_account_service),
) -> AccountOut:
    """重命名 / 改备注 / 调排序 / 设为默认账本。"""
    try:
        return await service.update(account_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{account_id}/archive", response_model=AccountArchiveOut, summary="归档账本")
async def archive_account(
    account_id: int,
    service: AccountService = Depends(get_account_service),
) -> AccountArchiveOut:
    """归档账本：数据保留但不参与默认视图。

    默认账本、以及仍有未平仓持仓的账本不允许归档（返回 400 并说明原因）。
    """
    try:
        return await service.archive(account_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{account_id}/restore", response_model=AccountArchiveOut, summary="恢复账本")
async def restore_account(
    account_id: int,
    service: AccountService = Depends(get_account_service),
) -> AccountArchiveOut:
    """恢复已归档账本；与在用账本重名时返回 400。"""
    try:
        return await service.restore(account_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
