"""报告存档 REST 端点 单测（V0.111.0）

覆盖：
- POST   /api/v1/reports/upload        上传 4 道校验 + 元数据落库 + 落盘
- GET    /api/v1/reports               列表 + q / category / tag 筛选 + 分页
- GET    /api/v1/reports/{id}          单条
- PATCH  /api/v1/reports/{id}          局部更新
- DELETE /api/v1/reports/{id}          删行 **且** 删磁盘文件
- GET    /api/v1/reports/{id}/content  CSP sandbox 安全头（隔离的关键）
- GET    /api/v1/reports/categories    分类下拉
- GET    /api/v1/reports/stats         侧栏统计

⚠ 两个必须的 fixture：
1. ``_seed_legacy`` —— conftest 每例 drop_all，LEGACY_USER(id=1) 不存在时
   ``require_user`` 单用户回退拿到 None ⇒ 每个写端点 401。
2. ``_tmp_reports_dir`` —— ``REPORTS_DIR`` 不重定向的话，测试会把上传物
   写进**真实** ``data/reports/``（reports_dir() 只认环境变量与 PROJECT_ROOT）。
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.models.user import LEGACY_USER_ID, ROLE_OWNER, User
from app.services.reports import CONTENT_SECURITY_POLICY, MAX_UPLOAD_BYTES

# ──────────────── fixtures ────────────────


@pytest.fixture(autouse=True)
async def _seed_legacy(db_session) -> None:
    """确保 LEGACY_USER(id=1) 存在 —— 单用户模式 ``require_user`` 兜底依赖。"""
    from sqlalchemy import select

    existing = (
        await db_session.execute(select(User).where(User.id == LEGACY_USER_ID))
    ).scalar_one_or_none()
    if existing is None:
        db_session.add(
            User(
                id=LEGACY_USER_ID,
                email="legacy@test",
                display_name="Legacy",
                password_hash="x",
                role=ROLE_OWNER,
                is_active=True,
                created_at=datetime(2026, 1, 1),
                last_login_at=datetime(2026, 1, 1),
            )
        )
        await db_session.commit()


@pytest.fixture(autouse=True)
def _tmp_reports_dir(tmp_path, monkeypatch) -> None:
    """把上传目录重定向到 tmp —— 绝不能让测试往真实 data/reports/ 里写。"""
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))


# ──────────────── helpers ────────────────

_HTML = "<html><head><title>测试研报</title></head><body><h1>金价走势</h1></body></html>"


def _files(name: str = "gold-report.html", content: bytes = _HTML.encode()) -> dict:
    """构造 httpx multipart 的 ``files=`` 参数。"""
    return {"file": (name, content, "text/html")}


async def _upload(client, **form):
    """上传一份默认 HTML；``form`` 里放 title / category / tags / report_date。"""
    files = form.pop("files", _files())
    return await client.post("/api/v1/reports/upload", files=files, data=form or None)


# ──────────────── 上传：正常路径 ────────────────


async def test_upload_ok(client) -> None:
    r = await client.post(
        "/api/v1/reports/upload",
        files=_files(),
        data={
            "title": "十月金价月报",
            "category": "研报",
            "tags": "黄金, 月报",
            "summary": "十月金价复盘",
            "report_date": "2026-10-20",
        },
    )
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["title"] == "十月金价月报"
    assert d["category"] == "研报"
    # 标签规范化：去空白 + 去重 + 字母序
    assert d["tags"] == sorted(["黄金", "月报"])
    assert d["summary"] == "十月金价复盘"
    assert d["report_date"] == "2026-10-20"
    assert d["size_bytes"] == len(_HTML.encode())
    assert d["view_url"] == f"/api/v1/reports/{d['id']}/content"
    # ⚠ 最小暴露：磁盘真名绝不出现在响应里
    assert "stored_name" not in d


async def test_upload_defaults_from_filename(client) -> None:
    """标题缺省取文件名去扩展名；分类缺省「其他」；report_date 可空。"""
    r = await client.post("/api/v1/reports/upload", files=_files("weekly-gold-2026W42.html"))
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["title"] == "weekly-gold-2026W42"
    assert d["category"] == "其他"
    assert d["report_date"] is None
    assert d["tags"] == []
    assert d["summary"] == ""


async def test_upload_accepts_htm(client) -> None:
    """``.htm`` 与 ``.html`` 同等对待。"""
    r = await client.post("/api/v1/reports/upload", files=_files("a.htm"))
    assert r.status_code == 201, r.text


async def test_upload_sanitizes_original_name(client) -> None:
    """路径分隔符被剥掉 —— 只留文件名，不保留目录结构。"""
    r = await client.post("/api/v1/reports/upload", files=_files("秘密/报告.html"))
    assert r.status_code == 201, r.text
    assert "/" not in r.json()["original_name"]


async def test_upload_bad_report_date_falls_back_none(client) -> None:
    """report_date 解析失败回退 None，而不是 500（multipart Form 转换不稳）。"""
    r = await client.post(
        "/api/v1/reports/upload", files=_files(), data={"report_date": "不是日期"}
    )
    assert r.status_code == 201, r.text
    assert r.json()["report_date"] is None


async def test_upload_accepts_bom(client) -> None:
    """UTF-8 BOM 开头也算 HTML —— 去 BOM 后首字节是 '<'。"""
    r = await client.post(
        "/api/v1/reports/upload", files=_files("bom.html", b"\xef\xbb\xbf" + _HTML.encode())
    )
    assert r.status_code == 201, r.text


# ──────────────── 上传：4 道校验（反向） ────────────────


async def test_upload_rejects_non_html_suffix(client) -> None:
    """校验 1：扩展名不是 .html/.htm ⇒ 422。"""
    r = await client.post("/api/v1/reports/upload", files=_files("evil.exe"))
    assert r.status_code == 422
    assert ".html" in r.json()["detail"]


async def test_upload_rejects_binary_content(client) -> None:
    """校验 3：改名成 .html 的二进制 ⇒ 422（首字节不是 '<'）。"""
    r = await client.post("/api/v1/reports/upload", files=_files("fake.html", b"MZ\x90\x00\x03"))
    assert r.status_code == 422
    assert "HTML" in r.json()["detail"]


async def test_upload_rejects_empty_file(client) -> None:
    """校验 4：0 字节 ⇒ 422。"""
    r = await client.post("/api/v1/reports/upload", files=_files("empty.html", b""))
    assert r.status_code == 422
    assert "空" in r.json()["detail"]


async def test_upload_rejects_oversize(client) -> None:
    """校验 2：超过 20MB ⇒ 422（分块读，超限即中止，不整体进内存）。"""
    big = b"<html>" + b"x" * (MAX_UPLOAD_BYTES + 1024) + b"</html>"
    r = await client.post("/api/v1/reports/upload", files=_files("big.html", big))
    assert r.status_code == 422
    assert "20MB" in r.json()["detail"]


async def test_upload_failure_leaves_no_orphan_file(client) -> None:
    """校验失败时磁盘不能留下孤儿文件。"""
    from app.services.reports import reports_dir

    before = set(reports_dir().glob("*")) if reports_dir().exists() else set()
    r = await client.post("/api/v1/reports/upload", files=_files("evil.exe"))
    assert r.status_code == 422
    after = set(reports_dir().glob("*")) if reports_dir().exists() else set()
    assert before == after


# ──────────────── 列表 / 筛选 ────────────────


async def test_list_empty(client) -> None:
    r = await client.get("/api/v1/reports")
    assert r.status_code == 200
    d = r.json()
    assert d["items"] == []
    assert d["total"] == 0
    assert d["limit"] == 50
    assert d["offset"] == 0


async def test_list_filter_by_query(client) -> None:
    """q 同时命中标题 / 摘要 / 原始文件名三列。"""
    await _upload(client, title="十月金价月报")
    await _upload(client, title="白银周报")
    r = await client.get("/api/v1/reports", params={"q": "月报"})
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 1
    assert d["items"][0]["title"] == "十月金价月报"


async def test_list_filter_by_category(client) -> None:
    await _upload(client, title="A", category="研报")
    await _upload(client, title="B", category="宏观")
    r = await client.get("/api/v1/reports", params={"category": "研报"})
    d = r.json()
    assert d["total"] == 1
    assert d["items"][0]["category"] == "研报"


async def test_list_filter_by_tag(client) -> None:
    """tag 走 JSON 数组的精确字符串匹配 —— 「黄金」不该命中「黄金段位」。"""
    await _upload(client, title="A", tags="黄金")
    await _upload(client, title="B", tags="黄金段位, 白银")
    r = await client.get("/api/v1/reports", params={"tag": "黄金"})
    d = r.json()
    assert d["total"] == 1
    assert d["items"][0]["title"] == "A"


async def test_list_pagination_total_matches_filter(client) -> None:
    """列表与 total 用同一套筛选条件 —— 谓词重复就是为这个。"""
    for i in range(5):
        await _upload(client, title=f"报告{i}", category="研报" if i % 2 == 0 else "持仓")
    r = await client.get("/api/v1/reports", params={"category": "研报", "limit": 1, "offset": 0})
    d = r.json()
    assert d["total"] == 3  # 0/2/4
    assert len(d["items"]) == 1
    assert d["limit"] == 1
    assert d["offset"] == 0


async def test_list_escape_like_wildcard(client) -> None:
    """搜 ``100%`` 不该匹配到所有行（LIKE 通配符已转义）。"""
    await _upload(client, title="涨了 100%")
    await _upload(client, title="普通报告")
    r = await client.get("/api/v1/reports", params={"q": "100%"})
    d = r.json()
    assert d["total"] == 1
    assert d["items"][0]["title"] == "涨了 100%"


async def test_list_limit_out_of_range_rejected(client) -> None:
    """limit 越界由 Query 约束直接 422，不进业务层。"""
    assert (await client.get("/api/v1/reports", params={"limit": 0})).status_code == 422
    assert (await client.get("/api/v1/reports", params={"limit": 999})).status_code == 422


# ──────────────── 单条 / PATCH / DELETE ────────────────


async def test_get_one(client) -> None:
    up = (await _upload(client, title="单条")).json()
    r = await client.get(f"/api/v1/reports/{up['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == up["id"]


async def test_get_one_404(client) -> None:
    assert (await client.get("/api/v1/reports/999999")).status_code == 404


async def test_patch_updates_only_given_fields(client) -> None:
    """None = 不更新 —— 只传 title 时其余字段必须原样保留。"""
    up = (await _upload(client, title="旧标题", category="研报", tags="黄金")).json()
    r = await client.patch(f"/api/v1/reports/{up['id']}", json={"title": "新标题"})
    assert r.status_code == 200
    d = r.json()
    assert d["title"] == "新标题"
    assert d["category"] == "研报"
    assert d["tags"] == ["黄金"]


async def test_patch_404(client) -> None:
    assert (await client.patch("/api/v1/reports/999999", json={"title": "x"})).status_code == 404


async def test_patch_too_long_title_422(client) -> None:
    up = (await _upload(client)).json()
    r = await client.patch(f"/api/v1/reports/{up['id']}", json={"title": "x" * 201})
    assert r.status_code == 422


async def test_delete_removes_row_and_disk_file(client) -> None:
    """删除必须同时清掉磁盘文件 —— 孤儿文件会一直涨磁盘且无人认领。"""
    from app.services.reports import reports_dir

    up = (await _upload(client)).json()
    files_before = list(reports_dir().glob("*.html"))
    assert len(files_before) == 1

    r = await client.delete(f"/api/v1/reports/{up['id']}")
    assert r.status_code == 204
    assert (await client.get(f"/api/v1/reports/{up['id']}")).status_code == 404
    assert list(reports_dir().glob("*.html")) == []


async def test_delete_404(client) -> None:
    assert (await client.delete("/api/v1/reports/999999")).status_code == 404


async def test_delete_twice_404(client) -> None:
    up = (await _upload(client)).json()
    assert (await client.delete(f"/api/v1/reports/{up['id']}")).status_code == 204
    assert (await client.delete(f"/api/v1/reports/{up['id']}")).status_code == 404


# ──────────────── /content：隔离的关键 ────────────────


async def test_content_returns_uploaded_html(client) -> None:
    up = (await _upload(client)).json()
    r = await client.get(f"/api/v1/reports/{up['id']}/content")
    assert r.status_code == 200
    assert r.text == _HTML
    assert r.headers["content-type"].startswith("text/html")


async def test_content_has_csp_sandbox(client) -> None:
    """⚠ 隔离的全部依据：sandbox 不带 allow-same-origin ⇒ opaque origin。

    若哪天有人图省事加上 allow-same-origin，报告里的 JS 就能读本页
    localStorage 并直接调全部 /api/v1/* 写端点（生产认证是关的）。
    """
    up = (await _upload(client)).json()
    r = await client.get(f"/api/v1/reports/{up['id']}/content")
    csp = r.headers["content-security-policy"]
    assert csp == CONTENT_SECURITY_POLICY
    assert "sandbox" in csp
    assert "allow-same-origin" not in csp
    # 脚本与弹窗放行（用户要完整渲染 + 可能开外链），网络封死
    assert "allow-scripts" in csp
    assert "connect-src 'none'" in csp
    # 其余三道
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "inline" in r.headers["content-disposition"]
    assert r.headers["cache-control"] == "no-store"


async def test_content_404_missing_row(client) -> None:
    assert (await client.get("/api/v1/reports/999999/content")).status_code == 404


async def test_content_404_when_disk_file_vanished(client, db_session) -> None:
    """记录在、磁盘不在 ⇒ 404 而不是 500（文件被手工删了的可预期路径）。"""
    from sqlalchemy import select

    from app.models.reports import Report
    from app.services.reports import reports_dir

    up = (await _upload(client)).json()
    row = (await db_session.execute(select(Report).where(Report.id == up["id"]))).scalar_one()
    (reports_dir() / row.stored_name).unlink()

    r = await client.get(f"/api/v1/reports/{up['id']}/content")
    assert r.status_code == 404
    assert "丢失" in r.json()["detail"]


async def test_content_not_reachable_after_delete(client) -> None:
    """删掉记录后 /content 一并消失（不会留下可猜 id 的裸文件端点）。"""
    up = (await _upload(client)).json()
    await client.delete(f"/api/v1/reports/{up['id']}")
    assert (await client.get(f"/api/v1/reports/{up['id']}/content")).status_code == 404


# ──────────────── /categories 与 /stats ────────────────


async def test_categories_includes_predefined(client) -> None:
    """预置分类即使当前没报告也出现在下拉里（上传第一份时不用先建分类）。"""
    r = await client.get("/api/v1/reports/categories")
    assert r.status_code == 200
    cats = r.json()["categories"]
    for c in ("研报", "持仓", "复盘", "宏观", "资金", "其他"):
        assert c in cats


async def test_categories_appends_user_defined(client) -> None:
    """库里出现过的自定义分类并入下拉，且不与预置重复。"""
    await _upload(client, title="A", category="自定义类")
    r = await client.get("/api/v1/reports/categories")
    cats = r.json()["categories"]
    assert cats.count("其他") == 1  # 不重复
    assert "自定义类" in cats


async def test_categories_route_not_swallowed_by_report_id(client) -> None:
    """⚠ 路由顺序：/categories 必须注册在 /{report_id} 之前。

    FastAPI 按声明顺序匹配，否则 /categories 会被当成 report_id="categories"
    走进详情分支报 422。
    """
    r = await client.get("/api/v1/reports/categories")
    assert r.status_code == 200
    assert "categories" in r.json()


async def test_stats_route_not_swallowed_by_report_id(client) -> None:
    """同上，/stats 也必须在 /{report_id} 之前。"""
    r = await client.get("/api/v1/reports/stats")
    assert r.status_code == 200
    assert r.json()["total"] == 0


async def test_stats_aggregates(client) -> None:
    await _upload(client, title="A", category="研报")
    await _upload(client, title="B", category="研报")
    await _upload(client, title="C", category="宏观")
    r = await client.get("/api/v1/reports/stats")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 3
    assert d["last_30d_count"] == 3
    assert d["total_bytes"] == len(_HTML.encode()) * 3
    by_cat = {c["category"]: c["count"] for c in d["by_category"]}
    assert by_cat == {"研报": 2, "宏观": 1}


# ──────────────── 跨用户隔离 ────────────────


async def test_other_users_report_not_visible(client, db_session) -> None:
    """跨用户读返回 404 而非 403 —— 不泄露「这个 id 存在」。"""
    from sqlalchemy import update

    from app.models.reports import Report

    up = (await _upload(client)).json()
    # 直接改 owner，模拟「这份报告属于别人」
    await db_session.execute(update(Report).where(Report.id == up["id"]).values(user_id=999))
    await db_session.commit()
    db_session.expire_all()

    assert (await client.get(f"/api/v1/reports/{up['id']}")).status_code == 404
    assert (await client.get(f"/api/v1/reports/{up['id']}/content")).status_code == 404
    assert (await client.delete(f"/api/v1/reports/{up['id']}")).status_code == 404
    assert (
        await client.patch(f"/api/v1/reports/{up['id']}", json={"title": "x"})
    ).status_code == 404
    # 列表里也不再出现
    d = (await client.get("/api/v1/reports")).json()
    assert d["total"] == 0
