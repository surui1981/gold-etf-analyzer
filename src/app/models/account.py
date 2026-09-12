"""账本 ORM 模型：单用户多账本（P1 #6）。

设计要点
--------
- **单用户多账本**：``user_id`` 沿用既有预留字段（当前恒为 1），账本之间用 ``id`` 隔离；
- **默认账本**：``is_default=True`` 的账本承接「未指定账本」的请求与历史数据
  （V0.62.0 迁移把既有持仓全部归入 id=1 的「默认账户」）；
- **归档而非删除**：``archived_at`` 非空表示已归档，账本与其历史流水仍可查询
  （交易历史页可显式筛选），但不参与默认视图，避免误删丢账；
- **不设 (user_id, name) 唯一约束**：SQLite 无法表达「仅未归档唯一」的部分索引约束，
  重名检查放在服务层（归档账本不占用名称）。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

DEFAULT_ACCOUNT_NAME = "默认账户"


class Account(Base):
    """交易账本：持仓与交易流水的归属容器。"""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, default=1, index=True, comment="预留多用户，当前单用户=1"
    )

    name: Mapped[str] = mapped_column(String(64), comment="账本名称，如 主账户 / 家人账户")
    note: Mapped[str] = mapped_column(String(255), default="", comment="备注（用途说明）")

    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否为默认账本（承接未指定账本的请求）"
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, comment="展示排序（升序）")

    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="归档时间戳；非空表示已归档（可恢复）"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:  # pragma: no cover
        flag = "默认" if self.is_default else ("已归档" if self.archived_at else "启用")
        return f"<Account {self.id} {self.name} ({flag})>"
