"""V0.109.0 全量重分类 sweep（历史行跟随新分类逻辑）

为什么需要
----------
V0.107.1 / V0.108.0 / V0.109.0 三次都改了 ``classify()`` 的行为，但
``news_feed_items`` 里已有的行仍带旧分类 —— ``upsert_bulk`` 遵循
「已分类行不变更」纪律，所以**只有新抓的条目**用新逻辑。

实测生产 DB 576 条里 30 条分类已过时（财经→科技 28 等）。

与 ``reclassify_v01071.py`` 的区别
---------------------------------
- v01071 版只扫 ``category='其他'`` 的行 —— 修 V0.107.1「弱词典导致大量
  落其他」的问题
- 本版扫**所有行**，因为 V0.109.0 的 ``PE ⊂ Europe`` 误判把 28 条科技新闻
  判成了财经，那些行的 category 是「财经」，v01071 版永远碰不到

安全设计
--------
- **默认 dry-run**：只打印将要发生的变更，不写库
- ``--apply`` 才真正执行
- ``--drop-blocklisted`` 额外删除黑名单站点的行（V0.108.0 起不入库的
  新浪科技 / maomu.com 存量行）；不带这个开关则只改分类不删行
- 完成后 rebuild 所有受影响日期的 ``news_feed_daily``

用法
----
  # 1. 先看会发生什么（不写库）
  PYTHONPATH=src:. .venv/bin/python scripts/reclassify_v01090.py

  # 2. 确认无误后执行（只改分类）
  PYTHONPATH=src:. .venv/bin/python scripts/reclassify_v01090.py --apply

  # 3. 连同黑名单站点存量行一起清理
  PYTHONPATH=src:. .venv/bin/python scripts/reclassify_v01090.py --apply --drop-blocklisted
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta, timezone

sys.path.insert(0, "src")

from sqlalchemy import delete, select, update  # noqa: E402

from app.models.news_feed import NewsFeedItem  # noqa: E402
from app.repositories.db import async_session_factory  # noqa: E402
from app.repositories.news_classifier import classify  # noqa: E402
from app.repositories.news_feed import NewsFeedRepository  # noqa: E402
from app.repositories.readhub_fetcher import SITE_BLOCKLIST  # noqa: E402
from app.services.news_feed import NewsFeedService  # noqa: E402

BJT = timezone(timedelta(hours=8))
_MAX_SAMPLE = 15


async def main() -> int:
    ap = argparse.ArgumentParser(description="V0.109.0 全量重分类 sweep")
    ap.add_argument(
        "--apply",
        action="store_true",
        help="真正写库；不带则只 dry-run 打印变更预览",
    )
    ap.add_argument(
        "--drop-blocklisted",
        action="store_true",
        help="额外删除黑名单站点的存量行（新浪科技 / maomu.com）",
    )
    args = ap.parse_args()

    today = datetime_now_bjt_date()
    mode = "APPLY" if args.apply else "DRY-RUN（不带 --apply 不写库）"
    print("=" * 72)
    print(f"V0.109.0 全量重分类 sweep · {mode}")
    print(f"今天 (BJT): {today}")
    print("=" * 72)

    async with async_session_factory() as session:
        # ── Step 1: 拉全量行 ──
        print("\n[1] 拉全量 news_feed_items ...")
        rows = (
            await session.execute(select(NewsFeedItem))
        ).scalars().all()
        print(f"  共 {len(rows)} 行")

        # ── Step 2: 重算分类 ──
        print("\n[2] 用 V0.109.0 classify() 重算每行 ...")
        to_update: list[tuple[int, str, str, str]] = []  # (id, old, new, title)
        transitions: dict[tuple[str, str], int] = Counter()
        to_other = 0
        for row in rows:
            new_cat = classify(
                row.title or "", row.summary or "", row.site_name or ""
            )
            old_cat = row.category or "其他"
            if new_cat == old_cat:
                continue
            transitions[(old_cat, new_cat)] += 1
            if new_cat == "其他":
                to_other += 1
            to_update.append((row.id, old_cat, new_cat, row.title or ""))

        print(f"  分类会变的: {len(to_update)} 行"
              f"（其中 {to_other} 行将落入「其他」）")
        if transitions:
            print("\n  流转明细（修复前 → 修复后）:")
            for (o, n), c in transitions.most_common():
                mark = " →" if o != n else "  "
                print(f"    {mark} {o:4s} → {n:4s}: {c:4d}")

        # ── Step 3: 黑名单站点存量行 ──
        blocked_rows = [r for r in rows if (r.site_name or "") in SITE_BLOCKLIST]
        if args.drop_blocklisted:
            by_site = Counter(r.site_name for r in blocked_rows)
            print(f"\n[3] 黑名单站点存量行: {len(blocked_rows)} 行，将删除")
            for site, c in by_site.most_common():
                print(f"    {site}: {c}")
        else:
            by_site = Counter(r.site_name for r in blocked_rows)
            print(f"\n[3] 黑名单站点存量行: {len(blocked_rows)} 行"
                  f"（未加 --drop-blocklisted，保留）")
            for site, c in by_site.most_common():
                print(f"    {site}: {c}")

        # ── Step 4: 预览样例 ──
        if to_update:
            print(f"\n[4] 变更样例（前 {_MAX_SAMPLE} 条）:")
            for row_id, o, n, title in to_update[:_MAX_SAMPLE]:
                print(f"    [{o:4s} → {n:4s}] {title[:44]}")
            if len(to_update) > _MAX_SAMPLE:
                print(f"    ... 另有 {len(to_update) - _MAX_SAMPLE} 条")

        if not args.apply:
            print("\n" + "=" * 72)
            print("DRY-RUN 结束，未写库。确认无误后加 --apply 重跑。")
            print("=" * 72)
            return 0

        # ── Step 5: 写库 ──
        print(f"\n[5] 写库: UPDATE {len(to_update)} 行 ...")
        if to_update:
            for row_id, _o, new_cat, _t in to_update:
                await session.execute(
                    update(NewsFeedItem)
                    .where(NewsFeedItem.id == row_id)
                    .values(category=new_cat)
                )
            await session.commit()
            print(f"  ✅ 已提交 {len(to_update)} 行 UPDATE")

        if args.drop_blocklisted and blocked_rows:
            print(f"\n[6] 删除黑名单站点 {len(blocked_rows)} 行 ...")
            await session.execute(
                delete(NewsFeedItem).where(
                    NewsFeedItem.site_name.in_(tuple(SITE_BLOCKLIST))
                )
            )
            await session.commit()
            print(f"  ✅ 已删除 {len(blocked_rows)} 行")

        # ── Step 7: 重建受影响日期的 daily ──
        affected: set[date] = set()
        for r in rows:
            affected.add(r.publish_date.date())
        print(f"\n[7] 重建受影响日期的 news_feed_daily（共 {len(affected)} 天）...")

    # 上一轮 session 已 commit，重新开干净 session 让 daily 看到新数据
    async with async_session_factory() as session:
        repo = NewsFeedRepository(session)
        svc = NewsFeedService(repo)
        ok = fail = 0
        for d in sorted(affected):
            try:
                rebuilt = await svc.rebuild_daily(d)
            except Exception as exc:  # 单日失败不阻断整批
                fail += 1
                print(f"  ⚠️  {d} 重建失败: {exc}")
                continue
            if rebuilt is None:
                ok += 1
                continue
            ok += 1
            print(
                f"  ✅ {d} total={rebuilt.total_count} "
                f"财经={rebuilt.finance_count} 科技={rebuilt.tech_count} "
                f"创投={rebuilt.vc_count} 商业={rebuilt.biz_count} "
                f"其他={rebuilt.other_count}"
            )
        await session.commit()

    print("\n" + "=" * 72)
    print(f"✅ V0.109.0 sweep 完成：更新 {len(to_update)} 行，"
          f"重建 {ok} 天 daily" + (f"（{fail} 天失败）" if fail else ""))
    print("=" * 72)
    return 0


def datetime_now_bjt_date() -> date:
    from datetime import datetime

    return datetime.now(BJT).date()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))