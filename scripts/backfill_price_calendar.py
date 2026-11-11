#!/usr/bin/env python
"""黄金价格日历**深度回填**脚本（V0.127.0 · 金价区间预测的前置）

背景
----
生产库 ``gold_price_daily`` 的 ``ny`` 只有 **97 行**（2026-06-25 → 2026-11-06），
而「未来 20 交易日金价区间」要用**历史类比**（找波动率相近的历史日）⇒ 97 天根本不够。

但**数据源本身有 10 年**：``ak.futures_foreign_hist(symbol="GC")`` 一次调用返回
**2588 行（2016-11-14 → 今）** —— 仓库里的 provider 只是 ``df.tail(days)`` 截断了它。

⇒ 本脚本把 provider 拿到的长历史**写进价格日历**，让区间预测有底座。

⚠ **三条不可退让的约束**（都来自本项目的既有教训）

1. **只认真实行情，不认 mock。**
   ``MarketDataRepository.get_us_gold_history`` 在取数失败时会**静默降级为 mock**
   （mock 收盘价 ≈ 4500 美元区间的编造序列）。mock 写进 ``gold_price_daily``
   ⇒ 回测与区间预测都基于**编造的价格**给出看似正常的结论 —— 比「无数据」危险得多。
   ⇒ 写入前先判 ``resolve_price_source(...)`` ∈ ``TRUSTED_PRICE_SOURCES``，
   不是就**拒绝写入并退出码非 0**（沿用 ``services/backtest.py::ensure_price_calendar`` 的约束 1）。

2. **必须先看要连哪个库。**
   ``get_settings()`` 读的是 ``.env`` ⇒ **默认连开发 SQLite**，不是生产 MySQL。
   ⇒ 本脚本要求显式指定 ``--env-file``（或 ``--database-url``），
   并在**做任何事之前**把解析出来的库打印出来（脱敏）。

3. **密钥不进 argv。**
   ``DATABASE_URL`` 里含 MySQL 密码 ⇒ 用 ``--env-file .env.mysql``（0600、已 gitignore），
   脚本从文件读进 ``os.environ``，命令行上只有**文件路径**。

用法
----
::

    # ① 先干跑（默认就是干跑）：看清要连哪个库、要写多少行
    PYTHONPATH=src:. python -m scripts.backfill_price_calendar --env-file .env.mysql --target ny --deep

    # ② 备份生产库（scripts/daily_backup.sh，或手动 mysqldump）

    # ③ 真写
    PYTHONPATH=src:. python -m scripts.backfill_price_calendar --env-file .env.mysql --target ny --deep --apply

    # 开发库（.env 指向的 SQLite）同样要回填 —— 门禁与本地跑脚本都连它
    PYTHONPATH=src:. python -m scripts.backfill_price_calendar --target ny --deep --apply

幂等：按 ``(target, price_date)`` upsert ⇒ 重跑只更新，不产生重复行。
⚠ **最新一根 K 线的收盘价会被数据源盘中修订**（实测同一小时内 3994.0 → 3991.0）
⇒ 回填后隔天重跑一次是正常的，不是 bug。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# 分块写：SQLite 的绑定变量上限是 32766；MySQL 无此限制但分块同样降低单事务体积。
# 参照 repositories/macro_factor_history.py::UPSERT_CHUNK_SIZE = 1000
CHUNK_SIZE = 1000

# 深回填的默认窗口：≈10 年交易日（provider 上游实际只有 2588 行，再大也不会更多）
DEEP_DAYS = 2600

# 浅回填（与 backtest.ensure_price_calendar 的默认一致）
SHALLOW_DAYS = 90

_TARGET_FETCHERS = {
    "ny": "get_us_gold_history",
    "etf": "get_gold_history",
    "gram": "get_gold_gram_history",
}


def _redact(url: str) -> str:
    """把 URL 里的口令替换成 ``***``（打印用；**不打印完整 URL**）。"""
    if "@" not in url:
        return url
    scheme, _, rest = url.partition("://")
    creds, _, host = rest.rpartition("@")
    if ":" not in creds:
        return f"{scheme}://{creds}@{host}"
    user, _, _pwd = creds.partition(":")
    return f"{scheme}://{user}:***@{host}"


def inject_database_url(argv: list[str]) -> None:
    """把 ``DATABASE_URL`` 注入 ``os.environ``（**必须在导入 app.* 之前**）。

    ⚠ 为什么必须提前：``app.repositories.db`` 在**模块导入时**就按
    ``settings.database_url`` 建好 engine ⇒ 之后再改环境变量已经晚了
    ⇒ 脚本会连到 ``.env`` 里的开发 SQLite，而人以为连的是生产库。

    Args:
        argv: 命令行参数列表（通常是 ``sys.argv[1:]``）。
    """
    env_file: str | None = None
    db_url: str | None = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--env-file" and i + 1 < len(argv):
            env_file = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--env-file="):
            env_file = arg.split("=", 1)[1]
            i += 1
            continue
        if arg == "--database-url" and i + 1 < len(argv):
            db_url = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--database-url="):
            db_url = arg.split("=", 1)[1]
            i += 1
            continue
        i += 1

    if db_url:
        os.environ["DATABASE_URL"] = db_url
        return
    if env_file:
        path = Path(env_file)
        if not path.is_file():
            raise SystemExit(f"指定的 env 文件不存在: {path}")
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == "DATABASE_URL":
                os.environ["DATABASE_URL"] = value.strip().strip('"').strip("'")
                return
        raise SystemExit(f"env 文件里没有 DATABASE_URL: {path}")


async def _fetch_bars(repo, target: str, days: int) -> tuple[list[tuple], dict[str, str]]:
    """按 target 取 (日期, 收盘价) 序列 + 数据源状态字典。"""
    method = _TARGET_FETCHERS[target]
    fn = getattr(repo, method)
    klines = await fn(days=days)
    bars = [(k.date, float(k.close)) for k in klines]
    status = getattr(repo, "source_status", None)
    sources = status() if callable(status) else {}
    return bars, sources


def _dedupe(bars: list[tuple]) -> list[tuple]:
    """去掉重复日期（同日保留最后一次出现）并丢掉收盘价非正的条目。"""
    seen: dict = {}
    for d, c in bars:
        if c is None or c <= 0:
            continue
        seen[d] = c
    return sorted(seen.items())


async def _run(
    target: str,
    days: int,
    apply: bool,
    chunk_size: int,
) -> int:
    # ⚠ 函数内导入：保证上面的 DATABASE_URL 注入已经生效
    from app.repositories.db import async_session_factory
    from app.repositories.market_data import MarketDataRepository
    from app.repositories.review import GoldPriceRepository
    from app.services.price_source import is_trusted_price_source, resolve_price_source

    repo = MarketDataRepository()
    print(f"目标标的: {target}   窗口: 最近 {days} 个交易日   模式: {'写入' if apply else '干跑'}")
    print(f"数据源标记: {repo.source_status()}")

    bars, sources = await _fetch_bars(repo, target, days)
    bars = _dedupe(bars)
    if len(bars) < 2:
        print("❌ 取数结果不足 2 根 K 线，放弃")
        return 2

    source = resolve_price_source(sources, target)
    print(f"解析出的行情来源: {source or '（未知）'}")

    # ⚠ 约束 1：只认真实行情。mock 是降级产物，写库即污染。
    if not is_trusted_price_source(source):
        print(
            f"❌ 数据源为 {source or '未知'}（非真实行情），拒绝写入 —— "
            "mock 价格是编造的，写进价格日历会让回测/区间预测基于假数据得出看似正常的结论"
        )
        return 3

    print(f"取到 {len(bars)} 根：{bars[0][0]} → {bars[-1][0]}（末根收盘 {bars[-1][1]}）")

    async with async_session_factory() as session:
        gold = GoldPriceRepository(session)
        before = await gold.count(target)
        first_before = await gold.latest_before(target, bars[0][0])
        print(
            f"写入前：库内 {target} 共 {before} 行；本次区间起点前最近一条 = "
            f"{first_before.price_date if first_before else '（无）'}"
        )

        if not apply:
            existing_dates = {r.price_date for r in await gold.list_range(target)}
            n_new = sum(1 for d, _ in bars if d not in existing_dates)
            print(
                f"干跑结束：将写入 {len(bars)} 行"
                f"（新增 {n_new} 行 / 更新 {len(bars) - n_new} 行，区间 {bars[0][0]} → {bars[-1][0]}）"
            )
            print("加 --apply 才会真的写库")
            return 0

        written = 0
        for start in range(0, len(bars), chunk_size):
            chunk = bars[start : start + chunk_size]
            written += await gold.upsert_many(target=target, bars=chunk, source=source)
            print(f"  写入分块 {start // chunk_size + 1}: {len(chunk)} 行（累计 {written}）")

        after = await gold.count(target)
        rows = await gold.list_range(target)
        print(f"写入后：库内 {target} 共 {after} 行")
        if rows:
            print(
                f"  首行 {rows[0].price_date} close={rows[0].close} change_pct={rows[0].change_pct}"
            )
            print(
                f"  末行 {rows[-1].price_date} close={rows[-1].close} change_pct={rows[-1].change_pct}"
            )
        print(f"本次写入/更新 {written} 行")
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="黄金价格日历深度回填（V0.127.0）")
    parser.add_argument(
        "--target",
        default="ny",
        choices=sorted(_TARGET_FETCHERS),
        help="标的：ny=COMEX 纽约金（美元/盎司）、etf=518880、gram=上海金 Au99.99",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help=f"取多少个交易日；不给则 --deep 用 {DEEP_DAYS}，否则用 {SHALLOW_DAYS}",
    )
    parser.add_argument("--deep", action="store_true", help=f"深回填（最近 {DEEP_DAYS} 个交易日）")
    parser.add_argument("--apply", action="store_true", help="真的写库（默认只干跑）")
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=CHUNK_SIZE,
        help=f"分块写的大小（默认 {CHUNK_SIZE}）",
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help="从该文件读 DATABASE_URL（如 .env.mysql）；**密钥不进命令行**",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="直接指定 DATABASE_URL（⚠ 口令会进 argv / shell 历史，优先用 --env-file）",
    )
    args = parser.parse_args(argv)

    # ⚠ 必须在导入 app.* 之前完成（engine 在导入期就建好）
    inject_database_url(sys.argv[1:])

    from app.config import get_settings

    settings = get_settings()
    print(f"=== 目标数据库：{_redact(settings.database_url)} ===")

    days = args.days if args.days is not None else (DEEP_DAYS if args.deep else SHALLOW_DAYS)
    return asyncio.run(_run(args.target, days, args.apply, args.chunk_size))


if __name__ == "__main__":
    sys.exit(main())
