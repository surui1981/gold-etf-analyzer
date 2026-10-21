"""用户报告存档 ORM 模型：HTML 研报上传与元数据登记（V0.111.0）

数据来源：
- 用户从本地上传的单份 HTML 报告（研报 / 周评 / 月报 / 持仓快照等）
- 上传时**只存文件本体 + 一份人工填写的元数据登记表**，不做任何正文抽取

设计要点：
- ``stored_name``（``uuid4().hex + '.html'``）是磁盘上的真实文件名，**唯一**。
  ⚠ **原始文件名只存 ``original_name`` 供展示，绝不参与磁盘路径拼接** ——
  路径拼接 = 目录穿越（``../../etc/cron.d/x``）与覆写既有文件两类漏洞。
  所有拼接处一律用 ``reports_dir / row.stored_name``，且入库前已由
  :func:`app.services.reports.safe_stored_name` 生成白名单字符。
- ``tags`` TEXT 存 JSON 数组（去重 + 字母序），与 ``user_news_favorites.user_tags`` /
  ``scoring_daily_wide.news_basis_tags`` 完全同模式，搜索走 LIKE。
- ``report_date``（报告自身的日期）与 ``created_at``（上传时间）刻意分开 ——
  上个月的报告今天补录是常态，两者混用会让时间线错乱。
- ``size_bytes`` 冗余存储：列表页要显示大小，回读文件会给每次渲染加 IO。

⚠ **文件不落 ``static/``**：那里是 Service Worker ``cache-first`` 区
   （``static/sw.js:248-260``）且被限流豁免（``rate_limit_skip_static=True``，
   ``config.py:145``）—— 上传物进去会被永久回放且不限速。落 ``data/reports/``，
   该目录在 systemd unit 的 ``ReadWritePaths`` 白名单内。

⚠ **文件在 ``static/`` 之外、由独立端点带 CSP 响应头送出**：上传的 HTML 与主站
   同源，一旦裸发就等于把全部 ``/api/v1/*`` 写接口交出去（生产 ``AUTH_ENABLED``
   未设置 = 认证关闭、无 cookie）。``endpoints/reports.py`` 的 ``/content`` 端点
   用 ``Content-Security-Policy: sandbox``（不带 allow-same-origin）把它压进
   **opaque origin**，再 ``connect-src 'none'`` 断掉接口调用 —— 渲染保真度不变。

⚠ 本表**挂 user_id**（与 ``user_news_favorites`` 的 V0.80.0 #159「不挂」相反）：
   收藏是「共享上下文」语义（同一份新闻大家看到同一条），报告是**用户私有资产**，
   语义上等价于 ``ai_chat`` 的对话归属。单用户模式下该列恒为
   ``LEGACY_USER_ID = 1``；多用户启用后仓储层 ``resolve_user_id`` 直接生效。
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Report(Base):
    """用户上传的报告存档记录（V0.111.0 引入）。

    唯一约束：``stored_name``（磁盘文件名），防止 UUID 碰撞覆写既有文件。
    ``title`` **不**唯一 —— 同一份报告改名重传是正常操作。
    """

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
        comment="归属用户；单用户模式下恒为 1（LEGACY_USER_ID）",
    )
    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="报告标题（登记表主字段；默认取原始文件名去扩展名）",
    )
    stored_name: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        comment="磁盘文件名 uuid4().hex + '.html'；**原始文件名不入此列**，杜绝路径穿越",
    )
    original_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="上传时的原始文件名（仅供前端展示，前端须 escapeHtml）",
    )
    size_bytes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="文件字节数（列表页显示用，避免回读文件）",
    )
    report_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        comment="报告自身日期（可与上传日不同；NULL = 用户未填）",
    )
    category: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="其他",
        server_default="其他",
        comment="分类（预置 研报/持仓/复盘/宏观/资金/其他，允许自由输入新分类）",
    )
    tags: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
        server_default="[]",
        comment="标签 JSON 数组（去重 + 字母序，LIKE 模式搜索）",
    )
    summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
        comment="一句话摘要（默认空字符串，非 NULL —— 用户内容占位用 ''）",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="上传时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="元数据改动时刷新",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Report #{self.id} '{self.title[:24]}' {self.size_bytes}B cat={self.category}>"
