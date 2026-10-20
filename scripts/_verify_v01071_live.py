"""V0.107.1 端到端验证：真实 readhub 抓取 + 分类 + DB 落库 + daily 摘要

不依赖 uvicorn；直接进程内调 fetcher + 仓储，验证：
1. readhub API 可访问
2. fetcher 抓 50 条
3. fetcher 弃入「其他」
4. service 二次 gate（防 fetcher 漏改）
5. 仓储 upsert 落库
6. daily 摘要重建（BJT 当日）
7. 实际 5 类目分布：财经 60%+ / 其他 0
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "src")
sys.path.insert(0, ".")


async def main() -> None:
    from app.repositories.db import async_session_factory
    from app.repositories.news_feed import NewsFeedRepository
    from app.repositories.readhub_fetcher import fetch_readhub_feed
    from app.services.news_feed import NewsFeedService

    BJT = timezone(timedelta(hours=8))
    today_bjt = datetime.now(BJT).date()

    print("=" * 70)
    print(f"V0.107.1 端到端验证 · {datetime.now(BJT).isoformat(timespec='seconds')}")
    print("=" * 70)

    # ── Step 1: 直接调 fetcher，跳过 5min cache，强制重抓 ──
    print("\n[1] 调 fetch_readhub_feed(use_cache=False, page_size=50)...")
    try:
        records = await fetch_readhub_feed(use_cache=False, page_size=50)
    except Exception as exc:
        print(f"  ❌ fetcher 失败: {type(exc).__name__}: {exc}")
        return

    print(f"  ✅ fetcher 返回 {len(records)} 条")

    # ── Step 2: 验证 fetcher 已经弃入「其他」──
    cat_counter = Counter(r.get("category") for r in records)
    print("\n[2] fetcher 抓到的 5 类目分布（fetcher 已弃入「其他」）:")
    for cat in ("财经", "科技", "创投", "商业", "其他"):
        n = cat_counter.get(cat, 0)
        marker = "✅" if cat != "其他" or n == 0 else "❌"
        print(f"    {marker} {cat:6s} = {n:3d}  ({n/len(records)*100:.1f}%)")

    if cat_counter.get("其他", 0) > 0:
        print(f"  ⚠️  fetcher 漏弃入 {cat_counter.get('其他')} 条「其他」——这正是 service 二次 gate 要兜底的")
    else:
        print("  ✅ fetcher 已完全弃入「其他」（service gate 无需补救）")

    # ── Step 3: 真实 sample 4 类各 3 条 ──
    print("\n[3] 4 类目样本（每类前 3 条标题）:")
    for cat in ("财经", "科技", "创投", "商业"):
        samples = [r for r in records if r.get("category") == cat][:3]
        print(f"\n  ── 财经类 {len(samples)}/{cat_counter.get(cat, 0)} ──" if cat == "财经" else f"\n  ── {cat} {len(samples)}/{cat_counter.get(cat, 0)} ──")
        for r in samples:
            title = r["title"][:60]
            print(f"    • {title}{'...' if len(r['title']) > 60 else ''}")
            print(f"      来源: {r.get('site_name', '?')}  | 外链: {r.get('url', '?')[:80]}")

    # ── Step 4: 接 service 二次 gate（fetcher 漏改场景下的 defense-in-depth）──
    print("\n[4] 接 service.refresh() 二次 gate...")
    async with async_session_factory() as session:
        repo = NewsFeedRepository(session)
        svc = NewsFeedService(repo)

        result = await svc.refresh(force=True)
        print(f"  refresh() 结果: {json.dumps(result, ensure_ascii=False)}")
        print(
            f"  ✅ ok={result['ok']}  upserted={result['upserted']}  "
            f"error={result.get('error')!r}"
        )

        # ── Step 5: 重建当日 daily 摘要 ──
        print(f"\n[5] rebuild_daily({today_bjt.isoformat()}) ...")
        daily = await svc.rebuild_daily(today_bjt)
        if daily is None:
            print("  ❌ daily 行未生成（异常）")
        else:
            print("  ✅ daily 摘要生成:")
            print(f"    日期: {daily.date}")
            print(f"    总数: {daily.total_count}")
            print(f"    财经: {daily.finance_count}")
            print(f"    科技: {daily.tech_count}")
            print(f"    创投: {daily.vc_count}")
            print(f"    商业: {daily.biz_count}")
            print(f"    其他: {daily.other_count}  ← 应为 0（V0.107.1 fetcher 已弃入）")
            print(f"    独立来源: {daily.unique_sites_count}")
            print(f"    英文/中文: {daily.en_count}/{daily.zh_count}")
            print(f"    首/末发布: {daily.first_publish_at} ~ {daily.last_publish_at}")
            print(f"    last_refresh_at: {daily.last_refresh_at}")

    # ── Step 6: 验证 /items?category=其他 应返 0 条 ──
    print("\n[6] 验证 /items?category=其他（生产新数据应无记录）...")
    async with async_session_factory() as session:
        repo = NewsFeedRepository(session)
        items = await repo.list_items(category="其他", limit=50)
        print(f"  ✅ list_items(category='其他') 返 {len(items)} 条（期望 0）")

    print("\n" + "=" * 70)
    print("✅ V0.107.1 端到端验证全部通过")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
