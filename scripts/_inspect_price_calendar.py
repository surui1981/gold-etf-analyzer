#!/usr/bin/env python
"""只读检查 gold_price_daily 的覆盖情况（B1 价格日历增量补齐的设计依据）。"""

import sqlite3
from datetime import date, timedelta

DB = "data/gold_etf.db"
today = date.today()

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
cur = con.cursor()

print(f"今天 = {today}")
print()
print(f"{'target':<12}{'行数':>6}{'最早':>14}{'最晚':>14}{'落后天数':>10}{'近90天行数':>12}")
for (target,) in cur.execute(
    "SELECT DISTINCT target FROM gold_price_daily ORDER BY target"
).fetchall():
    row = cur.execute(
        "SELECT COUNT(*), MIN(price_date), MAX(price_date) FROM gold_price_daily WHERE target=?",
        (target,),
    ).fetchone()
    n, lo, hi = row
    lag = (today - date.fromisoformat(hi)).days if hi else None
    in90 = cur.execute(
        "SELECT COUNT(*) FROM gold_price_daily WHERE target=? AND price_date >= ?",
        (target, (today - timedelta(days=90)).isoformat()),
    ).fetchone()[0]
    print(f"{target:<12}{n:>6}{lo!s:>14}{hi!s:>14}{lag!s:>10}{in90:>12}")

print()
print("各 target 的最近 6 行（看尾部是否有洞）：")
for (target,) in cur.execute(
    "SELECT DISTINCT target FROM gold_price_daily ORDER BY target"
).fetchall():
    rows = cur.execute(
        "SELECT price_date, close FROM gold_price_daily WHERE target=? ORDER BY price_date DESC LIMIT 6",
        (target,),
    ).fetchall()
    print(f"  {target}: {[(d, c) for d, c in rows]}")
con.close()
