"""账本仓储：封装 Account 的数据访问（P1 #6 单用户多账本）。"""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import DEFAULT_ACCOUNT_NAME, Account


class AccountRepository:
    """数据访问层：账本 CRUD / 默认账本保障 / 归档恢复。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self, user_id: int = 1, *, include_archived: bool = False) -> list[Account]:
        """账本列表（默认账本置顶，其余按 sort_order、id 升序）。

        Args:
            user_id: 用户 ID（当前恒为 1）
            include_archived: 是否包含已归档账本（交易历史查询页需要）
        """
        stmt = select(Account).where(Account.user_id == user_id)
        if not include_archived:
            stmt = stmt.where(Account.archived_at.is_(None))
        stmt = stmt.order_by(Account.is_default.desc(), Account.sort_order, Account.id)
        return list((await self._session.execute(stmt)).scalars().all())

    async def get(self, account_id: int) -> Account | None:
        """按 ID 查询账本（含已归档，供恢复/校验使用）。"""
        stmt = select(Account).where(Account.id == account_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_default(self, user_id: int = 1) -> Account | None:
        """默认账本（first is_default=1 and 未归档）。"""
        stmt = (
            select(Account)
            .where(
                Account.user_id == user_id,
                Account.is_default.is_(True),
                Account.archived_at.is_(None),
            )
            .order_by(Account.id)
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def get_by_name(
        self, name: str, user_id: int = 1, *, include_archived: bool = False
    ) -> Account | None:
        """按名称查询（重名校验 / 「沿用」场景）。"""
        stmt = select(Account).where(Account.user_id == user_id, Account.name == name)
        if not include_archived:
            stmt = stmt.where(Account.archived_at.is_(None))
        return (await self._session.execute(stmt)).scalars().first()

    async def create(
        self,
        *,
        name: str,
        note: str = "",
        user_id: int = 1,
        is_default: bool = False,
        sort_order: int | None = None,
        account_id: int | None = None,
    ) -> Account:
        """新建账本并提交。

        Args:
            name: 账本名称
            note: 备注
            user_id: 用户 ID
            is_default: 是否设为默认账本（会先清除其他账本的默认标记）
            sort_order: 展示排序；None 时取「现有最大 + 10」，保证新账本排在末尾
            account_id: 显式指定 ID（仅用于 seed id=1 的默认账本，承接历史数据）
        """
        if is_default:
            await self.clear_default(user_id)

        if sort_order is None:
            max_sort = (
                await self._session.execute(
                    select(func.max(Account.sort_order)).where(Account.user_id == user_id)
                )
            ).scalar()
            sort_order = (max_sort or 0) + 10

        kwargs: dict[str, object] = {
            "user_id": user_id,
            "name": name,
            "note": note,
            "is_default": is_default,
            "sort_order": sort_order,
        }
        if account_id is not None:
            kwargs["id"] = account_id

        account = Account(**kwargs)  # type: ignore[arg-type]
        self._session.add(account)
        await self._session.commit()
        await self._session.refresh(account)
        return account

    async def clear_default(self, user_id: int = 1) -> None:
        """清除该用户所有账本的默认标记（幂等，不提交）。"""
        for account in await self.list(user_id, include_archived=True):
            if account.is_default:
                account.is_default = False
        await self._session.flush()

    async def save(self, account: Account) -> Account:
        """保存账本变更（重命名 / 备注 / 排序 / 归档）并提交。"""
        await self._session.commit()
        await self._session.refresh(account)
        return account

    async def ensure_default(self, user_id: int = 1) -> Account:
        """保障默认账本存在（启动时调用，幂等）。

        三种情况：
        1. 已有默认账本 → 直接返回；
        2. 有账本但都未标记默认 → 把第一个设为默认；
        3. 完全没有账本 → 建立 id=1 的「默认账户」。
           显式指定 id=1 是为了承接老库升级路径：``positions.account_id`` 默认值
           为 1，若此时 accounts 由空表自增建出 id=1 也可，但显式更稳妥。
        """
        default = await self.get_default(user_id)
        if default is not None:
            return default

        accounts = await self.list(user_id, include_archived=True)
        if accounts:
            accounts[0].is_default = True
            return await self.save(accounts[0])

        existing = await self.get(1)
        if existing is not None:
            existing.is_default = True
            existing.archived_at = None
            return await self.save(existing)

        return await self.create(
            name=DEFAULT_ACCOUNT_NAME,
            note="系统默认账本（承接未指定账本的持仓与流水）",
            user_id=user_id,
            is_default=True,
            sort_order=0,
            account_id=1,
        )


def utcnow() -> datetime:
    """当前 UTC 时间（归档时间戳用）。"""
    return datetime.now(timezone.utc)
