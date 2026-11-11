"""服务看门狗：定时健康检查，卡死/停止时自动重启。

独立进程运行，不受服务自身卡死影响（服务挂了看门狗仍在工作）。

用法：
    python watchdog.py                    # 前台运行（默认 30s 检查一次）
    python watchdog.py --interval 20      # 自定义间隔
    python watchdog.py --once             # 只检查一次（用于调试）

开机自启：见 install_startup.ps1（注册为计划任务 GoldPriceAssistantWatchdog）
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

HEALTH_URL = "http://127.0.0.1:8888/api/v1/health"
CAPTURE_URL = "http://127.0.0.1:8888/api/v1/snapshots/capture"
PORT = 8888
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable
LOG_FILE = os.path.join(PROJECT_DIR, "watchdog.log")
CAPTURE_STATE_FILE = os.path.join(PROJECT_DIR, "capture_state.json")

# 每日定时采集快照的时刻（本地时间）：16:00 国内收盘后 ｜ 06:00 纽约金收盘后
CAPTURE_TIMES = ["06:00", "16:00"]
CAPTURE_WINDOW = 1800  # 触发时刻后 30 分钟内有效，避免跨天误触发

# 数据库连接与备份目录（V0.126.0：SQLite / MySQL 双方言）
#
# ⚠ **MySQL 没有「库文件」**：原来 ``_DB_PATH`` 直接切 URL 再取 dirname，
# 换成 MySQL 后会得到一个**不存在的路径** ⇒ 备份目录被算到错误的地方
# （``/home/surui/backup`` 之类），备份写出去也没人知道。
# ⇒ 两种方言各自算自己的「数据目录」：SQLite 跟库文件，MySQL 跟项目 data/。
try:
    from app.config import get_settings  # 独立脚本运行时不强依赖

    _DB_URL = get_settings().database_url
except Exception:  # noqa: BLE001
    _DB_URL = ""

_DB_IS_MYSQL = _DB_URL.startswith(("mysql", "mariadb"))
_DB_IS_SQLITE = _DB_URL.startswith("sqlite")

if _DB_IS_SQLITE:
    _DB_PATH = _DB_URL.split("///", 1)[-1]
    _DATA_DIR = os.path.dirname(_DB_PATH)
elif _DB_IS_MYSQL:
    _DB_PATH = ""  # MySQL 没有库文件
    _DATA_DIR = os.path.join(PROJECT_DIR, "data")
else:
    # 拿不到配置时兜底到项目 data/（⚠ 原来兜底到 **项目父目录**的 data/ —— 那是个路径 bug）
    _DB_PATH = os.path.join(PROJECT_DIR, "data", "gold_etf.db")
    _DATA_DIR = os.path.join(PROJECT_DIR, "data")
# ⚠ V0.126.0：目录名与 ``scripts/daily_backup.sh`` 对齐（``backups`` 复数）——
#   原来这里是 ``backup`` 单数 ⇒ 两个备份工具各写各的目录 ⇒ 同一个库有**两份**
#   互不相干的备份，且谁也不知道对方那份还在不在。
BACKUP_DIR = os.path.join(_DATA_DIR, "backups")
BACKUP_KEEP = 7  # 保留最近 7 份

# 快照归档：保留最近 N 天，更早的导出 JSON 到 archive/ 后删除
SNAPSHOT_RETENTION_DAYS = 365
ARCHIVE_DIR = os.path.join(_DATA_DIR, "archive")

logger = logging.getLogger("watchdog")


def _setup_logging() -> None:
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)


def check_health(timeout: float = 5.0) -> bool:
    """健康检查：HTTP 200 视为正常。"""
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _run(cmd: list[str], timeout: int = 15) -> str:
    """执行命令并返回 stdout（健壮解码，失败返回空串）。"""
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Command failed: %s (%s)", " ".join(cmd), exc)
        return ""
    for enc in ("utf-8", "gbk", "mbcs"):
        try:
            return proc.stdout.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return proc.stdout.decode("utf-8", errors="ignore")


def listening_pids(port: int) -> list[int]:
    """返回占用指定端口的监听进程 PID 列表。"""
    out = _run(["netstat", "-ano"])
    if not out:
        return []
    pids: set[int] = set()
    for line in out.splitlines():
        if f":{port}" in line and "LISTENING" in line.upper():
            parts = line.split()
            if parts and parts[-1].isdigit():
                pids.add(int(parts[-1]))
    return list(pids)


def kill_stale(port: int) -> int:
    """终止占用端口的全部进程，返回处理数量。"""
    count = 0
    for pid in listening_pids(port):
        subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True, timeout=15,
        )
        logger.warning("Killed stale process pid=%s on port %s", pid, port)
        count += 1
    return count


def start_service() -> bool:
    """后台启动 uvicorn 服务。

    输出写入独立日志文件（server_wd.log），避免与被重启进程持有的
    server.log 句柄冲突（Windows 下文件被占用会导致启动失败）。

    启动方式说明：直接 Popen + DETACHED_PROCESS 会让服务进程权限受限
    （实测 SQLite 写入报 "attempt to write a readonly database"），
    因此改用 PowerShell Start-Process（与手动启动等效，写入正常）。
    """
    server_log = os.path.join(PROJECT_DIR, "server_wd.log")
    server_err = os.path.join(PROJECT_DIR, "server_wd.log.err")

    args = f"-m uvicorn app.main:app --host 0.0.0.0 --port {PORT}"
    ps_cmd = (
        f"Start-Process -FilePath '{PYTHON}' "
        f"-ArgumentList '{args}' "
        f"-WorkingDirectory '{PROJECT_DIR}' "
        f"-WindowStyle Hidden "
        f"-RedirectStandardOutput '{server_log}' "
        f"-RedirectStandardError '{server_err}'"
    )
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            cwd=PROJECT_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info("Service starting on port %s (via Start-Process)", PORT)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to start service: %s", exc)
        return False


def _load_capture_state() -> dict:
    try:
        with open(CAPTURE_STATE_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"done": {}}


def _save_capture_state(state: dict) -> None:
    with open(CAPTURE_STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(state, fh)


def do_capture() -> dict:
    """调用采集接口，返回快照结果。"""
    req = urllib.request.Request(
        CAPTURE_URL, data=b"", method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


def archive_snapshots() -> None:
    """归档超过保留期的每日快照：导出 JSON 到 archive/ 后删除（幂等）。

    ⚠ **V0.126.0：改走 SQLAlchemy（双方言同一份 SQL）**。
    原来直接 ``sqlite3.connect`` —— MySQL 下必然 ``sqlite3.OperationalError``。
    这段 SQL 本身是标准 SQL（``SELECT`` / ``DELETE ... WHERE <``）⇒ 两个库通用。
    """
    try:
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
        cutoff = (datetime.now() - timedelta(days=SNAPSHOT_RETENTION_DAYS)).strftime("%Y-%m-%d")
        cols = [
            "snapshot_date", "symbol", "close", "change_pct", "direction",
            "tech_index", "macro_index", "news_index", "trend_index", "index_level",
        ]
        rows = _fetch_snapshot_rows(cutoff, cols)
        if rows:
            payload = [dict(zip(cols, r)) for r in rows]
            dest = os.path.join(ARCHIVE_DIR, f"snapshots_{datetime.now():%Y%m%d}.json")
            with open(dest, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            _delete_snapshot_rows(cutoff)
            logger.info(
                "snapshots archived: %d rows -> %s (retain %sd)",
                len(rows), dest, SNAPSHOT_RETENTION_DAYS,
            )
        else:
            logger.debug("no snapshots older than %sd to archive", SNAPSHOT_RETENTION_DAYS)
    except Exception as exc:  # noqa: BLE001
        logger.error("snapshot archive failed: %s", exc)


def _fetch_snapshot_rows(cutoff: str, cols: list[str]) -> list[tuple]:
    """读待归档的快照行（SQLite 直连；MySQL 走 SQLAlchemy）。"""
    if _DB_IS_MYSQL:
        return _run_sqlalchemy(
            f"SELECT {', '.join(cols)} FROM daily_snapshots WHERE snapshot_date < :cutoff",
            {"cutoff": cutoff},
        )
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    try:
        return conn.execute(
            f"SELECT {', '.join(cols)} FROM daily_snapshots WHERE snapshot_date < ?",
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()


def _delete_snapshot_rows(cutoff: str) -> None:
    """删除已归档的快照行。"""
    if _DB_IS_MYSQL:
        _run_sqlalchemy(
            "DELETE FROM daily_snapshots WHERE snapshot_date < :cutoff",
            {"cutoff": cutoff},
            commit=True,
        )
        return
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    try:
        conn.execute("DELETE FROM daily_snapshots WHERE snapshot_date < ?", (cutoff,))
        conn.commit()
    finally:
        conn.close()


def _run_sqlalchemy(sql: str, params: dict, *, commit: bool = False) -> list[tuple]:
    """在应用自己的连接层上跑一条 SQL（MySQL 分支用）。

    ⚠ 用应用 engine ⇒ 时区/连接参数与线上完全一致（UTC session tz 等），
    不会因为「看门狗另开一条连接」而与线上口径分叉。
    """
    import asyncio

    from sqlalchemy import text

    from app.repositories.db import async_session_factory

    async def _run() -> list[tuple]:
        async with async_session_factory() as session:
            result = await session.execute(text(sql), params)
            rows = [tuple(r) for r in result.all()]
            if commit:
                await session.commit()
            return rows

    return asyncio.run(_run())


def backup_db(now: datetime) -> None:
    """每日备份主库（按日期命名，保留最近 BACKUP_KEEP 份）。"""
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        if _DB_IS_MYSQL:
            _backup_mysql(now)
            return
        dst = os.path.join(BACKUP_DIR, f"gold_etf_{now:%Y%m%d}.db")
        if not os.path.exists(dst):
            if os.path.exists(_DB_PATH):
                shutil.copy2(_DB_PATH, dst)
                logger.info("db backup created: %s", dst)
        backups = sorted(glob.glob(os.path.join(BACKUP_DIR, "gold_etf_*.db")), reverse=True)
        for old in backups[BACKUP_KEEP:]:
            os.remove(old)
            logger.info("db backup cleaned: %s", old)
    except Exception as exc:  # noqa: BLE001
        logger.error("db backup failed: %s", exc)


def _backup_mysql(now: datetime) -> None:
    """MySQL 备份：mysqldump --single-transaction（InnoDB 一致性快照，不停写）。

    ⚠ 凭据走 0600 临时 defaults 文件（``--defaults-extra-file``）⇒ 密码不进 argv。
    """
    import gzip
    import tempfile

    dst = os.path.join(BACKUP_DIR, f"gold_etf_{now:%Y%m%d}.sql.gz")
    fd, cnf = tempfile.mkstemp(prefix="gold-etf-watchdog-", suffix=".cnf")
    os.close(fd)
    try:
        with open(cnf, "w", encoding="utf-8") as fh:
            fh.write(_mysql_client_cnf())
        os.chmod(cnf, 0o600)
        proc = subprocess.run(
            [
                "mysqldump", f"--defaults-extra-file={cnf}",
                "--single-transaction", "--quick",
                "--routines", "--triggers", "--events",
                "--default-character-set=utf8mb4",
                "--hex-blob", "--no-tablespaces", "--tz-utc",
                "--set-gtid-purged=OFF",
                _mysql_db_name(),
            ],
            capture_output=True, check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"mysqldump failed rc={proc.returncode}: "
                f"{proc.stderr.decode('utf-8', 'replace')[:400]}"
            )
        with gzip.open(dst, "wb") as out:
            out.write(proc.stdout)
        logger.info("db backup created: %s (%d bytes raw)", dst, len(proc.stdout))
    finally:
        if os.path.exists(cnf):
            os.remove(cnf)
    # 保留最近 BACKUP_KEEP 份（MySQL 分支是 .sql.gz）
    backups = sorted(glob.glob(os.path.join(BACKUP_DIR, "gold_etf_*.sql.gz")), reverse=True)
    for old in backups[BACKUP_KEEP:]:
        os.remove(old)
        logger.info("db backup cleaned: %s", old)


def _mysql_client_cnf() -> str:
    """把 DATABASE_URL 拆成 my.cnf 片段（密码不进 argv、不进日志）。"""
    import urllib.parse

    parsed = urllib.parse.urlsplit(_DB_URL.replace("mysql+asyncmy://", "mysql://", 1))
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 3306
    user = urllib.parse.unquote(parsed.username or "")
    pw = urllib.parse.unquote(parsed.password or "")
    return (
        "[client]\n"
        f"host={host}\nport={port}\nuser={user}\npassword={pw}\n"
        "default-character-set=utf8mb4\n"
    )


def _mysql_db_name() -> str:
    import urllib.parse

    parsed = urllib.parse.urlsplit(_DB_URL.replace("mysql+asyncmy://", "mysql://", 1))
    return (parsed.path or "/").lstrip("/").split("?", 1)[0]


def maybe_capture() -> None:
    """到达每日采集时刻且当日该时段未采集 → 执行一次（幂等）。"""
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    state = _load_capture_state()
    done = state.setdefault("done", {})
    today = now.strftime("%Y-%m-%d")

    for slot_time in CAPTURE_TIMES:
        slot = f"{today} {slot_time}"
        if done.get(slot):
            continue
        try:
            target = datetime.strptime(slot, "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        delta = (now - target).total_seconds()
        if not (0 <= delta <= CAPTURE_WINDOW):
            continue
        backup_db(now)  # 每日随采集备份主库
        archive_snapshots()  # 每日归档超期快照
        try:
            snap = do_capture()
            done[slot] = now.isoformat(timespec="seconds")
            _save_capture_state(state)
            logger.info(
                "scheduled capture done (%s): close=%.3f trend=%.1f (%s)",
                slot, snap.get("close", 0), snap.get("trend_index", 0), snap.get("index_level"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("scheduled capture failed (%s): %s", slot, exc)


def restart(reason: str) -> None:
    """清理残留进程并重启服务。"""
    logger.warning("Restart triggered: %s", reason)
    killed = kill_stale(PORT)
    if killed:
        time.sleep(2)
    if start_service():
        # 等待启动完成并验证
        for _ in range(12):
            time.sleep(5)
            if check_health():
                logger.info("Service recovered successfully")
                return
        logger.error("Service restarted but health check still failing")
    else:
        logger.error("Restart failed: could not start service")


def main() -> None:
    parser = argparse.ArgumentParser(description="黄金价格投资辅助工具 · 服务看门狗")
    parser.add_argument("--interval", type=int, default=30, help="检查间隔秒数（默认 30）")
    parser.add_argument("--threshold", type=int, default=2, help="连续失败几次触发重启（默认 2）")
    parser.add_argument("--once", action="store_true", help="只检查一次后退出")
    parser.add_argument(
        "--capture-times", default=",".join(CAPTURE_TIMES),
        help="每日快照采集时刻，逗号分隔（默认 06:00,16:00）",
    )
    parser.add_argument("--no-capture", action="store_true", help="关闭内置定时采集")
    args = parser.parse_args()

    capture_times = [t.strip() for t in args.capture_times.split(",") if t.strip()]
    CAPTURE_TIMES.clear()
    CAPTURE_TIMES.extend(capture_times)

    _setup_logging()
    logger.info(
        "Watchdog started (interval=%ss, threshold=%s, capture=%s, pid=%s)",
        args.interval, args.threshold,
        "off" if args.no_capture else "/".join(CAPTURE_TIMES), os.getpid(),
    )

    fails = 0
    while True:
        if check_health():
            if fails:
                logger.info("Service recovered (fails reset)")
            fails = 0
            if not args.no_capture:
                maybe_capture()
        else:
            fails += 1
            logger.warning("Health check failed (%s/%s)", fails, args.threshold)
            if fails >= args.threshold:
                restart(f"连续 {fails} 次健康检查失败")
                fails = 0

        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
