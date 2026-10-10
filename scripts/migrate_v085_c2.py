#!/usr/bin/env python3
"""V0.85.0 C2 migration script: 9 pages statusPanel summary 改造.

把 <span id="freshnessInline"> 替换为:
  - 8 页非 health: <a id="healthSummary" class="hs-chip-link" href="/data-health.html"></a>
  - data-health.html: <span id="healthSummary" class="hs-panel" aria-live="polite" aria-atomic="false"></span>

CSS: #freshnessInline → #healthSummary
Script: 删 freshness.js，加 health-summary.js
注释: V0.84.0 注释更新为 V0.85.0
"""
import re
import sys
from pathlib import Path

STATIC = Path("/home/surui/gold-etf-analyzer/static")

NON_HEALTH_PAGES = [
    "backtest.html",
    "central_bank.html",
    "portfolio.html",
    "review.html",
    "silver.html",
    "trades.html",
    "trend.html",
    "weights.html",
]

DATA_HEALTH_PAGE = "data-health.html"


def migrate_non_health(html: str) -> str:
    # 1. 替换 CSS 选择器
    html = html.replace(
        ".status-panel > summary #freshnessInline",
        ".status-panel > summary #healthSummary",
    )
    # 2. 替换挂载点 markup
    old_mount = '<span id="freshnessInline" aria-live="polite" aria-atomic="false"></span>'
    new_mount = '<a id="healthSummary" class="hs-chip-link" href="/data-health.html" aria-label="数据健康"></a>'
    if old_mount not in html:
        # 容错：可能 aria 属性顺序不同
        m = re.search(
            r'<span id="freshnessInline"[^>]*></span>', html
        )
        if m:
            html = html.replace(m.group(0), new_mount, 1)
    else:
        html = html.replace(old_mount, new_mount, 1)

    # 3. 替换注释（V0.84.0 → V0.85.0）
    html = html.replace(
        "<!-- V0.84.0 方案 C · 状态条 disclosure：summary = 时效 chips + 警示计数 pill（1 行 ~36px）；\n       body = 完整警示 5 条 + dismiss checkbox。由 warning.js 维持展开态。 -->",
        "<!-- V0.85.0 · 数据时效迁移到 /data-health.html：summary = 健康摘要 chip（6 数据源聚合）+ 警示 pill\n       点击 chip 跳 data-health.html（不展开 disclosure）；由 health-summary.js 维持 60s 自动刷新 -->",
    )
    html = html.replace(
        "<!-- V0.84.0 方案 C：状态条 disclosure（数据时效 + 警示计数合并 1 行）",
        "<!-- V0.85.0：数据时效迁移到 /data-health.html（summary = 健康摘要 chip + 警示 pill",
    )

    # 4. 替换脚本：删 freshness.js，加 health-summary.js
    html = re.sub(
        r'<script src="/static/freshness\.js"></script>\n?',
        '<script src="/static/health-summary.js"></script>\n',
        html,
    )
    # 如果之前没有 freshness.js（如 backtest/central_bank），追加 health-summary.js
    if 'src="/static/health-summary.js"' not in html:
        # 插在 warning.js 之前
        html = html.replace(
            '<script src="/static/warning.js"></script>',
            '<script src="/static/health-summary.js"></script>\n  <script src="/static/warning.js"></script>',
            1,
        )

    return html


def migrate_data_health(html: str) -> str:
    # 1. CSS 选择器
    html = html.replace(
        ".status-panel > summary #freshnessInline",
        ".status-panel > summary #healthSummary",
    )
    # 2. 挂载点 → 4-chip panel
    old_mount = '<span id="freshnessInline" aria-live="polite" aria-atomic="false"></span>'
    new_mount = '<span id="healthSummary" class="hs-panel" aria-live="polite" aria-atomic="false"></span>'
    html = html.replace(old_mount, new_mount, 1)

    # 3. 注释
    html = html.replace(
        "<!-- V0.84.0 方案 C · 状态条 disclosure：summary = 时效 chips + 警示计数 pill（1 行 ~36px）；\n       body = 完整警示 + dismiss checkbox。由 warning.js 维持展开态。 -->",
        "<!-- V0.85.0 · 数据时效迁移到 /data-health.html（summary = 4-chip 健康摘要）+ 警示 pill\n       由 health-summary.js 维持 60s 自动刷新 -->",
    )
    html = html.replace(
        "<!-- V0.84.0 方案 C · 状态条 disclosure（数据时效 + 警示计数合并 1 行）",
        "<!-- V0.85.0 · 数据时效迁移到 /data-health.html（summary = 4-chip 健康摘要）+ 警示 pill",
    )

    # 4. 删 freshness.js，加 health-summary.js
    html = re.sub(
        r'<script src="/static/freshness\.js"></script>\n?',
        '<script src="/static/health-summary.js"></script>\n',
        html,
    )

    return html


def main():
    changed = []
    for page in NON_HEALTH_PAGES:
        path = STATIC / page
        if not path.exists():
            print(f"[skip] not found: {page}")
            continue
        original = path.read_text(encoding="utf-8")
        new = migrate_non_health(original)
        if new != original:
            path.write_text(new, encoding="utf-8")
            changed.append(page)
            print(f"[ok] {page}: {len(original) - len(new)} bytes diff")
        else:
            print(f"[--] {page}: no change")

    # data-health.html
    path = STATIC / DATA_HEALTH_PAGE
    if path.exists():
        original = path.read_text(encoding="utf-8")
        new = migrate_data_health(original)
        if new != original:
            path.write_text(new, encoding="utf-8")
            changed.append(DATA_HEALTH_PAGE)
            print(f"[ok] {DATA_HEALTH_PAGE}: {len(original) - len(new)} bytes diff")
        else:
            print(f"[--] {DATA_HEALTH_PAGE}: no change")

    print(f"\nTotal changed: {len(changed)}")
    return 0 if changed else 1


if __name__ == "__main__":
    sys.exit(main())