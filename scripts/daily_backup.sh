#!/usr/bin/env bash
# gold-etf-analyzer 每日备份（V0.126.0：SQLite / MySQL 双方言）
#
# 配套 systemd: gold-etf-analyzer-backup.service（daily 03:00）
#
# ⚠ **为什么必须分支**：生产库 V0.126.0 起正式切到 MySQL。
# 原来的实现 100% 是 SQLite 专用（``sqlite3.connect().backup()`` + ``PRAGMA integrity_check``），
# 搬到 MySQL 上会**直接报错退出** ⇒ 备份链路会静默失效（这是最坏的一种失效：
# 定时器照常「成功」，但其实一份备份都没生成）。
#
# 分支依据：``.env.prod`` 里的 ``DATABASE_URL`` 前缀。
#   sqlite://…  → 走 .backup() + PRAGMA integrity_check（行为与旧版**逐字一致**）
#   mysql://…   → 走 mysqldump --single-transaction（InnoDB 一致性快照，不停写）
#
# ⚠ **凭据不进 argv**：MySQL 分支把账号密码写进一个 0600 的临时 defaults 文件，
# 用 ``--defaults-extra-file`` 传入（该选项必须是**程序名之后的第一个选项**）。
# 密码不落在命令行（``ps`` 可见）、不落在环境变量、不进日志。
set -euo pipefail

PROJECT_DIR=${PROJECT_DIR:-/home/surui/gold-etf-analyzer}
ENV_FILE=${ENV_FILE:-$PROJECT_DIR/.env.prod}
BACKUP_DIR=${BACKUP_DIR:-$PROJECT_DIR/data/backups}
RETENTION_DAYS=${RETENTION_DAYS:-7}

mkdir -p "$BACKUP_DIR"
STAMP=$(date +%F)

# ---------------------------------------------------------------------------
# 1) 读 DATABASE_URL（从 .env.prod，不带引号，忽略注释行）
# ---------------------------------------------------------------------------
read_db_url() {
    python3 - "$ENV_FILE" <<'PY'
import sys

env_path = sys.argv[1]
url = ""
try:
    with open(env_path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            if key.strip() == "DATABASE_URL":
                url = val.strip().strip('"').strip("'")
                break
except OSError as exc:
    print(f"read env failed: {exc}", file=sys.stderr)
    sys.exit(2)

if not url:
    print(f"DATABASE_URL not found in {env_path}", file=sys.stderr)
    sys.exit(2)
print(url)
PY
}

DB_URL=$(read_db_url)
SCHEME=${DB_URL%%:*}          # mysql+asyncmy / sqlite
BASE_SCHEME=${SCHEME%%+*}     # mysql / sqlite（去掉驱动后缀）

# ---------------------------------------------------------------------------
# 2) SQLite 分支（保持旧行为逐字不变）
# ---------------------------------------------------------------------------
backup_sqlite() {
    local db_path
    db_path=$(python3 -c 'import sys,urllib.parse;print(urllib.parse.unquote(sys.argv[1].split("///",1)[-1]))' "$DB_URL")
    local out="$BACKUP_DIR/gold_etf-$STAMP.db"

    # 1) sqlite3 .backup (Python 标准库实现)
    python3 - "$db_path" "$out" <<'PY'
import sqlite3
import sys

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
    python3 - "$out" <<'PY'
import sqlite3
import sys

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

    local size
    size=$(stat -c%s "$out")
    echo "backup ok: $out (${size} bytes, retention=${RETENTION_DAYS}d)"
}

# ---------------------------------------------------------------------------
# 3) MySQL 分支
# ---------------------------------------------------------------------------
backup_mysql() {
    local out="$BACKUP_DIR/gold_etf-$STAMP.sql.gz"
    local cnf
    cnf=$(mktemp /tmp/gold-etf-mysql-XXXXXX.cnf)
    # shellcheck disable=SC2064
    trap "rm -f '$cnf'" EXIT

    # 把 URL 拆成 my.cnf 字段（含端口/库名），密码不进 argv
    local db_name
    db_name=$(python3 - "$DB_URL" "$cnf" <<'PY'
import os
import sys
import urllib.parse

url, path = sys.argv[1], sys.argv[2]
parsed = urllib.parse.urlsplit(url.replace("mysql+asyncmy://", "mysql://", 1))
query = urllib.parse.parse_qs(parsed.query)
host = parsed.hostname or "127.0.0.1"
port = parsed.port or 3306
db = (parsed.path or "/").lstrip("/").split("?", 1)[0]
user = urllib.parse.unquote(parsed.username or "")
pw = urllib.parse.unquote(parsed.password or "")
if not db:
    print("DATABASE_URL 缺少库名", file=sys.stderr)
    sys.exit(2)
charset = (query.get("charset") or ["utf8mb4"])[0]

with open(path, "w", encoding="utf-8") as fh:
    fh.write("[client]\n")
    fh.write(f"host={host}\n")
    fh.write(f"port={port}\n")
    fh.write(f"user={user}\n")
    fh.write(f"password={pw}\n")
    fh.write(f"default-character-set={charset}\n")
os.chmod(path, 0o600)
print(db)
PY
)

    # 备份本体：
    #   --single-transaction  InnoDB 一致性快照（**不停写** ⇒ 业务无感）
    #   --no-tablespaces      不查 tablespace（应用账号没有 PROCESS 权限）
    #   --tz-utc              会话时区钉在 UTC（与生产连接层 init_command 一致）
    mysqldump --defaults-extra-file="$cnf" \
        --single-transaction --quick \
        --routines --triggers --events \
        --default-character-set=utf8mb4 \
        --hex-blob --no-tablespaces --tz-utc \
        --set-gtid-purged=OFF \
        "$db_name" | gzip -c > "$out"

    # 校验 1：gzip 流完整
    gzip -t "$out"

    # 校验 2：dump 里的 CREATE TABLE 数 == 库里真实的表数
    #（防止「mysqldump 静默跳过了一半表」——那是最阴的备份损坏）
    local expect_tables dumped_tables
    expect_tables=$(mysql --defaults-extra-file="$cnf" --batch --skip-column-names \
        -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='${db_name}';")
    dumped_tables=$(zcat "$out" | grep -c '^CREATE TABLE' || true)
    if [ "$expect_tables" != "$dumped_tables" ]; then
        echo "backup FAILED: dump has ${dumped_tables} CREATE TABLE, db has ${expect_tables}" >&2
        exit 1
    fi

    # 清理超出保留期的旧备份
    find "$BACKUP_DIR" -maxdepth 1 -name 'gold_etf-*.sql.gz' -mtime +"$RETENTION_DAYS" -delete

    local size
    size=$(stat -c%s "$out")
    echo "backup ok: $out (${size} bytes, tables=${dumped_tables}, retention=${RETENTION_DAYS}d)"
}

case "$BASE_SCHEME" in
    sqlite)
        backup_sqlite
        ;;
    mysql|mariadb)
        backup_mysql
        ;;
    *)
        echo "unsupported DATABASE_URL scheme: ${SCHEME}" >&2
        exit 2
        ;;
esac
