#!/usr/bin/env bash
# gold-etf-analyzer 每日备份（V0.126.0：SQLite / MySQL 双方言）
#
# 配套 systemd: gold-etf-analyzer-backup.service（daily 03:00，Persistent=true）
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
#
# ── V0.126.0 补修（2026-11-12 实测发现的两个真缺陷）────────────────────────
# ① **等 MySQL 起来**：timer 带 ``Persistent=true`` ⇒ 关机跨过 03:00 时，
#    **开机那一刻**就会补跑 —— 而此时 mysqld 往往还没接受连接
#    （2026-11-12 实测：04:23:59 开机、04:24:00 补跑 ⇒
#    ``mysqldump: Can't connect to MySQL server on '127.0.0.1:3306' (111)``）。
#    ⇒ 加 ``wait_for_mysql()``：连不上就重试（默认 30 × 2s = 60s）。
# ② **原子写**：旧写法 ``mysqldump … | gzip -c > "$out"`` 在 mysqldump 失败时
#    **已经把（空）文件创建出来了** ⇒ 目录里留下一个 20 字节的 .sql.gz，
#    **看起来像备份、其实啥也不是**（实测：当天真备份没生成，坏文件却躺在那儿）。
#    ⇒ 改成「先写临时文件 → 校验 → 再 ``mv`` 就位」；失败则**不留任何文件**。
set -euo pipefail

PROJECT_DIR=${PROJECT_DIR:-/home/surui/gold-etf-analyzer}
ENV_FILE=${ENV_FILE:-$PROJECT_DIR/.env.prod}
BACKUP_DIR=${BACKUP_DIR:-$PROJECT_DIR/data/backups}
RETENTION_DAYS=${RETENTION_DAYS:-7}
# 等 MySQL 接受连接：次数 × 间隔（秒）
MYSQL_WAIT_TRIES=${MYSQL_WAIT_TRIES:-30}
MYSQL_WAIT_INTERVAL=${MYSQL_WAIT_INTERVAL:-2}

mkdir -p "$BACKUP_DIR"
STAMP=$(date +%F)

# 临时文件统一登记，退出时清干净（不留半截文件在备份目录里）
TMP_FILES=()
cleanup() {
    local f
    for f in "${TMP_FILES[@]:-}"; do
        [ -n "$f" ] && rm -f "$f"
    done
}
trap cleanup EXIT

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
# 2) SQLite 分支（保持旧行为逐字不变，只把「写文件」换成原子写）
# ---------------------------------------------------------------------------
backup_sqlite() {
    local db_path
    db_path=$(python3 -c 'import sys,urllib.parse;print(urllib.parse.unquote(sys.argv[1].split("///",1)[-1]))' "$DB_URL")
    local out="$BACKUP_DIR/gold_etf-$STAMP.db"
    local tmp="$BACKUP_DIR/.tmp-gold_etf-$STAMP-$$.db"
    TMP_FILES+=("$tmp")

    # 1) sqlite3 .backup (Python 标准库实现)
    python3 - "$db_path" "$tmp" <<'PY'
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
    python3 - "$tmp" <<'PY'
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

    # 3) 校验通过才就位（原子写：坏文件绝不留在备份目录里）
    mv -f "$tmp" "$out"

    # 4) 清理超出保留期的旧备份
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
    local tmp="$BACKUP_DIR/.tmp-gold_etf-$STAMP-$$.sql.gz"
    local cnf
    cnf=$(mktemp /tmp/gold-etf-mysql-XXXXXX.cnf)
    TMP_FILES+=("$cnf" "$tmp")

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

    # ── ① 等 MySQL 接受连接（开机补跑时 mysqld 常常还没起来）──
    if ! wait_for_mysql "$cnf"; then
        echo "backup FAILED: MySQL 在 ${MYSQL_WAIT_TRIES}×${MYSQL_WAIT_INTERVAL}s 内没接受连接（不开备份文件）" >&2
        exit 1
    fi

    # ── ② 备份本体（写临时文件，校验通过才 mv 就位）──
    #   --single-transaction  InnoDB 一致性快照（**不停写** ⇒ 业务无感）
    #   --no-tablespaces      不查 tablespace（应用账号没有 PROCESS 权限）
    #   --tz-utc              会话时区钉在 UTC（与生产连接层 init_command 一致）
    mysqldump --defaults-extra-file="$cnf" \
        --single-transaction --quick \
        --routines --triggers --events \
        --default-character-set=utf8mb4 \
        --hex-blob --no-tablespaces --tz-utc \
        --set-gtid-purged=OFF \
        "$db_name" | gzip -c > "$tmp"

    # 校验 1：gzip 流完整
    gzip -t "$tmp"

    # 校验 2：dump 里的 CREATE TABLE 数 == 库里真实的表数
    #（防止「mysqldump 静默跳过了一半表」——那是最阴的备份损坏）
    local expect_tables dumped_tables
    expect_tables=$(mysql --defaults-extra-file="$cnf" --batch --skip-column-names \
        -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='${db_name}';")
    dumped_tables=$(zcat "$tmp" | grep -c '^CREATE TABLE' || true)
    if [ "$expect_tables" != "$dumped_tables" ]; then
        echo "backup FAILED: dump has ${dumped_tables} CREATE TABLE, db has ${expect_tables}" >&2
        exit 1
    fi

    # 校验通过才就位（原子写）—— 失败时目录里**不会**留下半个备份
    mv -f "$tmp" "$out"

    # 清理超出保留期的旧备份
    find "$BACKUP_DIR" -maxdepth 1 -name 'gold_etf-*.sql.gz' -mtime +"$RETENTION_DAYS" -delete

    local size
    size=$(stat -c%s "$out")
    echo "backup ok: $out (${size} bytes, tables=${dumped_tables}, retention=${RETENTION_DAYS}d)"
}

# 等 MySQL 接受连接：成功返回 0，超时返回 1。
# ⚠ 2026-11-12 实测：机器重启后 timer 会**立刻**补跑（Persistent=true），
#   而 mysqld 往往还没起来 ⇒ 直接 mysqldump 必然连不上（errno 111）。
wait_for_mysql() {
    local cnf=$1
    local i
    for ((i = 1; i <= MYSQL_WAIT_TRIES; i++)); do
        if mysql --defaults-extra-file="$cnf" --batch --skip-column-names -e "SELECT 1;" >/dev/null 2>&1; then
            [ "$i" -gt 1 ] && echo "mysql 就绪（第 ${i} 次尝试）"
            return 0
        fi
        [ "$i" -eq 1 ] && echo "mysql 还没起来，等着…（最多 ${MYSQL_WAIT_TRIES}×${MYSQL_WAIT_INTERVAL}s）" >&2
        sleep "$MYSQL_WAIT_INTERVAL"
    done
    return 1
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
