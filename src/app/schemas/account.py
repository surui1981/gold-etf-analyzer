"""账本 Schema：账本清单 / 新建 / 修改 / 归档（P1 #6 单用户多账本）。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AccountCreate(BaseModel):
    """新建账本请求。"""

    name: str = Field(..., min_length=1, max_length=64, description="账本名称，如 主账户")
    note: str = Field("", max_length=255, description="备注（用途说明）")
    is_default: bool = Field(False, description="是否设为默认账本（会取消其他账本的默认标记）")

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("账本名称不能为空")
        return name

    @field_validator("note")
    @classmethod
    def _strip_note(cls, value: str) -> str:
        return value.strip()


class AccountUpdate(BaseModel):
    """修改账本请求（字段可选，仅传需要变更的项）。"""

    name: str | None = Field(None, min_length=1, max_length=64, description="新名称")
    note: str | None = Field(None, max_length=255, description="新备注")
    sort_order: int | None = Field(None, ge=0, le=9999, description="展示排序（升序）")
    is_default: bool | None = Field(
        None, description="设为默认账本（true 时取消其他账本的默认标记）"
    )

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        name = value.strip()
        if not name:
            raise ValueError("账本名称不能为空")
        return name

    @field_validator("note")
    @classmethod
    def _strip_note(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class AccountStatsOut(BaseModel):
    """账本维度的持仓/流水统计。"""

    position_count: int = Field(0, description="持仓总数（含已平仓）")
    open_count: int = Field(0, description="未平仓持仓数")
    trade_count: int = Field(0, description="交易流水笔数")
    last_traded_at: datetime | None = Field(None, description="最近成交时间")


class AccountOut(BaseModel):
    """账本输出（含统计）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    note: str = ""
    is_default: bool = False
    sort_order: int = 0
    archived_at: datetime | None = None
    created_at: datetime | None = None
    stats: AccountStatsOut = Field(default_factory=AccountStatsOut)


class AccountListOut(BaseModel):
    """账本清单输出。"""

    items: list[AccountOut] = Field(default_factory=list, description="账本列表")
    total: int = Field(0, description="账本数量")
    current_account_id: int = Field(0, description="默认账本 ID（前端未选中账本时的落点）")


class AccountArchiveOut(BaseModel):
    """归档 / 恢复结果。"""

    id: int
    archived: bool = Field(..., description="true=已归档；false=已恢复")
    archived_at: datetime | None = None
