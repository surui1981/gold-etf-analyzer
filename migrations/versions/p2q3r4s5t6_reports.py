"""reports 表：用户上传的 HTML 报告存档 + 元数据登记表（V0.111.0）

Revision ID: p2q3r4s5t6
Revises: n1o2p3q4r5
Create Date: 2026-10-21 09:30:00.000000

迁移背景
----------
用户手里攒的研报 / 周评 / 月报只能躺在下载目录。既有 ``/report`` 是**复盘报告**
（由持仓 / 交易数据自动生成，``report.*`` i18n 命名空间），``docs/reports/`` 是
仓库内 git 跟踪的历史分析 markdown —— **两者都不是「我的文档」**，项目里此前
没有任何「用户上传文件」的表或端点（Explore 全仓 grep UploadFile / multipart /
FormData 0 命中）。

V0.111.0 起新增「报告存档」全栈：
- 首页第 8 张场景卡 + 顶 nav 第 9 个顶级场景 → ``/report-archive``
- 上传 HTML（带标题 / 报告日期 / 分类 / 标签 / 摘要登记表）→ 列表检索 → 新标签页查看

迁移策略
--------
- **单表，4 索引**，完全不碰既有表（V0.79.0 #162 纪律）
- **不落 ``static/``**：那里是 SW ``cache-first`` 区且被限流豁免（见
  ``models/reports.py`` 模块 docstring）。文件落 ``data/reports/<uuid4>.html``，
  由独立端点带 CSP 响应头送出
- **文件名两分**：``stored_name``（uuid4().hex + .html，磁盘真名，唯一约束）
  与 ``original_name``（用户原名，仅展示）。**原始文件名绝不参与路径拼接**
- ``tags`` TEXT 存 JSON 数组（去重 + 字母序），与 ``user_news_favorites.user_tags``
  完全同模式；搜索走 LIKE（``LIKE '%"黄金"%'``），千级数据够用
- ``report_date`` 与 ``created_at`` **刻意分开**：上个月的报告今天补录是常态
- **挂 user_id**（FK → users.id）：收藏是「共享上下文」，报告是用户私有资产，
  语义上等价于 ``ai_chat`` 的对话归属。单用户模式下恒为 LEGACY_USER_ID = 1
- 索引：
  - ``(stored_name)`` UNIQUE — UUID 碰撞防护（挡住覆写既有文件）
  - ``(user_id)`` — per-user 列表
  - ``(category)`` — 分类筛选
  - ``(created_at)`` — 倒序时间线
- ``summary`` 默认 ''（非 NULL：用户内容占位用空串而非 NULL）
- **表本体不含任何文件内容** —— 删行与 unlink 由 service 层同事务编排

⚠ ``_table_exists()`` 幂等守卫沿用 ``n1o2p3q4r5``（合并迁移）的写法：
   ``main._migrate_db()`` 在 alembic 失败时回退 ``Base.metadata.create_all``，
   两条路径都跑过时表已存在 —— 无守卫的迁移会在第二次启动时炸
   "table already exists" 并导致整个 app 起不来。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "p2q3r4s5t6"
down_revision: str | Sequence[str] | None = "n1o2p3q4r5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists() -> bool:
    return "reports" in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """建 reports 表 + 4 索引。"""
    if _table_exists():
        return
    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
            comment="归属用户；单用户模式下恒为 1（LEGACY_USER_ID）",
        ),
        sa.Column(
            "title",
            sa.String(length=200),
            nullable=False,
            comment="报告标题（登记表主字段；默认取原始文件名去扩展名）",
        ),
        sa.Column(
            "stored_name",
            sa.String(length=64),
            nullable=False,
            comment="磁盘文件名 uuid4().hex + '.html'；**原始文件名不入此列**，杜绝路径穿越",
        ),
        sa.Column(
            "original_name",
            sa.String(length=200),
            nullable=False,
            comment="上传时的原始文件名（仅供前端展示，前端须 escapeHtml）",
        ),
        sa.Column(
            "size_bytes",
            sa.Integer(),
            nullable=False,
            comment="文件字节数（列表页显示用，避免回读文件）",
        ),
        sa.Column(
            "report_date",
            sa.Date(),
            nullable=True,
            comment="报告自身日期（可与上传日不同；NULL = 用户未填）",
        ),
        sa.Column(
            "category",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'其他'"),
            comment="分类（预置 研报/持仓/复盘/宏观/资金/其他，允许自由输入新分类）",
        ),
        sa.Column(
            "tags",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'[]'"),
            comment="标签 JSON 数组（去重 + 字母序，LIKE 模式搜索）",
        ),
        sa.Column(
            "summary",
            sa.Text(),
            nullable=False,
            server_default=sa.text("''"),
            comment="一句话摘要（默认空字符串，非 NULL —— 用户内容占位用 ''）",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            comment="上传时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            comment="元数据改动时刷新",
        ),
        sa.UniqueConstraint("stored_name", name="uq_reports_stored_name"),
    )
    op.create_index("ix_reports_user_id", "reports", ["user_id"])
    op.create_index("ix_reports_category", "reports", ["category"])
    op.create_index("ix_reports_created_at", "reports", ["created_at"])


def downgrade() -> None:
    """删 reports 表（3 索引显式 drop + UNIQUE 约束随表走）。"""
    if not _table_exists():
        return
    op.drop_index("ix_reports_created_at", table_name="reports")
    op.drop_index("ix_reports_category", table_name="reports")
    op.drop_index("ix_reports_user_id", table_name="reports")
    op.drop_table("reports")
