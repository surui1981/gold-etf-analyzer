"""聚类渲染行为门禁（V0.77.0）—— tests/test_ui_cluster_render.py

`scripts/check_static_js.py` 只做静态检查（语法 / 未定义调用 / DOM id），
查不出「渲染出来的 HTML 结构对不对」。本模块调用 `scripts/check_cluster_render.mjs`，
在 Node 里用最小 DOM 桩**真实执行**各页的聚类渲染代码块，断言产出的结构
（簇数量 / 簇标题 / 卡片数 / 分组顺序）。

为什么值得单独立一道门禁：V0.77.0 的聚类改造（首页 8 张 KPI 卡分 3 组、上海金 6 张分 2 组、
trades 6 张 KPI 聚 2 簇、data-health 6 个数据源从两处渲染合并到一处、review 三组横条并为
Tab 分面）全部落在渲染逻辑里 —— 语法正确、DOM id 一个不差，静态门禁全绿，但分组完全
可能不出现。开发期就踩过一次：验证脚本只提取到函数定义却没调用它，innerHTML 为空、
断言却「看起来通过」，这正是「静态门禁全绿 ≠ 渲染正确」的又一例。

无 node 时跳过（与 `check_static_js.py`「找不到 node 只做静态引用检查」的降级策略一致）。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_cluster_render.mjs"


def _find_node() -> str | None:
    """按优先级探测 node：PATH → 常见安装位置（含 workbuddy 托管目录）。"""
    found = shutil.which("node")
    if found:
        return found
    # 环境变量名全大写（ruff SIM112）；Windows 上 os.environ 大小写不敏感，取值不受影响。
    cands = [
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "nodejs" / "node.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "nodejs" / "node.exe",
    ]
    managed = Path.home() / ".workbuddy" / "binaries" / "node"
    if managed.is_dir():
        cands.extend(sorted(managed.glob("versions/*/node.exe"), reverse=True))
    for cand in cands:
        if cand.is_file():
            return str(cand)
    return None


def test_cluster_render_structure() -> None:
    """各页聚类渲染产出的 HTML 结构必须符合预期（真实执行，非静态匹配）。"""
    node = _find_node()
    if node is None:
        pytest.skip("未找到 node，跳过聚类渲染行为验证")

    # 注意：不要传「只有 PATH」的极简环境 —— Windows 上 node 初始化 CSPRNG
    # 需要 SystemRoot，缺省会以 `Assertion failed: ncrypto::CSPRNG` 崩溃（rc=134）。
    # 继承当前进程环境再叠加即可，跨平台行为一致。
    env = dict(os.environ)
    res = subprocess.run(
        [node, str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=180,
    )
    assert res.returncode == 0, (
        "聚类渲染结构验证失败：\n" + (res.stdout or "") + "\n" + (res.stderr or "")
    )
