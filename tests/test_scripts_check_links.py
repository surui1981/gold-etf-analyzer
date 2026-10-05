"""死链门禁（`scripts/check_links.py`）的回归测试。

为什么需要单独测这个脚本：`check_links.py` 的核心是一段**锚点 slug 算法**，
它必须与 GitHub 实际渲染出的锚点 id 一致 —— 否则门禁会**误报**（把有效链接判为失效），
而误报会让后来者直接失去对门禁的信任，比漏报更糟。

本模块的断言分两层：

1. **金标准**：用 2026-10-05 从 GitHub blob 页面 HTML 实测取得的权威 `href` 做断言。
   这条来自真实渲染结果，不是「我觉得应该是什么」。
2. **行为**：用临时文件注入坏链接，确证脚本真能抓到问题 ——
   只靠「仓库当前恰好干净」无法证明门禁有效。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_links  # noqa: E402

# GitHub 权威锚点（2026-10-05 由
# https://github.com/surui1981/gold-etf-analyzer/blob/main/docs/improvement-path.md
# 的 HTML 中 `id="user-content-..."` 实测取得，去掉 user-content- 前缀）
GOLDEN_ANCHOR = "三五下一阶段路线v0670--v0720-工程化补齐--业务深度--产品化"

# V0.78.0 修复前的写法（错两处：全角括号被删后不留分隔符却多写一个连字符；
# 中点只产生一个连字符却写成两个）。它必须**不被**接受，否则门禁形同虚设。
STALE_ANCHOR = "三五下一阶段路线-v0670--v0720--工程化补齐--业务深度--产品化"


def test_golden_anchor_is_recognized() -> None:
    """权威 href 必须能被识别 —— 否则有效链接会被误报为失效。"""
    anchors = check_links.anchors_of(REPO_ROOT / "docs" / "improvement-path.md")
    assert GOLDEN_ANCHOR in anchors


def test_stale_anchor_is_rejected() -> None:
    """修复前的错误写法必须被拒绝 —— 这是门禁的存在意义。"""
    anchors = check_links.anchors_of(REPO_ROOT / "docs" / "improvement-path.md")
    assert STALE_ANCHOR not in anchors


def test_circled_digit_is_removed_like_github() -> None:
    """GitHub 会删掉 `①`：`V0.75.0 第 ① 步` → `...第--步`（不是 `第-①-步`）。

    实测自 `docs/api-reference.md`。若只保留宽字符集（`\\w` 含 `①`），
    该锚点会被漏判为失效 —— 校准中真实出现过的 2 处漏报之一。
    """
    cands = check_links.slug_candidates("6.5 认证与账号体系（V0.75.0 第 ① 步）")
    assert "65-认证与账号体系v0750-第--步" in cands


def test_setext_requires_adjacent_underline() -> None:
    """`段落 + 空行 + ---` 不是 Setext 标题，不得产生锚点。

    回归防护：初版用 `\\s*\\n` 匹配下划线，把水平分隔线误判为标题，
    在 4 份文档上凭空造出 **118 个垃圾锚点**（锚点集合从 ~60 撑到 ~120），
    显著推高误报概率。
    """
    cands = check_links.slug_candidates("验收标准：录入一笔交易 ≤ 3 次点击")
    # 这些"标题"从未存在过；锚点集合里不该出现它们
    assert "--验收标准录入一笔交易--3-次点击" not in cands


def test_detects_missing_file(tmp_path: Path) -> None:
    """负向：指向不存在文件的链接必须被检出。"""
    doc = tmp_path / "a.md"
    doc.write_text("[坏链接](nope.md)\n", encoding="utf-8")
    problems, _, _ = check_links.check_files([doc], skip_dirs=set())
    assert len(problems) == 1
    assert "链接目标不存在" in problems[0]


def test_detects_broken_anchor(tmp_path: Path) -> None:
    """负向：锚点在目标文件里不存在时必须被检出。"""
    (tmp_path / "target.md").write_text("# 真实标题\n", encoding="utf-8")
    doc = tmp_path / "a.md"
    doc.write_text("[坏锚点](target.md#不存在的锚点)\n", encoding="utf-8")
    problems, _, _ = check_links.check_files([doc], skip_dirs=set())
    assert len(problems) == 1
    assert "锚点失效" in problems[0]


def test_accepts_valid_anchor(tmp_path: Path) -> None:
    """正向：有效锚点不得误报。"""
    (tmp_path / "target.md").write_text("## 3.1 阈值口径\n", encoding="utf-8")
    doc = tmp_path / "a.md"
    doc.write_text("[对](target.md#31-阈值口径)\n", encoding="utf-8")
    problems, links, anchors = check_links.check_files([doc], skip_dirs=set())
    assert problems == []
    assert links == 1
    assert anchors == 1


def test_external_and_anchor_only_links_are_skipped(tmp_path: Path) -> None:
    """外链不检查；纯 `#anchor` 指向本文件。"""
    doc = tmp_path / "a.md"
    doc.write_text(
        "[外链](https://example.com/x#y)\n[本节](#本地标题)\n\n## 本地标题\n",
        encoding="utf-8",
    )
    problems, links, anchors = check_links.check_files([doc], skip_dirs=set())
    assert problems == []
    assert links == 1  # 只算了 #本地标题 这条
    assert anchors == 1


@pytest.mark.parametrize("rel", ["README.md"])
def test_repo_readme_has_no_broken_links(rel: str) -> None:
    """仓库自身的 README 必须零失效链接。"""
    problems, _, _ = check_links.check_files([REPO_ROOT / rel], skip_dirs=set())
    assert problems == []


def test_repo_docs_have_no_broken_links() -> None:
    """仓库全部文档必须零失效链接（与 `main()` 的扫描范围一致）。"""
    problems, links, _ = check_links.check_files(check_links.DOC_FILES)
    assert problems == [], f"以下链接失效：{problems}"
    assert links > 50, "链接总数异常偏少，可能是扫描范围被改坏了"
