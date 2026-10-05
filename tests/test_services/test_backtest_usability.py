"""回测可用性披露（V0.79.0 Step G 前置修复）。

为什么有这个文件
----------------
2026-10-06 实测发现：``gold_price_daily`` 表**0 行**，而
``backtest._build_next_returns()`` 从该表取 T+1 涨跌幅，``list_range()`` 又是
**纯 DB 查询、无实时回退** ⇒ ``next_returns`` 全 0.0 ⇒

* ``compute_sharpe()`` 遇零方差返回 **0.0**（所有 48 行 best/worst Sharpe 相同）；
* ``judge_hit()`` 对 NEUTRAL 判 ``abs(change_pct) <= NEUTRAL_BAND_PCT``，
  **全 0 也满足** ⇒ 命中率虚高（实测 avg_win_rate=0.6319）；
* 而 ``sample_warning`` 竟为 **False** —— 因为它只看快照天数（24 > 20）。

⇒ HTTP 200 + 无任何告警 + 数字看着「正常」，用户无从分辨「回测无效」与
「回测有效但表现差」。**这与项目里已知的「静默回退 / 静默兜底」同类**。

本文件锁死修复后的行为，重点是**此前无任何测试覆盖的那个场景**：
快照充足 **但** 价格日历为空。
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest

from app.repositories.review import GoldPriceRepository
from app.schemas.backtest import BacktestCoverageOut
from app.services.backtest import BacktestService
from app.services.settings import WeightService

# ─────────────── 内存桩 ───────────────


class _FakeSnapshot:
    """最小 DailySnapshot 替身（只需 coverage 读取的两个字段）。"""

    def __init__(self, d: date) -> None:
        self.snapshot_date = d
        self.tech_index = 50.0


class _FakeBar:
    """GoldPriceDaily 替身：`_build_next_returns` 只读这两个属性。"""

    __slots__ = ("close", "price_date")

    def __init__(self, price_date: date, close: float) -> None:
        self.price_date = price_date
        self.close = close


class _FakeGold:
    """GoldPriceRepository 替身：按传入行数决定价格日历「是否有数据」。

    ⚠ 必须能区分「0 条」与「N 条」—— 这正是原缺陷所在：真实实现里
    ``list_range`` 只查 DB，表空就返回空列表，且**不做任何回退**。
    """

    def __init__(self, bars: list[tuple[date, float]] | None) -> None:
        self._bars = bars or []
        self.range_calls = 0

    async def count_in_range(self, *, target: str, start: date, end: date) -> int:
        self.range_calls += 1
        return len([b for b in self._bars if start <= b[0] <= end])

    # ⚠ 签名与返回类型须与真实实现一致：`_build_next_returns` 调的是
    # `self._gold.list_range(target, start=..., end=...)`（target 是**位置参数**），
    # 并逐条读 `.price_date` / `.close`。写成 keyword-only 或返回裸 tuple，
    # 测试会「因为价格日历恒空而通过」，等于没测到 T+1 计算本身。
    async def list_range(self, target: str, *, start: date, end: date, limit=None):
        self.range_calls += 1
        return [_FakeBar(d, c) for d, c in self._bars if start <= d <= end]


class _FakeSession:
    """最小 AsyncSession 桩：按给定快照列表返回行。"""

    def __init__(self, snapshots: list[_FakeSnapshot]) -> None:
        self._snapshots = snapshots

    async def execute(self, stmt):
        rows = self._snapshots

        class _Result:
            def scalars(self_inner):
                class _Scalars:
                    def all(self_inner_inner):
                        return list(rows)

                return _Scalars()

            def scalar(self_inner):
                return 0

        return _Result()


def _mk_service(
    *,
    snapshots: list[_FakeSnapshot],
    bars: list[tuple[date, float]] | None,
) -> BacktestService:
    return BacktestService(
        session=_FakeSession(snapshots),  # type: ignore[arg-type]
        gold=_FakeGold(bars),  # type: ignore[arg-type]
        weights=WeightService(None),  # type: ignore[arg-type]
    )


def _snapshots(n: int, *, end: date = date(2026, 10, 6)) -> list[_FakeSnapshot]:
    """构造 n 条快照，**按日期升序**（与真实查询 ``ORDER BY snapshot_date ASC`` 一致）。

    ⚠ 顺序不是风格问题：``coverage()`` 取 ``start=rows[0]`` / ``end=rows[-1]``。
    若桩返回降序，会得到 ``start > end`` ⇒ 价格日历查询区间为空 ⇒
    「有价格数据」也测出 ``price_calendar_days=0`` ⇒ **测试以假绿通过**。
    """
    return [_FakeSnapshot(end - timedelta(days=n - 1 - i)) for i in range(n)]


def _bars(snapshots: list[_FakeSnapshot]) -> list[tuple[date, float]]:
    """为每个快照日 +1 天构造一根价格（⇒ T+1 收益可算且为正）。

    ⚠ 依赖 ``_build_next_returns`` 的实现：它按 ``price_date`` 升序取相邻两根，
    算 ``close[i+1]/close[i]-1``。价格必须**递增**才产生正收益；顺序颠倒会得到
    负收益或零收益，而「零收益」会让 ``returns_available_days`` 误判为 0
    （``0.0`` 与「无数据」在返回 dict 里无法区分 —— 这也是需要在
    ``coverage`` 侧单独计数的理由）。
    """
    last = snapshots[-1].snapshot_date
    return [(s.snapshot_date, 10.0 + i * 0.1) for i, s in enumerate(snapshots)] + [
        (last + timedelta(days=1), 10.0 + len(snapshots) * 0.1)
    ]


# ─────────────── 核心回归：此前完全无覆盖的场景 ───────────────


def test_snapshot_rich_but_price_calendar_empty_is_not_usable() -> None:
    """★ 快照 30 条（>20 下限）但价格日历 0 条 ⇒ usable=False 且 sample_warning=True。

    这是 2026-10-06 实测的真实场景。修复前该场景返回
    ``available_days=30 / sample_warning=False / best_sharpe=0.0``，
    用户看到的是一份「看起来正常」的假回测。
    """
    svc = _mk_service(snapshots=_snapshots(30), bars=None)

    cov = asyncio.run(svc.coverage(target="etf", days=90))

    assert cov.available_days == 30, "快照本身是充足的"
    assert cov.price_calendar_days == 0
    assert cov.returns_available_days == 0
    assert cov.returns_missing_days == 30
    # ⚠ 关键断言：样本数够不代表结果可用
    assert cov.usable is False
    assert cov.sample_warning is True, "样本充足但价格缺失时必须告警"
    # 备注必须说明根因，否则用户不知道该去做什么
    assert "价格日历" in cov.note


def test_price_calendar_partial_reports_missing_days() -> None:
    """价格日历只覆盖前 6 天 ⇒ 披露缺失天数，usable 仍为 True。"""
    snaps = _snapshots(10)
    # 只给前 6 个快照日配价格。`_bars` 会额外补「末位+1 天」那根，
    # 它恰好落在第 7 个快照日 ⇒ 共 7 根价格，但只有前 6 天有后继交易日。
    svc = _mk_service(snapshots=snaps, bars=_bars(snaps[:6]))

    cov = asyncio.run(svc.coverage(target="etf", days=90))

    assert cov.price_calendar_days == 7
    assert cov.returns_available_days == 6
    assert cov.returns_missing_days == 4
    assert cov.usable is True
    assert "未参与指标计算" in cov.note


def test_price_calendar_complete_is_usable() -> None:
    """价格日历完整（末尾多一根 T+1）⇒ usable=True、sample_warning=False。"""
    snaps = _snapshots(30)
    svc = _mk_service(snapshots=snaps, bars=_bars(snaps))

    cov = asyncio.run(svc.coverage(target="etf", days=90))

    assert cov.usable is True
    assert cov.sample_warning is False
    # `_bars` 末尾额外补了「最后一日 +1 天」那根 ⇒ 每个快照日都有后继交易日
    assert cov.returns_available_days == 30
    assert cov.returns_missing_days == 0
    assert cov.price_calendar_days == 31  # 30 根对齐 + 1 根 T+1


def test_last_snapshot_without_next_close_is_excluded() -> None:
    """⚠ 最后一个快照日若没有后继交易日 ⇒ 不计入可用天数（锁死该口径）。

    这是「快照末日」的真实情形：回测窗口的最后一天天然没有 T+1，
    它的对错**无法判定**，不应混进命中率分母之外却仍算作「可用」。
    """
    snaps = _snapshots(10)
    bars_no_tail = _bars(snaps)[:-1]  # 去掉末尾那根 T+1
    svc = _mk_service(snapshots=snaps, bars=bars_no_tail)

    cov = asyncio.run(svc.coverage(target="etf", days=90))

    assert cov.price_calendar_days == 10
    assert cov.returns_available_days == 9
    assert cov.returns_missing_days == 1
    assert cov.usable is True
    assert "未参与指标计算" in cov.note


# ─────────────── 边界 ───────────────


def test_empty_snapshots_also_discloses_price_calendar() -> None:
    """快照表为空 ⇒ usable=False 且价格日历字段为 0（不抛错）。"""
    svc = _mk_service(snapshots=[], bars=None)

    cov = asyncio.run(svc.coverage(target="etf", days=90))

    assert cov.available_days == 0
    assert cov.usable is False
    assert cov.sample_warning is True
    assert cov.price_calendar_days == 0


def test_single_price_bar_gives_no_returns() -> None:
    """只有 1 根价格 ⇒ 构不成 T+1 ⇒ returns 不可用。

    锁死 ``len(bars) < 2`` 这条既有短路不被破坏。
    """
    snaps = _snapshots(5)
    svc = _mk_service(snapshots=snaps, bars=[(snaps[0].snapshot_date, 10.0)])

    cov = asyncio.run(svc.coverage(target="etf", days=90))

    assert cov.returns_available_days == 0
    assert cov.usable is False


def test_schema_defaults_are_backward_compatible() -> None:
    """新增字段有默认值 ⇒ 旧构造方式（不传新字段）仍可用。"""
    cov = BacktestCoverageOut(
        target="etf",
        start_date=None,
        end_date=None,
        available_days=0,
        available_window_trading_days=0,
    )
    assert cov.price_calendar_days == 0
    assert cov.returns_available_days == 0
    assert cov.returns_missing_days == 0
    # ⚠ 默认必须落在「保守」一侧：拿不到数据时不能宣称结果可用
    assert cov.usable is False
    assert cov.sample_warning is False


def test_gold_price_repository_has_count_in_range() -> None:
    """仓储须提供 count_in_range（coverage 依赖它披露价格日历）。"""
    assert hasattr(GoldPriceRepository, "count_in_range")


@pytest.mark.parametrize("n_snaps", [1, 2, 5, 29])
def test_returns_available_never_exceeds_snapshot_count(n_snaps: int) -> None:
    """不变量：可算收益的天数不超过快照数。"""
    snaps = _snapshots(n_snaps)
    svc = _mk_service(snapshots=snaps, bars=_bars(snaps))

    cov = asyncio.run(svc.coverage(target="etf", days=90))

    assert cov.returns_available_days <= cov.available_days
    assert cov.returns_missing_days == cov.available_days - cov.returns_available_days
