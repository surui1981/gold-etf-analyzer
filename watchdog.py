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
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

HEALTH_URL = "http://127.0.0.1:8888/api/v1/health"
PORT = 8888
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable
LOG_FILE = os.path.join(PROJECT_DIR, "watchdog.log")

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
    """
    server_log = os.path.join(PROJECT_DIR, "server_wd.log")
    server_err = os.path.join(PROJECT_DIR, "server_wd.log.err")
    creation = 0
    if os.name == "nt":
        creation = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        with open(server_log, "a", encoding="utf-8") as fo, open(server_err, "a", encoding="utf-8") as fe:
            subprocess.Popen(
                [
                    PYTHON, "-m", "uvicorn", "app.main:app",
                    "--host", "0.0.0.0", "--port", str(PORT),
                ],
                cwd=PROJECT_DIR,
                stdout=fo,
                stderr=fe,
                creationflags=creation,
                close_fds=True,
            )
        logger.info("Service starting on port %s", PORT)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to start service: %s", exc)
        return False


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
    args = parser.parse_args()

    _setup_logging()
    logger.info(
        "Watchdog started (interval=%ss, threshold=%s, pid=%s)",
        args.interval, args.threshold, os.getpid(),
    )

    fails = 0
    while True:
        if check_health():
            if fails:
                logger.info("Service recovered (fails reset)")
            fails = 0
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
