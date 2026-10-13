"""占位迁移（V0.92.0 部署修复）

背景
----
2026-10-14 V0.92.0 部署期间发现：生产 DB 的 ``alembic_version`` 指向
``c4d5e6f7a8b9``，但代码库中**无此 revision 的迁移文件**。可能是早期
手动 ``alembic stamp`` 或 DB 备份恢复导致 alembic 链路失同步。

**实情**：生产 DB 的 ``scoring_daily_wide`` 表（V0.92.0 引入，26 列）
已**实际存在**，且 ``positions.grams_held / password_reset_tokens /
push_subscriptions / telemetry_events`` 等所有下游表都齐备。
所以 schema 状态本身**已经过** V0.92.0，只是 alembic 链路断裂。

解决
----
本文件**占位** revision ``c4d5e6f7a8b9``，down_revision 指向实际
前一版本 ``b7c5d9e3f1a2``（telemetry_events，V0.92.0 之前最后一个
已知 revision），upgrade / downgrade 都是 ``pass`` —— 因为 schema
实际状态不需要再改。

后续 ``alembic upgrade head`` 就能从 c4d5e6f7a8b9 顺着
``i5d6e7f8a9b0``（V0.92.0 真迁移）走通。
"""

from __future__ import annotations

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, None] = "b4c6d8e2f0a1"  # password_reset_tokens
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """占位迁移：实际 schema 已在生产 DB 落齐，upgrade 不做任何事。"""
    pass


def downgrade() -> None:
    """占位迁移：downgrade 不做任何事。"""
    pass
