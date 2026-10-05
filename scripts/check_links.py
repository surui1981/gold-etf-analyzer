#!/usr/bin/env python
r"""校验 markdown 文档内部链接有效（第 6 道门禁 · 死链 / 锚点）。

背景
----
本项目文档体量大（README + `docs/` 十余份，其中数份超过 2000 行），相互 cross-link 密集。
链接失效**不会**让任何既有门禁变红：`check_docs_claims.py` 只校验文档里**声明**的实体名
（表 / 端点 / 页面 / localStorage key）存在，**完全不看链接**；`check_static_js.py` 只管前端。

2026-10-05 实测到的实例：`docs/ux-roadmap.md:5` 指向 `improvement-path.md` 的锚点失效
（旧链接把「全角括号被删后不留分隔符」与「中点只产生一个连字符」两处都写错了），
它自 `867b579` 起存在了多个版本而无人发现。

本脚本把这件事机械化：扫描 `README.md` 与 `docs/**/*.md` 的 markdown 链接，断言

  1. **目标文件存在**（相对路径按所在文档目录解析）；
  2. **锚点在目标文件里能解析** —— 支持三种锚点来源：
     - ATX 标题（`## 标题`）
     - Setext 标题（`标题` + 下一行 `===` / `---`）
     - 显式 HTML 锚（`<a id="...">` / `<a name="...">`）

锚点 slug 规则（必须与 GitHub 实际渲染一致）
--------------------------------------------
小写 → 删除标点（保留字母 / 数字 / 中日韩字符 / 连字符 / 下划线 / **空格**）→ 每个空格转连字符。

⚠ 本脚本对该规则做了**容错**：同时接受「每个空格各转一个连字符」（GitHub 实际行为）
与「连续空格压缩为一个连字符」两种写法，避免因规则细节差异产生**误报**。
误报比漏报更糟 —— 会让后来者失去对门禁的信任。

豁免
----
- 外部链接（`http` / `https` / `mailto` / `tel` / `data`）与纯 `#anchor` 不检查；
- `docs/reports/` 下的历史报告：**只校验文件存在性，跳过锚点校验**。
  与 `check_docs_claims.py` 的 `SKIP_FILES` 同一原则 —— 报告是历史快照，其锚点可能因
  目标文档后来重构而失效，但**改写历史记录的措辞**不是正确修法。

用法
----
    python scripts/check_links.py          # 校验（失败非零退出）
    python scripts/check_links.py -v       # 打印每份文档的链接数
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 扫描范围：README + docs 下全部 md（**递归**，与 check_docs_claims.py 的非递归范围不同，
# 因为死链是「点不开」的缺陷，历史报告里的坏链接同样应修）。
DOC_FILES: list[Path] = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]

# 历史快照目录：跳过锚点校验，只看文件存在性
ANCHOR_SKIP_DIRS = {ROOT / "docs" / "reports"}

EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "tel:", "data:", "ftp://")

# `[text](target)` 与 `![alt](target)`；允许可选的 "title"
LINK_RE = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)>\s]+)>?(?:\s+[\"'][^\"']*[\"'])?\s*\)")

ATX_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.M)
# Setext 标题：文本行**紧接**下一行 `===` / `---`（中间不得有空行）。
# ⚠ 必须用 `\n` 而非 `\s*\n`：后者会把「普通段落 + 空行 + 水平分隔线 `---`」误判成标题，
#    实测在 4 份文档上凭空产生 **118 个垃圾锚点**（把锚点集合从 ~60 撑到 ~120），
#    直接推高误报概率 —— 详见 `_calib_links.py` 的权威对账输出。
SETEXT_RE = re.compile(r"^(?![#\s|>\-])(.+?)[ \t]*\n(={3,}|-{3,})[ \t]*$", re.M)
HTML_ANCHOR_RE = re.compile(r"<a\s+[^>]*(?:id|name)\s*=\s*\"([^\"]+)\"", re.I)

# 行内标记：生成 slug 前需剥离，否则 `**P0**` / `` `code` `` 会算出多余连字符
INLINE_PATTERNS = (
    (re.compile(r"`([^`]*)`"), r"\1"),
    (re.compile(r"\*\*([^*]*)\*\*"), r"\1"),
    (re.compile(r"\*([^*]*)\*"), r"\1"),
    (re.compile(r"\[([^\]]*)\]\([^)]*\)"), r"\1"),
    (re.compile(r"!\[([^\]]*)\]\([^)]*\)"), r"\1"),
)


def _strip_inline(text: str) -> str:
    for pat, repl in INLINE_PATTERNS:
        text = pat.sub(repl, text)
    return text


def slug_candidates(text: str) -> set[str]:
    """给定标题原文，返回它**可能**对应的锚点 id 集合。

    ⚠ 本函数故意返回**多个候选**（而非 GitHub 的唯一正解），原则是
    「**宁愿多给候选，也不要误报**」—— 误报会让后来者失去对门禁的信任。

    两处容错，均由 `_calib_links.py` 对 GitHub blob HTML 的权威对账确定：

    1. **字符集**：宽字符集（`\\w`）会保留 `①` 这类 Unicode 数字符号，而 GitHub 会删除它。
       实例：`docs/api-reference.md` 的「V0.75.0 第 ① 步」→ GitHub 生成 `第--步`。
       故同时产出「窄」变体（仅 ASCII 字母数字 + CJK 汉字 + `-`/`_`）。
    2. **空格**：GitHub 是「每个空格各转一个连字符」，但也产出「连续空格压缩为一个」的
       变体，以容忍规则细节差异。
    """
    t = _strip_inline(text).strip().lower()

    wide = re.sub(r"[^\w\s-]", "", t, flags=re.UNICODE)
    narrow = re.sub(r"[^a-z0-9\u4e00-\u9fff\s_-]", "", t)

    cands: set[str] = set()
    for base in (wide, narrow):
        base = base.strip()
        if not base:
            continue
        cands.add(re.sub(r"\s", "-", base))  # GitHub 实际：每个空格各转一个连字符
        cands.add(re.sub(r"\s+", "-", base))  # 容错：连续空格压缩为一个
    # 容错：去掉首尾连字符（标题两侧空白所致）
    cands |= {c.strip("-") for c in cands}
    return {c for c in cands if c}


def anchors_of(path: Path) -> set[str]:
    """目标文件里全部可用锚点 id。"""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return set()

    anchors: set[str] = set(HTML_ANCHOR_RE.findall(text))

    for m in ATX_RE.finditer(text):
        anchors |= slug_candidates(m.group(2))
    for m in SETEXT_RE.finditer(text):
        anchors |= slug_candidates(m.group(1))

    return anchors


def _link_targets(text: str) -> list[tuple[int, str]]:
    """返回 (行号, 目标) 列表，行号从 1 起。"""
    out: list[tuple[int, str]] = []
    for m in LINK_RE.finditer(text):
        line_no = text.count("\n", 0, m.start()) + 1
        out.append((line_no, m.group(1)))
    return out


def _in_anchor_skip_dir(path: Path, skip_dirs: set[Path] | None = None) -> bool:
    dirs = ANCHOR_SKIP_DIRS if skip_dirs is None else skip_dirs
    return any(d in path.parents for d in dirs)


def check_files(
    docs: list[Path],
    skip_dirs: set[Path] | None = None,
    verbose: bool = False,
) -> tuple[list[str], int, int]:
    """校验给定文档列表。返回 (问题列表, 内部链接数, 校验过的锚点数)。

    逻辑抽成独立函数，便于测试注入临时文件 —— 只靠「仓库当前恰好干净」无法证明
    门禁真能抓到问题。
    """
    problems: list[str] = []
    total_links = 0
    total_anchors = 0

    for doc in docs:
        if not doc.is_file():
            continue
        try:
            rel_doc = doc.relative_to(ROOT).as_posix()
        except ValueError:
            rel_doc = doc.as_posix()
        text = doc.read_text(encoding="utf-8")
        links = _link_targets(text)
        n_anchor = 0
        doc_problems = 0
        skip_anchor = _in_anchor_skip_dir(doc, skip_dirs)

        for line_no, target in links:
            if target.startswith(EXTERNAL_PREFIXES):
                continue
            total_links += 1

            path_part, _, anchor = target.partition("#")
            anchor = anchor.strip()

            # 纯 #anchor：指向本文件
            if not path_part:
                if anchor and not skip_anchor:
                    n_anchor += 1
                    if anchor not in anchors_of(doc):
                        problems.append(
                            f"{rel_doc}:{line_no} 锚点 #{anchor} 在本文件中不存在"
                        )
                        doc_problems += 1
                continue

            target_path = (doc.parent / path_part).resolve()
            if not target_path.exists():
                problems.append(f"{rel_doc}:{line_no} 链接目标不存在：{target}")
                doc_problems += 1
                continue

            if anchor and not skip_anchor:
                n_anchor += 1
                if target_path.is_dir():
                    continue
                if anchor not in anchors_of(target_path):
                    problems.append(
                        f"{rel_doc}:{line_no} 锚点失效：{target}（目标文件无 #{anchor}）"
                    )
                    doc_problems += 1

        total_anchors += n_anchor
        if verbose:
            mark = "FAIL" if doc_problems else "OK  "
            print(f"  [{mark}] {rel_doc}  链接 {len(links)} · 待校验 {n_anchor} 锚点")

    return problems, total_links, total_anchors


def main(argv: list[str]) -> int:
    verbose = "-v" in argv
    problems, total_links, total_anchors = check_files(DOC_FILES, verbose=verbose)

    print()
    if problems:
        print(f"[FAIL] 发现 {len(problems)} 个失效链接：")
        for p in problems:
            print(f"  - {p}")
        return 1

    print(
        f"[OK] 死链门禁通过：{len(DOC_FILES)} 份文档、"
        f"{total_links} 条内部链接 + {total_anchors} 个锚点全部有效"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
