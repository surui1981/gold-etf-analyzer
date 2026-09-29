#!/usr/bin/env python
"""校验文档中的技术声明与代码实际一致（文档声明可校验门禁）。

背景
----
2026-09-27 的版本差距对账中发现，文档里出现过「凭空捏造的数据表名」
（`portfolios` / `snapshot_overrides`）、「写错的 localStorage key」
（`pm_dash_layout`）、「不存在的端点 / 页面」等问题。这些错误能长期存活，
根因是 `docs/feature-alignment.md` 的对账**是人工事后补记的**，没有任何机制拦住它。

本脚本把对账升级为**机制门禁**：扫描 `README.md` 与 `docs/*.md`，对其中出现的

  1. **数据表名**（`` `xxx` 表 `` / `` 业务表（`a` / `b`） `` 两种句式）
  2. **localStorage key**（`pm_*`）
  3. **静态页面**（`/static/xxx.html`）
  4. **API 端点**（`/api/v1/...`）

做**存在性断言**，查不到即以 `文件:行号` 报错并非零退出。

用法
----
    python scripts/check_docs_claims.py          # 校验（失败非零退出）
    python scripts/check_docs_claims.py --list   # 打印代码侧真实清单
    python scripts/check_docs_claims.py -v       # 打印每类校验计数

豁免与登记
----------
- `docs/feature-alignment.md` 是对账报告，天然会**引用错误值**用于记述，故整体跳过。
- 规划中尚未落地的名称（如 V0.75.0 规划新建的 `audit_log` 表）请登记到 `ALLOW`。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# ---------------------------------------------------------------- 配置

# 总体规划中、尚未落地的名称（登记于此即视为合法声明）
ALLOW: dict[str, set[str]] = {
    "table": {
        "audit_log",  # V0.75.0 规划：审计日志表
        "data_consistency_audit",  # P2 规划：数据一致性审计
    },
    "endpoint": set(),
    "page": {
        "platinum.html",  # V0.77.0 规划：铂金页
        "palladium.html",  # V0.77.0 规划：钯金页
        "oil.html",  # V0.77.0 规划：原油页
    },
    "ls_key": {
        # V0.75.0 认证：pm_session / pm_csrf 是 **cookie 名**（服务端 Set-Cookie 下发），
        # 不是 localStorage key。localStorage 存不下 HttpOnly cookie 也不该存会话，
        # 故它们永远不会出现在 static/*.js 的 localStorage 调用里 —— 登记为已知的非 LS 名称。
        "pm_session",
        "pm_csrf",
    },
}

# 对账报告天然引用错误值，跳过校验
SKIP_FILES = {"feature-alignment.md"}

DOC_FILES = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]

# ---------------------------------------------------------------- 正则

RE_TABLE_AFTER = re.compile(r"`([a-z][a-z0-9_]*)`\s*(?:表|表内)")
# 「表」前须有明确修饰词才算表名引用（避免「日内分钟表 `xxx`」这类排期表被误判）
RE_TABLE_BEFORE = re.compile(r"(?:数据表|业务表|同表|独立表)\s*[（(]?\s*`([a-z][a-z0-9_]*)`")
RE_TABLE_PAREN = re.compile(r"表\s*[（(]([^）)\n]{1,800})[）)]")
# 括号内是「字段清单」的句式：`table_x` 表（`col_a` / `col_b` …）→ 整段跳过
RE_TABLE_FIELD_PAREN = re.compile(r"`[a-z][a-z0-9_]*`[^（(\n]{0,10}表\s*$")
# 括号内是「表清单」的句式：业务表（`a` / `b` / `c`）→ 取开头连续 token 序列
RE_TABLE_LIST = re.compile(r"\s*(?:`[a-z][a-z0-9_]+`\s*(?:[/、,]|\+)\s*)*(?:`[a-z][a-z0-9_]+`)")
RE_BACKTICK = re.compile(r"`([^`\n]+)`")
RE_LS_KEY = re.compile(r"\bpm_[a-z0-9_]+")
RE_PAGE = re.compile(r"(?:/static/|(?<![\w/])static/)([A-Za-z0-9._-]+\.html)")
RE_ENDPOINT = re.compile(r"`?(?:GET|POST|PUT|DELETE|PATCH|HEAD)?\s*(/api/v1/[A-Za-z0-9_\-{}/.,]+)")
RE_BRACE = re.compile(r"\{([^{}]*)\}")

# 表格清单里需要排除的非表名 token（表头/动词等误入）
TABLE_TOKEN_STOP = {
    "user_id",
    "json",
    "key",
    "sqlite",
    "alembic",
}


# ---------------------------------------------------------------- 代码侧真实清单


def real_tables() -> set[str]:
    names: set[str] = set()
    for py in sorted((ROOT / "src" / "app" / "models").glob("*.py")):
        for m in re.finditer(
            r'__tablename__\s*=\s*["\']([^"\']+)["\']', py.read_text(encoding="utf-8")
        ):
            names.add(m.group(1))
    return names


def real_endpoints() -> set[str]:
    from app.main import app  # 延迟导入：仅在需要时构建 schema

    paths: set[str] = set()
    for p in app.openapi()["paths"]:
        paths.add(RE_BRACE.sub("{p}", p))
    return paths


def real_pages() -> set[str]:
    static = ROOT / "src" / "app" / "static"
    if not static.is_dir():
        static = ROOT / "static"
    return {p.name for p in static.glob("*.html")} | {
        str(p.relative_to(static)).replace("\\", "/") for p in static.glob("*.html")
    }


def real_ls_keys() -> set[str]:
    static = ROOT / "src" / "app" / "static"
    if not static.is_dir():
        static = ROOT / "static"
    keys: set[str] = set()
    for f in list(static.glob("*.js")) + list(static.glob("*.html")):
        keys.update(RE_LS_KEY.findall(f.read_text(encoding="utf-8", errors="ignore")))
    return keys


def expand_endpoint(raw: str) -> list[str]:
    """把 `/…/{a,b,c}` 展开为多个端点，其余 `{x}` 归一为 `{p}`。"""
    raw = raw.rstrip("。，,；;、）)")
    m = RE_BRACE.search(raw)
    if not m or "," not in m.group(1):
        return [RE_BRACE.sub("{p}", raw)]
    prefix, suffix = raw[: m.start()], raw[m.end() :]
    return [
        f"{prefix}{opt.strip()}{RE_BRACE.sub('{p}', suffix)}"
        for opt in m.group(1).split(",")
        if opt.strip()
    ]


def is_file_reference(raw: str) -> bool:
    """判断匹配到的是「源码文件路径」而非 API 端点。

    背景（2026-09-29 新增）：``RE_ENDPOINT`` 会在任意位置抓取 ``/api/v1/…``，
    因此文档里写 ``src/app/api/v1/endpoints/auth.py``（模块路径）会被误判成
    一个端点 ``/api/v1/endpoints/auth.py`` —— 这类**假失败**会逼作者在文档里
    绕弯写作（把路径拆开或省略），反而降低可读性。

    判据：带源码扩展名（``.py`` / ``.js`` / ``.html`` / ``.md`` …），
    或首段是目录名而非资源名（``endpoints`` / ``middleware`` / ``models`` /
    ``services`` / ``schemas`` / ``repositories``）。
    """
    tail = raw.rstrip("/}).,;")
    if re.search(r"\.(py|js|ts|html|md|json|yml|yaml|toml)$", tail):
        return True
    segments = tail.split("/")
    # /api/v1/<segment>/... → segment 是「后端包名」时判为模块路径
    if len(segments) >= 4 and segments[3] in {
        "endpoints",
        "middleware",
        "models",
        "services",
        "schemas",
        "repositories",
        "utils",
    }:
        return True
    return False


# ---------------------------------------------------------------- 校验


def check() -> tuple[list[str], dict[str, int]]:
    tables = real_tables()
    pages = real_pages()
    ls_keys = real_ls_keys()
    endpoints = real_endpoints()

    problems: list[str] = []
    stats = {"table": 0, "page": 0, "ls_key": 0, "endpoint": 0}
    seen: set[tuple[str, int, str, str]] = set()

    def flag(rel: str, lineno: int, kind: str, value: str, why: str) -> None:
        key = (rel, lineno, kind, value)
        if key in seen:
            return
        seen.add(key)
        problems.append(f"{rel}:{lineno}  [{kind}] `{value}` {why}")

    for doc in DOC_FILES:
        if not doc.exists() or doc.name in SKIP_FILES:
            continue
        for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            rel = doc.relative_to(ROOT).as_posix()

            # ---- 1. 数据表名 ----
            candidates: set[str] = set(RE_TABLE_AFTER.findall(line)) | set(
                RE_TABLE_BEFORE.findall(line)
            )
            for paren in RE_TABLE_PAREN.finditer(line):
                # 形如「`telemetry_events` 表（`event_type` / `page` …）」→ 括号内是该表的字段清单，跳过
                # 注意 +1：paren.start() 指向「表」字本身，切片需含它才能匹配 RE_TABLE_FIELD_PAREN 的结尾
                if RE_TABLE_FIELD_PAREN.search(line[: paren.start() + 1]):
                    continue
                # 仅当括号内容以「`a` / `b` / `c`」形式开头时，才当作表清单
                seq = RE_TABLE_LIST.match(paren.group(1))
                if seq:
                    for tok in RE_BACKTICK.findall(seq.group(0)):
                        if re.fullmatch(r"[a-z][a-z0-9_]{2,}", tok.strip()):
                            candidates.add(tok.strip())
            for tok in sorted(candidates):
                if tok in TABLE_TOKEN_STOP:
                    continue
                stats["table"] += 1
                if tok not in tables and tok not in ALLOW["table"]:
                    flag(
                        rel, lineno, "table", tok, "不是任何模型的 __tablename__，且未登记在 ALLOW"
                    )

            # ---- 2. localStorage key ----
            for key in sorted(set(RE_LS_KEY.findall(line))):
                stats["ls_key"] += 1
                # 支持前缀引用（文档惯用 `pm_help_*` 表示命名空间）
                if (
                    key not in ls_keys
                    and not any(k.startswith(key) for k in ls_keys)
                    and key not in ALLOW["ls_key"]
                ):
                    flag(rel, lineno, "ls_key", key, "未在任何 static/*.js|*.html 中出现")

            # ---- 3. 静态页面 ----
            for page in sorted(set(RE_PAGE.findall(line))):
                stats["page"] += 1
                if page not in pages and page not in ALLOW["page"]:
                    flag(rel, lineno, "page", page, "static/ 下不存在该页面")

            # ---- 4. API 端点 ----
            for raw in RE_ENDPOINT.findall(line):
                if is_file_reference(raw):
                    continue  # 源码模块路径（如 src/app/api/v1/endpoints/auth.py），非端点
                for ep in expand_endpoint(raw):
                    stats["endpoint"] += 1
                    if ep not in endpoints and ep not in ALLOW["endpoint"]:
                        flag(rel, lineno, "endpoint", ep, "不在 app.openapi()['paths'] 中")

    return problems, stats


def main() -> int:
    if "--list" in sys.argv:
        print("数据表（__tablename__）：")
        for t in sorted(real_tables()):
            print(f"  {t}")
        print(f"\n静态页 {len(real_pages())} 个 / localStorage key {len(real_ls_keys())} 个")
        from app.main import app

        print(f"API 端点路径 {len(app.openapi()['paths'])} 条")
        return 0

    problems, stats = check()
    total = sum(stats.values())
    print(
        f"文档声明校验：表名 {stats['table']} / localStorage key {stats['ls_key']} / "
        f"页面 {stats['page']} / 端点 {stats['endpoint']}（共 {total} 处引用）"
    )
    if problems:
        print(f"\n[FAIL] {len(problems)} 处声明与代码不符：\n")
        for p in problems:
            print(f"  {p}")
        print("\n修正文档，或（若确为规划项）登记到 scripts/check_docs_claims.py 的 ALLOW。")
        return 1
    print("[OK] 全部声明均可在代码中找到对应实体")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
