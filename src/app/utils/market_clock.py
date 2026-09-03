"""交易时段与数据时效判定（UX 6.1：数据时效与语境透明）。

提供两组能力：
1. **交易时段判定**：纽约金（COMEX GC，CME Globex 近乎全天连续）、
   上海金（SGE Au99.99，夜盘 + 日盘）、黄金 ETF（上交所 518880）当前的
   交易中 / 盘前 / 盘中休整 / 休市 状态，并给出下一时间点提示；
2. **数据时效分级**：结合数据源状态与数据截止日，判定
   实时 / 延时 / T-1 / 滞后多日 / 缓存 / 演示，避免把盘后静态价误当实时价。

设计约定：
- 本模块**只做纯逻辑计算**，不依赖 Pydantic Schema，供 Service 与趋势分析复用；
- 纽约金按**美东时间**（含夏令时自动换算）判定，国内两个市场按**北京时间**判定；
- 时段仅按「周一至周五 + 固定时段」计算，**不含法定节假日**（页面已注明）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum

try:  # pragma: no cover - 与时区数据库可用性相关
    from zoneinfo import ZoneInfo

    _ET = ZoneInfo("America/New_York")
    _CN = ZoneInfo("Asia/Shanghai")
except Exception:  # pragma: no cover - 无 tzdata 时回退固定偏移（不区分夏令时）
    _ET = timezone(timedelta(hours=-5), "ET")
    _CN = timezone(timedelta(hours=8), "CN")


class SessionState(StrEnum):
    """市场交易时段状态。"""

    OPEN = "open"  # 交易中
    PRE = "pre"  # 盘前（当日首个时段尚未开始）
    BREAK = "break"  # 盘中休整（午休 / 每日结算间歇）
    CLOSED = "closed"  # 休市（收盘后 / 周末）


_STATE_LABELS: dict[SessionState, str] = {
    SessionState.OPEN: "交易中",
    SessionState.PRE: "盘前",
    SessionState.BREAK: "盘中休整",
    SessionState.CLOSED: "休市",
}


@dataclass(frozen=True)
class MarketSession:
    """单个市场的当前交易时段快照。"""

    market: str = ""
    name: str = ""
    state: SessionState = SessionState.CLOSED
    state_label: str = ""
    windows: tuple[str, ...] = ()
    next_event: str = ""
    note: str = ""

    @property
    def is_open(self) -> bool:
        """是否处于交易中。"""
        return self.state == SessionState.OPEN


def _session(
    market: str,
    name: str,
    state: SessionState,
    windows: list[str],
    next_event: str,
    note: str,
) -> MarketSession:
    """构造 MarketSession（统一补状态中文名）。"""
    return MarketSession(
        market=market,
        name=name,
        state=state,
        state_label=_STATE_LABELS[state],
        windows=tuple(windows),
        next_event=next_event,
        note=note,
    )


def ny_gold_session(now: datetime | None = None) -> MarketSession:
    """纽约金（COMEX GC / CME Globex）交易时段。

    规则（美东时间）：周日 18:00 开盘 → 周五 17:00 收盘，每日 17:00-18:00 为结算间歇，
    周六全天休市。故纽约金近乎 23 小时连续交易，覆盖国内夜盘与休市时段。

    Args:
        now: 计算时刻（UTC）；缺省取当前时间

    Returns:
        纽约金当前时段快照
    """
    now = now or datetime.now(timezone.utc)
    et = now.astimezone(_ET)
    wd = et.weekday()  # Mon=0 ... Sun=6
    t = et.time()

    # 每日结算间歇（美东 17:00）对应的北京时间，便于国内用户对照
    break_cn = et.replace(hour=17, minute=0, second=0, microsecond=0).astimezone(_CN)
    windows = [
        "美东 周日 18:00 → 周五 17:00（近乎全天连续）",
        f"每日 美东 17:00-18:00 结算间歇（约北京 {break_cn:%H:%M}）",
    ]
    market, name = "ny", "纽约金（COMEX GC）"

    if wd == 5:  # 周六
        return _session(market, name, SessionState.CLOSED, windows,
                        "周日 18:00（美东）开盘", "周末休市，最新价为上一交易日收盘静态价")
    if wd == 6:  # 周日
        if t >= time(18, 0):
            return _session(market, name, SessionState.OPEN, windows,
                            "周五 17:00（美东）收盘", "新交易周已开盘")
        return _session(market, name, SessionState.PRE, windows,
                        "今日 18:00（美东）开盘", "周末休市，等待开盘")
    if wd == 4:  # 周五
        if t < time(17, 0):
            return _session(market, name, SessionState.OPEN, windows,
                            "今日 17:00（美东）进入周末休市", "交易中，临近周末收盘")
        return _session(market, name, SessionState.CLOSED, windows,
                        "周日 18:00（美东）开盘", "周末休市，最新价为收盘静态价")
    # 周一~周四
    if time(17, 0) <= t < time(18, 0):
        return _session(market, name, SessionState.BREAK, windows,
                        "今日 18:00（美东）恢复交易", "每日结算间歇，报价短暂停更")
    return _session(market, name, SessionState.OPEN, windows,
                    "次日 17:00（美东）结算间歇", "交易中")


def sge_session(now: datetime | None = None) -> MarketSession:
    """上海金（SGE Au99.99）交易时段（北京时间）。

    夜盘 20:00 → 次日 02:30（周一至周四夜）、早盘 09:00-11:30、午盘 13:30-15:30；
    周五无夜盘，日盘收市后进入周末休市。

    Args:
        now: 计算时刻（UTC）；缺省取当前时间

    Returns:
        上海金当前时段快照
    """
    now = now or datetime.now(timezone.utc)
    cn = now.astimezone(_CN)
    wd = cn.weekday()
    t = cn.time()
    windows = ["夜盘 20:00 → 次日 02:30（周一至周四）", "早盘 09:00-11:30", "午盘 13:30-15:30"]
    market, name = "sge", "上海金（SGE Au99.99）"

    if wd >= 5:  # 周末
        return _session(market, name, SessionState.CLOSED, windows,
                        "周一 09:00 开盘", "周末休市")
    if t < time(2, 30):
        # 凌晨 00:00-02:30 属前一交易日夜盘延续（周二至周五凌晨有夜盘）
        if wd >= 1:
            return _session(market, name, SessionState.OPEN, windows,
                            "今日 02:30 夜盘结束", "夜盘交易中（前一交易日夜盘延续）")
        return _session(market, name, SessionState.PRE, windows,
                        "今日 09:00 早盘开盘", "周一凌晨无夜盘，等待早盘")
    if t < time(9, 0):
        return _session(market, name, SessionState.PRE, windows,
                        "今日 09:00 早盘开盘", "盘前")
    if t < time(11, 30):
        return _session(market, name, SessionState.OPEN, windows,
                        "11:30 早盘收市", "早盘交易中")
    if t < time(13, 30):
        return _session(market, name, SessionState.BREAK, windows,
                        "13:30 午盘开盘", "午间休市")
    if t < time(15, 30):
        return _session(market, name, SessionState.OPEN, windows,
                        "15:30 日盘收市", "午盘交易中")
    if t < time(20, 0):
        if wd <= 3:  # 周一至周四：日盘收市后等待夜盘
            return _session(market, name, SessionState.BREAK, windows,
                            "20:00 夜盘开盘", "日盘已收市，等待夜盘")
        return _session(market, name, SessionState.CLOSED, windows,
                        "周一 09:00 开盘", "周五无夜盘，进入周末休市")
    if wd <= 3:
        return _session(market, name, SessionState.OPEN, windows,
                        "次日 02:30 夜盘结束", "夜盘交易中")
    return _session(market, name, SessionState.CLOSED, windows,
                    "周一 09:00 开盘", "周五无夜盘，进入周末休市")


def etf_session(now: datetime | None = None) -> MarketSession:
    """黄金 ETF（上交所 518880）交易时段（北京时间）。

    早盘 09:30-11:30、午盘 13:00-15:00，周一至周五（法定节假日休市）。

    Args:
        now: 计算时刻（UTC）；缺省取当前时间

    Returns:
        黄金 ETF 当前时段快照
    """
    now = now or datetime.now(timezone.utc)
    cn = now.astimezone(_CN)
    wd = cn.weekday()
    t = cn.time()
    windows = ["早盘 09:30-11:30", "午盘 13:00-15:00"]
    market, name = "etf", "黄金ETF（518880）"

    if wd >= 5:  # 周末
        return _session(market, name, SessionState.CLOSED, windows,
                        "周一 09:30 开盘", "周末休市")
    if t < time(9, 30):
        return _session(market, name, SessionState.PRE, windows,
                        "今日 09:30 开盘", "盘前")
    if t < time(11, 30):
        return _session(market, name, SessionState.OPEN, windows,
                        "11:30 早盘收市", "早盘交易中")
    if t < time(13, 0):
        return _session(market, name, SessionState.BREAK, windows,
                        "13:00 午盘开盘", "午间休市")
    if t < time(15, 0):
        return _session(market, name, SessionState.OPEN, windows,
                        "15:00 收盘", "午盘交易中")
    next_open = "下周一 09:30 开盘" if wd == 4 else "明日 09:30 开盘"
    return _session(market, name, SessionState.CLOSED, windows,
                    next_open, "已收盘，最新价为当日收盘静态价")


class FreshnessLevel(StrEnum):
    """数据时效等级。"""

    REALTIME = "realtime"  # 实时（交易中且数据截止当日）
    DELAYED = "delayed"  # 延时（数据截止当日但已收盘/休市，属盘后静态价）
    T1 = "t1"  # T-1（数据截止上一交易日）
    LAGGED = "lagged"  # 滞后多日
    CACHED = "cached"  # 缓存（数据源失败，读取磁盘旧缓存，可能过期）
    MOCK = "mock"  # 演示（非真实行情）
    UNKNOWN = "unknown"  # 尚未采集


_FRESHNESS_LABELS: dict[FreshnessLevel, str] = {
    FreshnessLevel.REALTIME: "实时",
    FreshnessLevel.DELAYED: "延时（盘后静态）",
    FreshnessLevel.T1: "T-1（上一交易日）",
    FreshnessLevel.LAGGED: "滞后多日",
    FreshnessLevel.CACHED: "缓存（可能过期）",
    FreshnessLevel.MOCK: "演示（非真实行情）",
    FreshnessLevel.UNKNOWN: "未采集",
}


def freshness_label(level: FreshnessLevel) -> str:
    """时效等级 → 中文标签。"""
    return _FRESHNESS_LABELS[level]


def classify_freshness(
    *,
    status: str,
    data_date: date | None,
    session_state: SessionState,
    now: datetime | None = None,
) -> FreshnessLevel:
    """判定数据时效等级。

    判定顺序：数据源状态优先（mock → 演示、stale → 缓存），
    再按「数据截止日 vs 今日（北京时间）」的自然日差分级：
    当日 + 交易中 → 实时；当日 + 休市 → 延时；差 1 日 → T-1；差 ≥2 日 → 滞后多日。

    Args:
        status: 数据源状态 live / stale / mock
        data_date: 数据截止日（最后一根 K 线日期）
        session_state: 该市场当前交易时段状态
        now: 计算时刻（UTC）；缺省取当前时间

    Returns:
        时效等级
    """
    if status == "mock":
        return FreshnessLevel.MOCK
    if status == "stale":
        return FreshnessLevel.CACHED
    if data_date is None:
        return FreshnessLevel.UNKNOWN

    now = now or datetime.now(timezone.utc)
    lag_days = (now.astimezone(_CN).date() - data_date).days
    if lag_days <= 0:
        return (
            FreshnessLevel.REALTIME
            if session_state == SessionState.OPEN
            else FreshnessLevel.DELAYED
        )
    if lag_days == 1:
        return FreshnessLevel.T1
    return FreshnessLevel.LAGGED
