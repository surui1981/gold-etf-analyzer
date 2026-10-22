"""COMEX 黄金库存导入脚本（CLI）。

用法::

    python -m app.scripts.import_gold_inventory --dry-run                 # 只抓不落库
    python -m app.scripts.import_gold_inventory                          # 全量 upsert

实现：``fetch_comex_inventory()``（子进程隔离 AKShare）→ upsert 到
``gold_inventory_daily`` 表。全量约 1230 行，upsert 按 ``inv_date`` 去重，
重复执行安全（行数不变，见 V0.115.0 验证脚本的幂等断言）。
"""

import argparse
import asyncio

from app.models.base import Base
from app.repositories.db import async_session_factory, engine
from app.repositories.gold_inventory import GoldInventoryRepository
from app.repositories.gold_inventory_data import fetch_comex_inventory
from app.services.gold_inventory import GoldInventoryService
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def run_import() -> int:
    """抓 COMEX 库存全量并落库。

    Returns:
        upserted 行数；源不可用返回 0。可被 CLI 与 scheduler 共用。
    """
    # 确保表存在（首次运行 / alembic 未跑到时兜底）
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as session:
        return await GoldInventoryService(repo=GoldInventoryRepository(session)).refresh()


async def main() -> None:
    parser = argparse.ArgumentParser(description="抓 COMEX 黄金库存 → gold_inventory_daily 表")
    parser.add_argument("--dry-run", action="store_true", help="只抓不落库")
    args = parser.parse_args()

    if args.dry_run:
        points = await asyncio.to_thread(fetch_comex_inventory)
        print(f"dry-run: {len(points)} 点，{points[0].inv_date} -> {points[-1].inv_date}")
        print(f"  最新 {points[-1].inv_date}: {points[-1].tonnes:.2f} 吨")
        if len(points) >= 22:
            base = points[-22]
            pct = (points[-1].tonnes - base.tonnes) / base.tonnes * 100
            print(f"  近 1 月（回看 {len(points) - 22} 个点）: {pct:+.2f}%")
        return

    logger.info("开始导入 COMEX 黄金库存")
    n = await run_import()
    print(f"导入完成：{n} 行")


if __name__ == "__main__":
    asyncio.run(main())