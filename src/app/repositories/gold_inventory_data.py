"""COMEX 黄金库存数据采集。

数据源
------
COMEX（纽约商品交易所）黄金仓库库存总量，日频。经 AKShare
``ak.futures_comex_inventory`` 获取 —— 底层是公开表格页的 ``pandas.read_html``，
无需 KEY。实测覆盖 2021-10-25 起 1234 个交易日，截至 2026-10-20。

设计取舍（与 ``central_bank_data.py`` 同源纪律）
----------------------------------------------
- **子进程隔离调用**。AKShare 内部嵌了 V8 引擎（``py_mini_racer``），在主服务
  进程里崩过一次就会带走整个 uvicorn —— ``market_providers._sina_etf_via_subprocess``
  与 ``_us_gold_via_subprocess`` 都是同一个理由做的隔离，本 fetcher 沿用。
- **失败不回退 mock**。库存是「有多少、有没有在去库」的事实性数据，
  编一条确定性假序列比留空卡更坏：用户会把「COMEX 在持续去库」当成真信号用。
  宁缺勿假。
- **进程内 TTL 缓存 24h**。库存日频更新，一天抓一次足够。

口径
----
COMEX 库存 ≠ 央行持有量（``central_bank_purchases``）≠ ETF 持仓。三者常被混为一谈，
但只有本表回答「交易所仓库里还剩多少」。前端三张卡必须分开标注。
"""

import json
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime

from app.utils.logger import get_logger

logger = get_logger(__name__)

# 缓存 TTL：24h（库存日频，一天一次足够）
CACHE_TTL = 86400

# 子进程超时。实测抓 1234 行约 1-3s，30s 留足网络抖动余量。
SUBPROCESS_TIMEOUT = 30

# 子进程内跑的代码：只吐 JSON，异常打 stderr 后非零退出。
# ⚠ 用 ``list(df[...])`` 而不是 ``iterrows()``：read_html 返回的 DataFrame 里
# 日期列是 ``datetime.date``，iterrows 会把整行上转成 object dtype，
# 取值反而绕。这里直接按列转字符串，最短路径。
_TEMPLATE = """import sys, json, math
try:
    import akshare as ak
    df = ak.futures_comex_inventory()
    def num(x):
        # NaN / inf / None 一律转 None，交给主进程判断丢弃
        if x is None:
            return None
        try:
            v = float(x)
        except (TypeError, ValueError):
            return None
        return None if math.isnan(v) or math.isinf(v) else v
    out = [
        {"date": str(d)[:10], "tonnes": num(t), "ounces": num(o)}
        for d, t, o in zip(
            list(df["日期"]), list(df["COMEX黄金库存量-吨"]), list(df["COMEX黄金库存量-盎司"])
        )
    ]
    print(json.dumps(out))
except Exception as e:
    print("ERR:" + str(e)[:200], file=sys.stderr)
    sys.exit(3)
"""

# 进程内缓存：key=("comex",) -> (ts, points)
_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()


class GoldInventorySourceError(RuntimeError):
    """COMEX 库存源不可用（网络失败 / 解析失败 / 返回空）。**不降级 mock**。"""


@dataclass(frozen=True)
class InventoryPoint:
    """单日库存观测（吨）。"""

    inv_date: date
    tonnes: float
    ounces: float | None = None
    source: str = "COMEX"


def _parse_date(raw: str) -> date | None:
    """``'2026-10-20'`` → ``date``；解析不了返回 None（该行丢弃，不猜）。"""
    try:
        return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _normalize_rows(raw: list) -> list[InventoryPoint]:
    """子进程 JSON → ``InventoryPoint`` 列表。

    逐行容错：日期解不出、或吨数是 NaN/None/非数字 —— 丢这一行，其余照常。
    整批全废才抛错（交由调用方决定降级）。
    """
    points: list[InventoryPoint] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        d = _parse_date(row.get("date", ""))
        if d is None:
            continue
        try:
            tonnes = float(row["tonnes"])
        except (KeyError, TypeError, ValueError):
            continue
        # NaN / inf 一律丢掉：float('nan') 能过 float() 但会让所有变化率变 NaN
        if tonnes != tonnes or tonnes in (float("inf"), float("-inf")):
            continue
        ounces = row.get("ounces")
        try:
            ounces = float(ounces) if ounces is not None else None
        except (TypeError, ValueError):
            ounces = None
        if ounces is not None and ounces != ounces:
            ounces = None
        points.append(InventoryPoint(inv_date=d, tonnes=tonnes, ounces=ounces, source="COMEX"))

    # 同一天可能重复出现（源表偶有），保留后写的
    points.sort(key=lambda p: p.inv_date)
    deduped: dict[date, InventoryPoint] = {}
    for p in points:
        deduped[p.inv_date] = p
    return sorted(deduped.values(), key=lambda p: p.inv_date)


def _fetch_comex_via_subprocess() -> list:
    """子进程隔离调用 AKShare，失败返回 None。"""
    try:
        res = subprocess.run(
            [sys.executable, "-c", _TEMPLATE],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        if res.returncode == 0 and res.stdout.strip():
            return json.loads(res.stdout)
        logger.warning(
            "comex subprocess 失败 rc=%s stderr=%s",
            res.returncode,
            (res.stderr or "").strip()[:200],
        )
    except Exception as exc:
        logger.warning("comex subprocess 异常: %s", exc)
    return None


def fetch_comex_inventory(*, use_cache: bool = True) -> list[InventoryPoint]:
    """抓 COMEX 黄金库存全量历史（日频，约 1200+ 行）。

    Args:
        use_cache: 进程内 24h TTL 缓存开关。测试传 False 强制穿透。

    Returns:
        按日期升序的 ``InventoryPoint`` 列表。

    Raises:
        GoldInventorySourceError: 源不可用且无缓存可回。**不回退 mock**。
    """
    if use_cache:
        with _CACHE_LOCK:
            hit = _CACHE.get("comex")
            if hit and (time.time() - hit[0]) < CACHE_TTL:
                return hit[1]

    raw = _fetch_comex_via_subprocess()
    if raw is None:
        # 源挂了但缓存还在（未过期）：拿旧的总比让首页空掉强，但会打日志，
        # 让「今天没更新」这件事在服务端留痕，而不是静默显示昨天的数当今天的。
        with _CACHE_LOCK:
            hit = _CACHE.get("comex")
            if hit and (time.time() - hit[0]) < CACHE_TTL:
                logger.warning("comex 源不可用，回退 %dh 内的进程内缓存", CACHE_TTL // 3600)
                return hit[1]
        raise GoldInventorySourceError("COMEX 黄金库存源不可用（akshare 子进程失败）")

    points = _normalize_rows(raw)
    if not points:
        raise GoldInventorySourceError(f"COMEX 黄金库存返回空（raw {len(raw)} 行全部无法解析）")

    with _CACHE_LOCK:
        _CACHE["comex"] = (time.time(), points)
    logger.info(
        "comex inventory fetched: %d points, %s -> %s",
        len(points),
        points[0].inv_date,
        points[-1].inv_date,
    )
    return points
