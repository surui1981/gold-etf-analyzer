"""央行购金数据导入脚本（CLI）。

用法::

    python -m app.scripts.import_central_bank --since 2020-01           # 默认全量导入
    python -m app.scripts.import_central_bank --since 2025-01           # 仅补最近 1 年
    python -m app.scripts.import_central_bank --dry-run                 # 只打印，不落库

实现：调用 ``build_full_dataset()`` → upsert 到 ``central_bank_purchases`` 表。
"""

import argparse
import asyncio
import sys
from collections import Counter

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models.base import Base
from app.repositories.central_bank_data import QuarterlyPurchase, build_full_dataset
from app.repositories.db import async_session_factory, engine
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def upsert_rows(rows: list[QuarterlyPurchase]) -> int:
    """upsert 写入；返回受影响行数。"""
    from app.models.central_bank import CentralBankPurchase

    if not rows:
        return 0

    payload = [
        {
            "country_iso": r.country_iso,
            "country_name": r.country_name,
            "quarter": r.quarter,
            "tonnes_net": r.tonnes_net,
            "source": r.source,
            "data_date": r.data_date,
        }
        for r in rows
    ]

    async with async_session_factory() as session, session.begin():
        stmt = sqlite_insert(CentralBankPurchase).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=["country_iso", "quarter"],
            set_={
                "country_name": stmt.excluded.country_name,
                "tonnes_net": stmt.excluded.tonnes_net,
                "source": stmt.excluded.source,
                "data_date": stmt.excluded.data_date,
            },
        )
        result = await session.execute(stmt)
        return result.rowcount or 0


async def run_import(include_manual: bool = True) -> int:
    """执行完整导入流程（拉 WGC + 手工补丁 + 落库）。

    Returns:
        upserted 行数；网络异常或空数据返回 0。
    可被 CLI 和 scheduler 共用。
    """
    rows = await build_full_dataset()
    if not include_manual:
        rows = [r for r in rows if r.source != "WGC 月报估读"]

    if not rows:
        logger.error("未获取到任何数据；请检查 WGC fsapi 可达性")
        return 0

    # 确保表存在（首次运行无 alembic 时兜底）
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    n = await upsert_rows(rows)
    logger.info(
        "导入完成：%d 行（countries=%d, sources=%s）",
        n,
        len({r.country_iso for r in rows}),
        dict(Counter(r.source for r in rows)),
    )
    return n


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="导入 WGC GDT HTML + 手工补丁 → central_bank_purchases 表"
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印，不落库")
    parser.add_argument("--no-manual", action="store_true", help="跳过 UZB/IRN 手工补丁")
    args = parser.parse_args()

    logger.info("开始导入央行购金数据：dry_run=%s", args.dry_run)
    rows = await build_full_dataset()
    if args.no_manual:
        rows = [r for r in rows if r.source != "WGC 月报估读"]

    if not rows:
        logger.error("未获取到任何数据；请检查 WGC fsapi 可达性")
        sys.exit(2)

    # 统计
    country_count = len({r.country_iso for r in rows})
    quarter_set = sorted({r.quarter for r in rows})
    source_counter = Counter(r.source for r in rows)
    print(f"[import] rows={len(rows)} countries={country_count}")
    print(
        f"[import] quarter range: {quarter_set[0]} → {quarter_set[-1]} ({len(quarter_set)} quarters)"
    )
    print(f"[import] sources: {dict(source_counter)}")

    # Top 5 buyer preview (T12M = 最近 4 个季度合计)
    last4 = quarter_set[-4:]
    top = Counter()
    for r in rows:
        if r.quarter in last4:
            top[r.country_iso] += r.tonnes_net
    print(f"[import] T12M top buyers: {top.most_common(5)}")

    if args.dry_run:
        print("[import] dry-run，未落库")
        return

    n = await run_import(include_manual=not args.no_manual)
    print(f"[import] upserted {n} rows into central_bank_purchases")


if __name__ == "__main__":
    asyncio.run(main())
