"""报告存档 REST 端点（V0.111.0）

7 个端点：
- GET    /api/v1/reports              列表（q / category / tag 筛选 + 分页）
- GET    /api/v1/reports/{id}         单条元数据
- GET    /api/v1/reports/{id}/content **HTML 本体**（CSP sandbox 隔离，见下）
- GET    /api/v1/reports/categories   分类 distinct（喂筛选下拉）
- GET    /api/v1/reports/stats        侧栏统计
- POST   /api/v1/reports/upload       上传（multipart；require_user）
- PATCH  /api/v1/reports/{id}         改登记表字段（require_user）
- DELETE /api/v1/reports/{id}         删除记录 + 磁盘文件（require_user）

⚠⚠ ``/{id}/content`` 是本模块的安全关键端点
----------------------------------------------------
上传的 HTML 与主站**同源**。生产 ``.env.prod`` 没有 ``AUTH_ENABLED`` ⇒ 认证关闭、
不签发 cookie、``user_id`` 恒为 1，连 ``ADMIN_TOKEN`` 校验都被
``middleware/admin_auth.py:9-10`` 跳过 —— 一份裸发的同源 HTML 里的 JS 能直接
调**全部** ``/api/v1/*`` 写端点（改 V0.110.0 的评估权重、删收藏…）。

因此这个响应强制带 :data:`CONTENT_SECURITY_POLICY`：

    sandbox allow-scripts allow-popups; connect-src 'none'; ...

``sandbox`` 不带 ``allow-same-origin`` ⇒ 文档进入 **opaque origin**，读不到
localStorage / cookie、够不到父页面；``connect-src 'none'`` 再封死
fetch / XHR / sendBeacon / WebSocket ⇒ 调不动任何接口。脚本与样式照常加载，
**渲染保真度不受影响**（不给 ``default-src`` 正是不想禁掉外部 CSS/字体/图片）。

配套：``X-Content-Type-Options: nosniff``（防 MIME 嗅探）+ ``Content-Disposition:
inline``（内联渲染而非下载）。
"""

from datetime import date as _date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse

from app.dependencies import get_report_repository, get_report_service, require_user
from app.repositories.reports import ReportRepository
from app.schemas.reports import (
    ReportCategoriesOut,
    ReportListOut,
    ReportOut,
    ReportStatsOut,
    ReportUpdateIn,
)
from app.services.reports import CONTENT_SECURITY_POLICY, ReportService, reports_dir

router = APIRouter(prefix="/reports", tags=["reports"])

_CONTENT_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    # 「inline」而非「attachment」：报告要**在浏览器里渲染**，attachment 会直接
    # 触发下载。文件名给 RFC 5987 的 filename*（中文名在 filename 里会被截断）。
    "Content-Disposition": 'inline; filename="report.html"',
    # 报告内容随用户上传变化，禁缓存以免 A 改完看到 B 的旧版
    "Cache-Control": "no-store",
}


# ────────────── 读 ──────────────


@router.get("", response_model=ReportListOut, summary="报告列表（检索 + 分页）")
async def list_reports(
    q: str | None = Query(None, max_length=200, description="标题 / 摘要 / 原始文件名模糊搜索"),
    category: str | None = Query(None, max_length=32, description="按分类精确筛选"),
    tag: str | None = Query(None, max_length=32, description="标签精确包含（LIKE 模式）"),
    limit: int = Query(50, ge=1, le=200, description="返回上限"),
    offset: int = Query(0, ge=0, description="跳过条数"),
    service: ReportService = Depends(get_report_service),
) -> ReportListOut:
    return await service.list_reports(q=q, category=category, tag=tag, limit=limit, offset=offset)


@router.get("/categories", response_model=ReportCategoriesOut, summary="分类列表（筛选下拉）")
async def categories(
    service: ReportService = Depends(get_report_service),
) -> ReportCategoriesOut:
    """⚠ 路径必须注册在 ``/{report_id}`` **之前** —— FastAPI 按声明顺序匹配路由，
    ``/categories`` 若排在 ``/{report_id}`` 后面会被当成 report_id="categories"
    而走到单条详情分支报 422。
    """
    return await service.categories()


