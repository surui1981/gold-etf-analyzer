"""每日快照定时采集脚本（P0-1）。

由计划任务每日触发，调用运行中的服务 API 捕获当日评估快照。
采集为 upsert（同日更新），幂等可重复执行。

触发时机建议：
  - 16:00  A股/上金所收盘后（ETF 与上海金当日数据完整）
  - 06:00  纽约金 COMEX 收盘后（北京时间清晨，国际数据完整）

用法：
    python capture_snapshot.py               # 采集一次（默认最多等待服务就绪 180s）
    python capture_snapshot.py --wait 300    # 自定义等待上限
    python capture_snapshot.py --no-wait     # 不等待，服务不在直接退出

日志：capture.log
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
import urllib.error
import urllib.request

HEALTH_URL = "http://127.0.0.1:8888/api/v1/health"
CAPTURE_URL = "http://127.0.0.1:8888/api/v1/snapshots/capture"
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(PROJECT_DIR, "capture.log")

logger = logging.getLogger("capture")


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
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def wait_service(max_wait: int) -> bool:
    """等待服务就绪（看门狗会自动拉起服务）。"""
    waited = 0
    while waited < max_wait:
        if check_health():
            return True
        time.sleep(10)
        waited += 10
    return False


def capture() -> dict:
    """调用采集接口，返回快照 JSON。"""
    req = urllib.request.Request(
        CAPTURE_URL,
        data=b"",
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:  # 采集涉及真实行情，放宽超时
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="每日评估快照定时采集")
    parser.add_argument("--wait", type=int, default=180, help="等待服务就绪的最大秒数")
    parser.add_argument("--no-wait", action="store_true", help="不等待服务")
    args = parser.parse_args()

    _setup_logging()

    if not args.no_wait and not check_health():
        logger.warning("Service not ready, waiting up to %ss ...", args.wait)
        if not wait_service(args.wait):
            logger.error("Service unavailable, capture aborted")
            return

    try:
        snap = capture()
        logger.info(
            "Captured: date=%s close=%.3f trend=%.1f (%s) tech=%.1f macro=%.1f news=%.1f",
            snap.get("snapshot_date"), snap.get("close"), snap.get("trend_index"),
            snap.get("index_level"), snap.get("tech_index"),
            snap.get("macro_index"), snap.get("news_index"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Capture failed: %s", exc)


if __name__ == "__main__":
    main()
