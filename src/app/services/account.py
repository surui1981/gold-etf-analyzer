"""账本服务：单用户多账本的解析、增删改与统计（P1 #6）。

关键约定
--------
- **默认账本**：所有「未指定账本」的请求都落到默认账本（``is_default=True``），
  保证既有前端逻辑与历史数据平滑迁移；
- **归档而非删除**：归档账本保留全部持仓与流水（交易历史页可显式查询），
  但不参与默认视图；默认账本与仍有未平仓持仓的账本不允许归档；
- **至少一个默认账本**：启动时 :meth:`AccountService.ensure_default` 兜底，
  且归档默认账本被拒绝。
"""

from app.models.account import Account
from app.repositories.account import AccountRepository, utcnow
from app.repositories.position import PositionRepository
from app.schemas.account import (
    AccountArchiveOut,
    AccountCreate,
    AccountListOut,
    AccountOut,
    AccountStatsOut,
    AccountUpdate,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


class AccountService:
    """账本生命周期管理。"""

    def __init__(self, repo: AccountRepository, positions: PositionRepository) -> None:
        self._repo = repo
        self._positions = positions

    # ───────────────────────── 解析 ─────────────────────────
    async def resolve(self, account_id: int | None) -> int:
        """解析请求账本 ID：None → 默认账本；显式指定则校验存在性。

        Args:
            account_id: 请求中的账本 ID（可为 None）

        Returns:
            可用的账本 ID

        Raises:
            ValueError: 指定账本不存在
        """
        if account_id is None:
            return (await self.ensure_default()).id
        account = await self._repo.get(account_id)
        if account is None:
            raise ValueError(f"账本不存在：{account_id}")
        return account.id

    async def ensure_default(self) -> Account:
        """保障默认账本存在（启动时 / 首次请求时兜底，幂等）。"""
        return await self._repo.ensure_default()

    # ───────────────────────── 查询 ─────────────────────────
    async def list(self, *, include_archived: bool = False) -> AccountListOut:
        """账本清单（含每个账本的持仓 / 流水统计）。

        先保障默认账本存在再查询：账本清单是前端的入口，返回空列表会让
        切换器与账本管理面板无账本可选；自愈一次比让用户面对空态更合理。
        """
        await self.ensure_default()
        accounts = await self._repo.list(include_archived=include_archived)
        stats = await self._positions.stats_by_account()
        default = await self._repo.get_default()

        items = []
        for account in accounts:
            out = AccountOut.model_validate(account)
            st = stats.get(account.id)
            out.stats = (
                AccountStatsOut(
                    position_count=st.position_count,
                    open_count=st.open_count,
                    trade_count=st.trade_count,
                    last_traded_at=st.last_traded_at,
                )
                if st
                else AccountStatsOut()
            )
            items.append(out)
        return AccountListOut(
            items=items,
            total=len(items),
            current_account_id=default.id if default else (items[0].id if items else 0),
        )

    async def get(self, account_id: int) -> AccountOut:
        """单个账本详情（含统计）。

        Raises:
            ValueError: 账本不存在
        """
        account = await self._repo.get(account_id)
        if account is None:
            raise ValueError(f"账本不存在：{account_id}")
        stats = await self._positions.stats_by_account()
        out = AccountOut.model_validate(account)
        st = stats.get(account.id)
        if st:
            out.stats = AccountStatsOut(
                position_count=st.position_count,
                open_count=st.open_count,
                trade_count=st.trade_count,
                last_traded_at=st.last_traded_at,
            )
        return out

    # ───────────────────────── 增改 ─────────────────────────
    async def create(self, request: AccountCreate) -> AccountOut:
        """新建账本。

        先保障默认账本存在：默认账本固定为 id=1，是所有「未指定账本」请求与
        ``positions.account_id`` 默认值的落点；若让新建账本先占用了 id=1，
        老库升级路径的历史持仓就会被错误归属到该账本。

        Raises:
            ValueError: 已存在同名（未归档）账本
        """
        await self.ensure_default()
        if await self._repo.get_by_name(request.name) is not None:
            raise ValueError(f"同名账本已存在：{request.name}")
        account = await self._repo.create(
            name=request.name, note=request.note, is_default=request.is_default
        )
        logger.info("账本已创建: id=%s name=%s", account.id, account.name)
        return await self.get(account.id)

    async def update(self, account_id: int, request: AccountUpdate) -> AccountOut:
        """修改账本（名称 / 备注 / 排序 / 设为默认）。

        Raises:
            ValueError: 账本不存在，或改名后与其它未归档账本重名
        """
        account = await self._repo.get(account_id)
        if account is None:
            raise ValueError(f"账本不存在：{account_id}")

        if request.name is not None and request.name != account.name:
            conflict = await self._repo.get_by_name(request.name)
            if conflict is not None and conflict.id != account.id:
                raise ValueError(f"同名账本已存在：{request.name}")
            account.name = request.name

        if request.note is not None:
            account.note = request.note
        if request.sort_order is not None:
            account.sort_order = request.sort_order
        if request.is_default is True:
            await self._repo.clear_default()
            account.is_default = True
        elif request.is_default is False and account.is_default:
            raise ValueError("至少需保留一个默认账本，请先把其它账本设为默认")

        await self._repo.save(account)
        logger.info("账本已更新: id=%s", account_id)
        return await self.get(account_id)

    # ───────────────────────── 归档 / 恢复 ─────────────────────────
    async def archive(self, account_id: int) -> AccountArchiveOut:
        """归档账本（保留数据，退出默认视图）。

        Raises:
            ValueError: 账本不存在 / 默认账本不可归档 / 仍有未平仓持仓
        """
        account = await self._repo.get(account_id)
        if account is None:
            raise ValueError(f"账本不存在：{account_id}")
        if account.is_default:
            raise ValueError("默认账本不可归档，请先把其它账本设为默认")

        stats = (await self._positions.stats_by_account()).get(account_id)
        if stats and stats.open_count > 0:
            raise ValueError(
                f"该账本仍有 {stats.open_count} 笔未平仓持仓，请先平仓或转移后再归档"
            )

        account.archived_at = utcnow()
        await self._repo.save(account)
        logger.info("账本已归档: id=%s", account_id)
        return AccountArchiveOut(
            id=account.id, archived=True, archived_at=account.archived_at
        )

    async def restore(self, account_id: int) -> AccountArchiveOut:
        """恢复已归档账本。

        Raises:
            ValueError: 账本不存在 / 未归档 / 与在用账本重名
        """
        account = await self._repo.get(account_id)
        if account is None:
            raise ValueError(f"账本不存在：{account_id}")
        if account.archived_at is None:
            raise ValueError("该账本未归档，无需恢复")

        conflict = await self._repo.get_by_name(account.name)
        if conflict is not None and conflict.id != account.id:
            raise ValueError(
                f"存在同名在用账本「{account.name}」，请先修改本账本名称再恢复"
            )

        account.archived_at = None
        await self._repo.save(account)
        logger.info("账本已恢复: id=%s", account_id)
        return AccountArchiveOut(id=account.id, archived=False, archived_at=None)
