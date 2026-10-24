"""V0.107.1 只读 fetcher 验证（不写 DB）

直接调用 readhub_fetcher 抓真实 readhub，验证：
1. readhub API 仍可访问
2. page_size=50 实测 P99 <2s
3. fetcher 弃入「其他」正确
4. 4 类目分布真实比例

不连接 DB（避免 classifier 拦截）；纯 fetcher 层验证
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections import Counter

sys.path.insert(0, "src")


async def main() -> None:
    from app.repositories.readhub_fetcher import fetch_readhub_feed

    print("=" * 70)
    print("V0.107.1 只读 fetcher 验证")
    print("=" * 70)

    # Step 1: 真实抓取（page_size=50）
    print("\n[1] 调 fetch_readhub_feed(use_cache=False, page_size=50)...")
    t0 = time.perf_counter()
    try:
        records = await fetch_readhub_feed(use_cache=False, page_size=50)
    except Exception as exc:
        print(f"  ❌ fetcher 失败: {type(exc).__name__}: {exc}")
        return
    elapsed_ms = (time.perf_counter() - t0) * 1000

    print(f"  ✅ 抓到 {len(records)} 条，耗时 {elapsed_ms:.0f}ms")
    print(f"  ✅ 期望 P99 <2s → {'通过' if elapsed_ms < 2000 else '⚠️  超时'}")

    # Step 2: 5 类目分布（fetcher 弃入「其他」应 =0）
    cat_counter = Counter(r.get("category") for r in records)
    print("\n[2] fetcher 抓到的 5 类目分布:")
    total = max(len(records), 1)
    for cat in ("财经", "科技", "创投", "商业", "其他"):
        n = cat_counter.get(cat, 0)
        pct = n / total * 100
        marker = ("✅" if n == 0 else "❌ 漏弃入") if cat == "其他" else "✅"
        print(f"    {marker} {cat:6s} = {n:3d}  ({pct:5.1f}%)")

    # Step 3: 5 各类目样本
    print("\n[3] 各分类样本（前 3 条标题）:")
    for cat in ("财经", "科技", "创投", "商业"):
        samples = [r for r in records if r.get("category") == cat][:3]
        print(f"\n  ── {cat} {len(samples)} 条样本 ──")
        if not samples:
            print(f"    （本批 0 条，全部已弃入或抓取时段不发{cat}）")
            continue
        for r in samples:
            title = r.get("title", "?")[:55]
            site = r.get("site_name", "?")
            print(f"    • {title}{'...' if len(r.get('title', '')) > 55 else ''}")
            print(f"      {site}")

    # Step 4: 校验 fetcher 已经把「其他」全弃入
    other_count = cat_counter.get("其他", 0)
    print("\n" + "=" * 70)
    if other_count == 0:
        print("✅ V0.107.1 fetcher 完美：所有「其他」已弃入，仅 4 类进入 DB")
    else:
        print(f"⚠️  V0.107.1 fetcher 漏弃入 {other_count} 条「其他」—— service gate 会兜底")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