@router.get("/stats", response_model=ReportStatsOut, summary="侧栏统计")
async def stats(
    service: ReportService = Depends(get_report_service),
) -> ReportStatsOut:
    return await service.stats()


@router.get("/{report_id}", response_model=ReportOut, summary="单条报告元数据")
async def get_report(
    report_id: int,
    service: ReportService = Depends(get_report_service),
) -> ReportOut:
    return await service.get(report_id)


@router.get(
    "/{report_id}/content",
    summary="报告 HTML 本体（带 CSP sandbox 隔离，新标签页打开）",
    response_class=FileResponse,
)
async def get_report_content(
    report_id: int,
    repo: ReportRepository = Depends(get_report_repository),
) -> FileResponse:
    """返回报告 HTML 原文，强制 ``Content-Security-Policy: sandbox``。

    路径安全：``reports_dir() / row.stored_name`` —— ``stored_name`` 是入库时
    服务端生成的 ``uuid4().hex.html``，不是用户输入，所以这里不存在目录穿越。
    仍显式做一次 ``resolve()`` 断言，把「万一哪天有人改成原名入库」当场变成
    500 而不是静默读到 ``/etc/passwd``。
    """
    row = await repo.get(report_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"报告 id={report_id} 不存在")

    base = reports_dir().resolve()
    path = (base / row.stored_name).resolve()
    if base not in path.parents:
        # 正常路径永远走不到这里（stored_name 是 uuid）；走到即说明数据被篡改
        raise HTTPException(status_code=500, detail="报告文件路径越界")
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"报告文件已丢失（记录在、磁盘不在）：{row.original_name}",
        )

    return FileResponse(
        path,
        media_type="text/html; charset=utf-8",
        headers=_CONTENT_HEADERS,
    )


# ────────────── 写 ──────────────


@router.post(
    "/upload",
    response_model=ReportOut,
    status_code=status.HTTP_201_CREATED,
    summary="上传 HTML 报告（multipart；require_user）",
)
async def upload_report(
    file: UploadFile = File(..., description="报告 HTML 文件（.html / .htm，≤20MB）"),
    title: str | None = Form(None, description="报告标题（缺省取文件名）"),
    report_date: str | None = Form(None, description="报告自身日期 YYYY-MM-DD（可空）"),
    category: str | None = Form(None, description="分类（缺省「其他」）"),
    tags: str | None = Form(None, description="标签，逗号分隔或 JSON 数组字符串"),
    summary: str | None = Form(None, description="一句话摘要"),
    user=Depends(require_user),
    service: ReportService = Depends(get_report_service),
) -> ReportOut:
    """⚠ ``user = Depends(require_user)`` 显式取用户（不只是 ``dependencies=[...]``
    丢弃返回值）—— 报告挂 ``user_id``，多用户模式下必须落到正确的 owner 上。
    单用户模式下 ``require_user`` 回退 LEGACY_USER(id=1)，零配置可用。

    ``report_date`` 以字符串收（multipart 的 Form 字段类型转换在 Pydantic v2 下
    不稳），在 service 入口手动解析，解析失败回退 None 而不是 500。
    """
    parsed_date = None
    if report_date:
        try:
            parsed_date = _date.fromisoformat(report_date.strip())
        except ValueError:
            parsed_date = None

    return await service.upload(
        file,
        user_id=user.id,
        title=title,
        report_date=parsed_date,
        category=category,
        tags=tags,
        summary=summary,
    )


@router.patch(
    "/{report_id}",
    response_model=ReportOut,
    summary="修改报告登记表字段（require_user）",
)
async def update_report(
    report_id: int,
    payload: ReportUpdateIn,
    user=Depends(require_user),
    service: ReportService = Depends(get_report_service),
) -> ReportOut:
    """任一字段为 None → 不更新。磁盘文件不受影响。"""
    return await service.update(report_id, payload, user_id=user.id)


@router.delete(
    "/{report_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除报告（记录 + 磁盘文件；require_user）",
)
async def delete_report(
    report_id: int,
    user=Depends(require_user),
    service: ReportService = Depends(get_report_service),
) -> None:
    await service.delete(report_id, user_id=user.id)
