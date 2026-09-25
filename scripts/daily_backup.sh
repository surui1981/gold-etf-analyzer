#!/usr/bin/env bash
# gold-etf-analyzer SQLite daily backup
# 配套 systemd: gold-etf-analyzer-backup.service
# 调 python sqlite3 模块做 .backup() + PRAGMA integrity_check
set -euo pipefail

PROJECT_DIR=${PROJECT_DIR:-/home/surui/gold-etf-analyzer}
DB_PATH=${DB_PATH:-$PROJECT_DIR/data/gold_etf.db}
BACKUP_DIR=${BACKUP_DIR:-$PROJECT_DIR/data/backups}
RETENTION_DAYS=${RETENTION_DAYS:-7}

mkdir -p "$BACKUP_DIR"
STAMP=$(date +%F)
OUT="$BACKUP_DIR/gold_etf-$STAMP.db"

# 1) sqlite3 .backup (Python 标准库实现)
python3 - "$DB_PATH" "$OUT" <<'PY'
import sys, sqlite3
src, dst = sys.argv[1], sys.argv[2]
sc = sqlite3.connect(src)
dc = sqlite3.connect(dst)
try:
    sc.backup(dc)
finally:
    dc.close()
    sc.close()
PY

# 2) 校验完整性 (防止备份源已损坏)
python3 - "$OUT" <<'PY'
import sys, sqlite3
out = sys.argv[1]
c = sqlite3.connect(out)
try:
    ok = c.execute("PRAGMA integrity_check").fetchone()[0]
finally:
    c.close()
assert ok == "ok", f"backup corrupt: {ok}"
print("integrity_check ok")
PY

# 3) 清理超出保留期的旧备份
find "$BACKUP_DIR" -maxdepth 1 -name 'gold_etf-*.db' -mtime +"$RETENTION_DAYS" -delete

SIZE=$(stat -c%s "$OUT")
echo "backup ok: $OUT (${SIZE} bytes, retention=${RETENTION_DAYS}d)"