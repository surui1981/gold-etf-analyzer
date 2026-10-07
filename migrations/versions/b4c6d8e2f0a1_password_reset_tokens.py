"""password_reset_tokens 表（V0.75.3 · 找回密码）

Revision ID: b4c6d8e2f0a1
Revises: a3f2c1d5e6f7
Create Date: 2026-10-08 06:20:00.000000

新建表（不是给已有表加列）
------------------------
密码重置的一次性令牌。24h TTL，用过即作废。

⚠⚠ **只存``token_hash``（sha256 十六进制），不存明文** —— 本迁移的核心设计。
token 明文只在两个时刻存在：刚生成要写邮件的那一瞬、用户从邮件粘回来的那一瞬。
若库里存明文，则**一次库泄漏 = 所有在途账号可被永久重置**；
存摘要后泄漏拿到的是不可逆结果，攻击者无法据此重置任何账号。

⚠ 与 ``sessions`` 表的设计差异（勿照抄）：会话 id 是**不透明随机串**
（泄漏一个会话只能冒充该会话本身，无需哈希）；重置 token 是**高价值凭据**
（拿到即可永久改密码）⇒ 必须哈希。

可重复执行
----------
新库路径由 ``create_all`` 直接建表（见模型声明）⇒ 本迁移对��库是 no-op
（``_table_exists`` 探测后跳过）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b4c6d8e2f0a1"
down_revision: Union[str, Sequence[str], None] = "a3f2c1d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists() -> bool:
    """表是否已存在（新库由 ``create_all`` 建好⇒ 跳过）。"""
    return "password_reset_tokens" in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """Upgrade schema."""
    if _table_exists():
        return
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False, comment="归属用户 users.id"),
        #⚠ sha256 摘要（64 字符十六进制），非明文
        sa.Column(
            "token_hash",
            sa.String(length=64),
            nullable=False,
            comment="token 的 sha256 十六进制摘要（**非明文**）",
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, comment="过期时间（朴素 UTC）"),
        sa.Column(
            "used_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="非空 = 已使用（一次性，不可重放）",
        ),
        # ⚠ 仅供审计（发现暴力枚举邮箱的迹象），不作为鉴权依据
        sa.Column("request_ip", sa.String(length=64), nullable=True, comment="申请时客户端 IP（审计用）"),
        sa.Column(
            "user_agent", sa.String(length=256), nullable=True, comment="申请时设备标识（审计用）"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="申请时间",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_password_reset_tokens_token_hash"),
        "password_reset_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        op.f("ix_password_reset_tokens_user_id"), "password_reset_tokens", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_password_reset_tokens_expires_at"),
        "password_reset_tokens",
        ["expires_at"],
        unique=False,
    )
    # 「查某用户是否有过在途 token」走该复合索引
    op.create_index(
        "ix_password_reset_tokens_user_used",
        "password_reset_tokens",
        ["user_id", "used_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema.

    ⚠ 本表**只存摘要、不含任何凭据**，删除它**不会泄漏或丢失用户数据** ——
    唯一后果是所有在途的重置链接失效（已发出的邮件里的 token 全部作废）。
    """
    if _table_exists():
        op.drop_table("password_reset_tokens")