#!/usr/bin/env bash
# V0.126.0 · 生产库回滚：MySQL → SQLite
#
# ⚠ 什么时候用：切库后生产服务起不来、或数据核对不过 —— 停服务 → 把
#   ``.env.prod`` 的 ``DATABASE_URL`` 改回 SQLite → 用切库前的备份覆盖
#   ``data/gold_etf.db`` → 起服务。
#   **MySQL 侧的数据不会被动**（还在那儿）；确认要回 MySQL 时重跑
#   ``scripts/migrate_sqlite_to_mysql.py --apply`` 即可。
#
# ⚠ 回滚**不 bump 版本**：代码层两个方言都支持，回滚只是改一行配置 + 换库文件。
#
# 用法：bash scripts/rollback_to_sqlite.sh [备份文件路径]
#       不给参数就用最新的 cutover 备份（data/backups/gold_etf-cutover-*.db）。
#
# 前置：备份必须存在（切库时已生成）。
set -euo pipefail
cd "$(dirname "$0")/.."

BACKUP=${1:-}
if [ -z "$BACKUP" ]; then
    BACKUP=$(ls -1t data/backups/gold_etf-cutover-*.db 2>/dev/null | head -1)
fi
if [ -z "$BACKUP" ] || [ ! -f "$BACKUP" ]; then
    echo "找不到 cutover 备份，请显式给路径" >&2
    exit 1
fi
echo "回滚用的备份：$BACKUP"

echo "== 1) 停服务 =="
sudo systemctl stop gold-etf-analyzer.service

echo "== 2) .env.prod 切回 SQLite =="
python3 - <<'PY'
from pathlib import Path

p = Path(".env.prod")
lines = p.read_text(encoding="utf-8").splitlines()
out, hit = [], False
for line in lines:
    if line.startswith("DATABASE_URL="):
        out.append("DATABASE_URL=sqlite+aiosqlite:///./data/gold_etf.db")
        hit = True
    else:
        out.append(line)
assert hit, ".env.prod 里没有 DATABASE_URL 行"
p.write_text("\n".join(out) + "\n", encoding="utf-8")
print("已切回 SQLite")
PY

echo "== 3) 恢复库文件（保留现库为 .before-rollback）===="
if [ -f data/gold_etf.db ]; then
    mv data/gold_etf.db "data/gold_etf.db.before-rollback-$(date +%Y%m%d-%H%M%S)"
    rm -f data/gold_etf.db-wal data/gold_etf.db-shm
fi
cp "$BACKUP" data/gold_etf.db

echo "== 4) 起服务 =="
sudo systemctl start gold-etf-analyzer.service
sleep 6
curl -fsS -m 5 http://127.0.0.1:8888/api/v1/health && echo " <- health OK"
echo "⚠ MySQL 侧的数据**没动**（还在那儿）；切回 MySQL 重跑迁移脚本即可。"
