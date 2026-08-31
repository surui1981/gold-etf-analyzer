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
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

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

# 数据库路径与备份目录（与主库同目录 backup/）
try:
    from app.config import get_settings  # 独立脚本运行时不强依赖

    _DB_PATH = get_settings().database_url.split("///", 1)[-1]
except Exception:  # noqa: BLE001
    _DB_PATH = os.path.join(os.path.dirname(PROJECT_DIR), "data", "gold_etf.db")
BACKUP_DIR = os.path.join(os.path.dirname(_DB_PATH), "backup")
BACKUP_KEEP = 7  # 保留最近 7 份

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


def backup_db(now: datetime) -> None:
    """每日备份主库（按日期命名，保留最近 BACKUP_KEEP 份）。"""
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
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
