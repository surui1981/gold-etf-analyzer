"""报告存档服务：HTML 上传校验 + 磁盘读写 + 元数据 CRUD（V0.111.0）

职责边界
--------
- **service 层是唯一知道「文件存在」的地方**：校验、写盘、unlink、拼 ``FileResponse``。
  仓储层（``repositories/reports.py``）纯 CRUD，不碰文件系统。
- 落盘目录 ``data/reports/`` —— 该目录在 systemd unit 的 ``ReadWritePaths``
  白名单内（``deploy/systemd/gold-etf-analyzer.service``）。换任何别处在生产会
  ``Read-only file system``（``ProtectHome=read-only``），而测试照过。

⚠⚠ 上传的 HTML 与主站同源，这是本模块最需要小心的设计点
--------------------------------------------------------------------------
生产 ``.env.prod`` **没有** ``AUTH_ENABLED`` ⇒ 认证关闭、不签发 cookie、
``user_id`` 恒为 ``LEGACY_USER_ID=1``、连 ``ADMIN_TOKEN`` 校验都被
``middleware/admin_auth.py:9-10`` 跳过。也就是说：一份裸发的同源 HTML 里的
JS 能直接调**全部** ``/api/v1/*`` 写端点 —— 改 V0.110.0 的评估权重、删收藏、
改告警规则，等于「以你的身份操作这个系统」。

应对：``/content`` 端点给每个响应打 :data:`CONTENT_SECURITY_POLICY`：

    sandbox allow-scripts allow-popups
    connect-src 'none'; form-action 'none'
    base-uri 'none'; object-src 'none'; frame-src 'none'

``sandbox``（**不带** ``allow-same-origin``）把文档压进 **opaque origin**：
读不到 localStorage / cookie，够不到 ``window.parent``。``connect-src 'none'``
再封死 fetch / XHR / sendBeacon / WebSocket ⇒ **调不动任何接口**。
同时**刻意不给** ``default-src`` —— 那样会连带禁掉外部 CSS / 字体 / 图片，
把报告渲染打残。脚本与样式照常加载，**渲染保真度不受影响**。
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status

from app.config import PROJECT_ROOT
from app.repositories.reports import ReportRepository
from app.schemas.reports import (
    ReportCategoriesOut,
    ReportListOut,
    ReportOut,
    ReportStatsOut,
    ReportUpdateIn,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ────────────── 常量 ──────────────

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
"""单文件上限 20MB。

必须与 nginx ``client_max_body_size`` 对齐 —— nginx 默认 **1MB**，
不显式放开的话超过 1MB 的请求在到达本应用之前就被 413 挡掉，
用户看到的是「上传失败」而应用日志里什么都没有。
"""

ALLOWED_SUFFIXES = {".html", ".htm"}

DEFAULT_CATEGORY = "其他"
PREDEFINED_CATEGORIES = ["研报", "持仓", "复盘", "宏观", "资金", DEFAULT_CATEGORY]

CHUNK_BYTES = 1024 * 1024
"""流式读取块大小。**不整体读进内存** —— 20MB 上限若先 ``await file.read()``
再判长度，一个伪装成 .html 的 500MB 文件已经吃满内存了。"""

_SAFE_FILENAME_RE = re.compile(r"[^\w一-鿿.\- ]+", re.UNICODE)

CONTENT_SECURITY_POLICY = (
    "sandbox allow-scripts allow-popups; "
    "connect-src 'none'; "
    "form-action 'none'; "
    "base-uri 'none'; "
    "object-src 'none'; "
    "frame-src 'none'"
)
"""上传 HTML 的响应 CSP。语义见模块 docstring。

⚠ ``sandbox`` 是**逐响应**生效的，与应用其它页面（无 CSP）互不影响；
   刻意只打在这一个端点上，不做全局中间件 —— 全局 CSP 要兼顾
   ``marked.min.js`` + 大量内联脚本的现存页面，风险远大于收益。
