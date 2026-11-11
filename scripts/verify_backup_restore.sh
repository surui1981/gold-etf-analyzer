#!/usr/bin/env bash
# V0.126.0 · 备份**可恢复性**验证
#
# 为什么单独一个脚本：「备份文件在」不等于「能还原」。
# 本脚本把最新 dump 灌进一个**临时库**，逐表比对行数，验完删掉临时库。
#
# 用法：
#   sudo -S bash scripts/verify_backup_restore.sh            # 默认取最新一份备份
#   sudo -S bash scripts/verify_backup_restore.sh <dump.gz>  # 指定某一份
#
# ⚠ 需要管理员访问：应用账号只对自己的库有权限（建临时库会 1044）⇒
#   走 root-only 的 /etc/mysql/debian.cnf（不引入任何 MySQL 密码进 argv）。
# ⚠ sudo 密码走 stdin 会和被喂 stdin 的程序抢 ⇒
#   `sudo -S bash scripts/verify_backup_restore.sh < /tmp/.sudo_pw`
#
# ⚠⚠ **截点必须用 UTC**（本脚本踩过的坑）：
#   应用把 created_at / updated_at 存成 **UTC**（连接串 init_command
#   `SET time_zone='+00:00'`），而 dump 文件的 mtime 是**本机时区**（CST）。
#   ⇒ 拿 mtime 直接当截点会**错 8 小时**，把 dump 之后才写的行也算进去
#     ⇒ 报出假的「对不上」。本脚本用 `date -u` 转成 UTC。
#
# 判据分两层：
#   ① 直比：行数完全相等 ⇒ 最强证据；
#   ② 不等 ⇒ 用「dump 时刻」的口径再比一次，并把多出来的行的时间戳打出来
#     ⇒ 相等即证明「恢复完整」，差的那几行是 dump 之后的增量。
set -uo pipefail

BACKUP_DIR=${BACKUP_DIR:-$(cd "$(dirname "$0")/.." && pwd)/data/backups}
CNF=${MYSQL_ADMIN_CNF:-/etc/mysql/debian.cnf}
SRC=${MYSQL_PROD_DB:-gold_etf}
DST=${MYSQL_SCRATCH_DB:-gold_etf_restore_check}

if [ $# -ge 1 ]; then
    DUMP=$1
else
    DUMP=$(ls -t "$BACKUP_DIR"/gold_etf-*.sql.gz 2>/dev/null | head -1)
fi
if [ -z "${DUMP:-}" ] || [ ! -f "$DUMP" ]; then
    echo "找不到备份文件（$BACKUP_DIR/gold_etf-*.sql.gz）" >&2
    exit 1
fi

MTIME=$(stat -c %Y "$DUMP")
CUTOFF=$(date -u -d "@$MTIME" '+%F %T')
echo "备份文件：$DUMP（$(du -h "$DUMP" | cut -f1)）"
echo "dump 时刻：本机 $(date -d "@$MTIME" '+%F %T %Z') · 截点(UTC)=$CUTOFF"

q() { mysql --defaults-file="$CNF" --batch --skip-column-names -e "$1"; }

cleanup() { q "DROP DATABASE IF EXISTS \`$DST\`;" >/dev/null 2>&1; }
trap cleanup EXIT

echo "=== 0) 建临时库 $DST ==="
cleanup
q "CREATE DATABASE \`$DST\`;"

echo "=== 1) 灌 dump ==="
if ! zcat "$DUMP" | mysql --defaults-file="$CNF" "$DST"; then
    echo "❌ 恢复失败" >&2
    exit 1
fi

# 每张表的「时间口径列」；没有时间列的用「dump 里最大 id / 最大业务日期」切
filter_kind() {
    case "$1" in
        daily_snapshots) echo "ts:created_at" ;;
        news_scores) echo "ts:updated_at" ;;
        scoring_daily_wide) echo "maxdate:date" ;;
        telemetry_events) echo "ts:created_at" ;;
        *) echo "maxid:id" ;;
    esac
}

echo "=== 2) 逐表对行数 ==="
tables=$(q "SELECT table_name FROM information_schema.tables WHERE table_schema='$SRC' ORDER BY table_name;")
same=0; filt_same=0; diff=0; nd=0
for t in $tables; do
    a=$(q "SELECT COUNT(*) FROM \`$SRC\`.\`$t\`;")
    b=$(q "SELECT COUNT(*) FROM \`$DST\`.\`$t\`;")
    nd=$((nd + 1))
    if [ "$a" = "$b" ]; then
        same=$((same + 1))
        continue
    fi
    kind=$(filter_kind "$t")
    case "$kind" in
        ts:*)
            col=${kind#ts:}
            a2=$(q "SELECT COUNT(*) FROM \`$SRC\`.\`$t\` WHERE \`$col\` <= '$CUTOFF';")
            extra=$(q "SELECT CONCAT('      多出的行 → $col=', \`$col\`, ' UTC (= ', DATE_ADD($col, INTERVAL 8 HOUR), ' CST)') FROM \`$SRC\`.\`$t\` WHERE \`$col\` > '$CUTOFF' ORDER BY $col DESC LIMIT 5;" 2>/dev/null)
            ;;
        maxdate:*)
            col=${kind#maxdate:}
            maxd=$(q "SELECT COALESCE(MAX(\`$col\`),'1970-01-01') FROM \`$DST\`.\`$t\`;")
            a2=$(q "SELECT COUNT(*) FROM \`$SRC\`.\`$t\` WHERE \`$col\` <= '$maxd';")
            extra=$(q "SELECT CONCAT('      多出的行 → $col=', \`$col\`) FROM \`$SRC\`.\`$t\` WHERE \`$col\` > '$maxd' LIMIT 5;" 2>/dev/null)
            ;;
        *)
            maxid=$(q "SELECT COALESCE(MAX(id),0) FROM \`$DST\`.\`$t\`;")
            a2=$(q "SELECT COUNT(*) FROM \`$SRC\`.\`$t\` WHERE id <= $maxid;")
            extra=""
            ;;
    esac
    if [ "$a2" = "$b" ]; then
        filt_same=$((filt_same + 1))
        echo "  ⚠ $t  生产=$a 恢复=$b ⇒ 差 $((a - b)) 行；按 dump 时刻口径 生产=$a2 = 恢复=$b ⇒ **恢复完整**"
        [ -n "$extra" ] && echo "$extra"
    else
        diff=$((diff + 1))
        echo "  ❌ $t  生产=$a 恢复=$b 按 dump 时刻口径生产=$a2 ⇒ **对不上**"
    fi
done

echo
echo "  共 $nd 张表：直比相等 $same；按 dump 时刻口径相等 $filt_same；仍然对不上 $diff"

if [ "$diff" -eq 0 ]; then
    echo "✅ 备份可恢复：$nd/$nd 张表在「dump 时刻」的口径上逐张相等"
    exit 0
fi
echo "❌ 有 $diff 张表对不上" >&2
exit 1