"""


def reports_dir() -> Path:
    """上传目录 ``data/reports/``（不存在则建）。

    参照 ``repositories/db.py:13-16`` 建库目录的惯例：导入期建目录会让
    单元测试污染真实 data/，所以延到真正写入时才 mkdir。

    ⚠ 取 ``app.config.PROJECT_ROOT``（模块级常量）而不是从 ``database_url``
    反推 —— 后者会让测试把上传物写进 ``tests/`` 目录。测试改用环境变量
    ``REPORTS_DIR`` 重定向，见下。
    """
    override = os.environ.get("REPORTS_DIR")
    d = Path(override) if override else PROJECT_ROOT / "data" / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_stored_name() -> str:
    """生成磁盘文件名 ``<uuid4>.hex.html``。

    ⚠ **绝不用原始文件名拼路径** —— ``../../.ssh/authorized_keys``、超长名、
    Windows 保留名、Unicode 归一化碰撞全都是真实攻击面。UUID 一次性绕开全部。
    """
    return f"{uuid.uuid4().hex}.html"


def sanitize_original_name(raw: str | None) -> str:
    """把用户上传的原始文件名清洗成「可安全展示」的形式。

    只用于 ``original_name`` 列与前端展示（前端仍须 escapeHtml）。清洗的是
    控制字符 / 路径分隔符 / 超长，不保留目录结构 —— 上传时选了
    ``/home/me/秘密.html`` 就只留 ``秘密.html``。
    """
    name = (raw or "").replace("\\", "/").split("/")[-1].strip()
    name = _SAFE_FILENAME_RE.sub("_", name)
    name = name.strip(". ")
    if not name:
        name = "report.html"
    return name[:200]


def default_title_from_filename(original_name: str) -> str:
    """标题缺省值：原始文件名去扩展名。"""
    stem = original_name.rsplit("/", 1)[-1]
    for suf in (".html", ".htm"):
        if stem.lower().endswith(suf):
            stem = stem[: -len(suf)]
            break
    return (stem.strip() or "未命名报告")[:200]


def normalize_tags(raw: Any) -> list[str]:
    """标签规范化：去空白 / 去重 / 字母序，上限 20 个 × 32 字符。"""
    if raw is None:
        return []
    if isinstance(raw, str):
        # 兼容前端传逗号分隔字符串
        parts = re.split(r"[,，]", raw)
    elif isinstance(raw, (list, tuple)):
        parts = list(raw)
    else:
        return []
    out: set[str] = set()
    for p in parts:
        s = str(p).strip()[:32]
        if s:
            out.add(s)
        if len(out) >= 20:
            break
    return sorted(out)


class ReportService:
    """报告存档服务（V0.111.0）。"""

    def __init__(self, repo: ReportRepository) -> None:
        self._repo = repo

    # ────────────── 上传 ──────────────

    async def upload(
        self,
        file: UploadFile,
        *,
        user_id: int | None = None,
        title: str | None = None,
        report_date: date | None = None,
        category: str | None = None,
        tags: Any = None,
        summary: str | None = None,
    ) -> ReportOut:
        """校验 → 落盘 → 入库。

        Raises:
            HTTPException 422：任一校验不通过（扩展名 / 大小 / HTML 头 / 空文件）
        """
        original_name = sanitize_original_name(file.filename)
        if Path(original_name).suffix.lower() not in ALLOWED_SUFFIXES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"只接受 HTML 报告（.html / .htm），收到 {Path(original_name).suffix or '（无扩展名）'}",
            )

        content, size = await self._read_capped(file)
        if size == 0:
            raise HTTPException(422, "文件为空")
        # 去 BOM + 首尾空白后必须以 '<' 开头：挡掉把 .exe / .zip 改名成 .html
        head = content[:1024].lstrip(b"\xef\xbb\xbf").lstrip()
        if not head.startswith(b"<"):
            raise HTTPException(422, "文件内容不像 HTML（首字节不是 '<'），请确认选对了文件")

        stored_name = safe_stored_name()
        (reports_dir() / stored_name).write_bytes(content)

        try:
            row = await self._repo.add(
                {
                    "title": (title or "").strip()[:200]
                    or default_title_from_filename(original_name),
                    "stored_name": stored_name,
                    "original_name": original_name,
                    "size_bytes": size,
                    "report_date": report_date,
                    "category": (category or "").strip()[:32] or DEFAULT_CATEGORY,
                    "tags": json.dumps(normalize_tags(tags), ensure_ascii=False),
                    "summary": (summary or "").strip()[:2000],
                },
                user_id=user_id,
            )
        except Exception:
            # 入库失败必须回收已落盘的孤儿文件，否则删表后磁盘残留且无人认领
            (reports_dir() / stored_name).unlink(missing_ok=True)
            raise
        logger.info(
            "报告存档入库 #%s %s (%d bytes, cat=%s)",
            row.id,
            original_name,
            size,
            row.category,
        )
        return self._to_out(row)

    async def _read_capped(self, file: UploadFile) -> tuple[bytes, int]:
        """分块读取，累计超 ``MAX_UPLOAD_BYTES`` 立即中止（不整体读进内存）。"""
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = await file.read(CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    422,
                    f"文件超过 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB 上限",
                )
            chunks.append(chunk)
        return b"".join(chunks), total

    # ────────────── 元数据 CRUD ──────────────

    async def list_reports(
        self,
        *,
        user_id: int | None = None,
        q: str | None = None,
        category: str | None = None,
        tag: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ReportListOut:
        rows = await self._repo.list_items(
            user_id=user_id, q=q, category=category, tag=tag, limit=limit, offset=offset
        )
        total = await self._repo.count_items(user_id=user_id, q=q, category=category, tag=tag)
        return ReportListOut(
            items=[self._to_out(r) for r in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get(self, report_id: int, *, user_id: int | None = None) -> ReportOut:
        row = await self._repo.get(report_id, user_id=user_id)
        if row is None:
            raise HTTPException(404, f"报告 id={report_id} 不存在")
        return self._to_out(row)

    async def update(
        self, report_id: int, payload: ReportUpdateIn, *, user_id: int | None = None
    ) -> ReportOut:
        row = await self._repo.update(
            report_id,
            user_id=user_id,
            title=payload.title.strip()[:200] if payload.title is not None else None,
            report_date=payload.report_date,
            category=payload.category.strip()[:32] if payload.category is not None else None,
            tags=(
                json.dumps(normalize_tags(payload.tags), ensure_ascii=False)
                if payload.tags is not None
                else None
            ),
            summary=payload.summary.strip()[:2000] if payload.summary is not None else None,
        )
        if row is None:
            raise HTTPException(404, f"报告 id={report_id} 不存在")
        return self._to_out(row)

    async def delete(self, report_id: int, *, user_id: int | None = None) -> None:
        """删行 + 删磁盘文件。

        ⚠ 顺序是「先 unlink 再删行」还是反过来？取**先删行**：删行成功但 unlink
        失败只留一个孤儿文件（用户无感，下次可手工清）；反过来则可能留下
        「库里没有、文件还在」但 id 已被复用 —— 更糟的是 DELETE 返回成功、
        用户以为删干净了，实际磁盘还在涨。
        """
        row = await self._repo.get(report_id, user_id=user_id)
        if row is None:
            raise HTTPException(404, f"报告 id={report_id} 不存在")
        ok = await self._repo.delete(report_id, user_id=user_id)
        if not ok:
            raise HTTPException(404, f"报告 id={report_id} 不存在")
        path = reports_dir() / row.stored_name
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("报告 #%s 磁盘文件删除失败（记录已删，留孤儿文件）: %s", report_id, exc)

    # ────────────── 辅助查询 ──────────────

    async def categories(self, *, user_id: int | None = None) -> ReportCategoriesOut:
        seen = await self._repo.list_categories(user_id=user_id)
        # 预置分类即使当前没报告也出现在下拉里（用户上传第一份时不用先去别处建分类）
        merged = [*PREDEFINED_CATEGORIES, *[c for c in seen if c not in PREDEFINED_CATEGORIES]]
        return ReportCategoriesOut(categories=merged)

    async def stats(self, *, user_id: int | None = None) -> ReportStatsOut:
        return ReportStatsOut(**await self._repo.get_stats(user_id=user_id))

    # ────────────── 内部 ──────────────

    @staticmethod
    def _to_out(row: Any) -> ReportOut:
        """ORM → Pydantic Out。

        ``tags`` 是 TEXT 里的 JSON 数组；解析失败回退空数组而不是抛错 ——
        一条脏数据不该让整个列表页挂掉（与 ``services/settings.py`` 读
        ``app_settings`` 时的容错读法一致）。
        """
        try:
            parsed = json.loads(row.tags or "[]")
            tags = [str(t) for t in parsed] if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            tags = []
        return ReportOut(
            id=row.id,
            title=row.title,
            original_name=row.original_name,
            size_bytes=row.size_bytes,
            report_date=row.report_date,
            category=row.category,
            tags=tags,
            summary=row.summary or "",
            created_at=row.created_at,
            updated_at=row.updated_at,
            view_url=f"/api/v1/reports/{row.id}/content",
        )
