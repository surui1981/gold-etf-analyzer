"""宏观因子历史回填单测（V0.118.0）。

不依赖真实网络：三个外部源（H.15 / FRED / Yahoo）全部用 monkeypatch 打桩。
回填本身是「让 V0.79.0 Step E 的滚动 90/10 分位真正生效」的前置条件，
所以它的两条关键性质必须锁住：

1. **幂等** —— 同 ``(target, snapshot_date, factor_key)`` 覆盖写，重复跑不产生脏数据；
2. **只补缺口** —— 样本已足够的因子直接跳过，日常调度调用近乎零成本。
"""

from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.macro_factor_history import MacroFactorHistoryRepository

TODAY = date(2026, 10, 25)


@pytest.fixture
def repo(db_session: AsyncSession) -> MacroFactorHistoryRepository:
    return MacroFactorHistoryRepository(db_session)


@pytest.fixture
def stub_sources(monkeypatch):
    """把 H.15 / FRED / Yahoo 三个历史源全部打桩。

    返回一个 dict，调用方可以改写其中的返回值来模拟「某源失败」。
    """
    state: dict = {
        "h15": [
            (date(2026, 10, 21), 4.79, 5.12, 5.42),
            (date(2026, 10, 22), 4.65, 4.96, 5.29),
            (date(2026, 10, 23), 4.60, 4.94, 5.27),
        ],
        "fred": {
            "DFII10": [(date(2026, 10, 22), 2.64)],
            "VIXCLS": [(date(2026, 10, 22), 19.03)],
        },
        "yahoo": [(date(2026, 10, 22), 101.75)],
    }

    async def fake_h15():
        result = state["h15"]
        if isinstance(result, BaseException):
            raise result
        return result

    async def fake_fred():
        result = state["fred"]
        if isinstance(result, BaseException):
            raise result
        return result

    async def fake_yahoo():
        result = state["yahoo"]
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr("app.services.macro_backfill._fetch_h15_history", fake_h15)
    monkeypatch.setattr("app.services.macro_backfill._fetch_fred_history", fake_fred)
    monkeypatch.setattr("app.services.macro_backfill._fetch_yahoo_history", fake_yahoo)
    return state


# ───────────────────── 基本回填 ─────────────────────


async def test_backfill_writes_all_seven_factors(repo, stub_sources) -> None:
    """7 个可回填因子全部落表（cb_gold 无日频历史，不参与）。"""
    from app.services.macro_backfill import backfill_macro_history

    result = await backfill_macro_history(repo, target="default", days=400, today=TODAY)

    assert set(result) == {
        "dxy",
        "us2y",
        "us10y",
        "us30y",
        "curve_10y2y",
        "real10y",
        "vix",
    }
    for key in ("us2y", "us10y", "us30y", "curve_10y2y"):
        assert await repo.count_samples("default", key, 400, end_date=TODAY) == 3
    for key in ("dxy", "real10y", "vix"):
        assert await repo.count_samples("default", key, 400, end_date=TODAY) == 1


async def test_backfill_derives_curve_from_10y_minus_2y(repo, stub_sources) -> None:
    """10Y-2Y 利差由同一份 H.15 派生：4.96 − 4.65 = 0.31。"""
    from app.services.macro_backfill import backfill_macro_history

    await backfill_macro_history(repo, target="default", days=400, today=TODAY)

    rows = await repo.get_window("default", "curve_10y2y", 400, end_date=TODAY)
    by_date = {r.snapshot_date: r.value for r in rows}
    assert by_date[date(2026, 10, 22)] == pytest.approx(0.31)
    assert by_date[date(2026, 10, 21)] == pytest.approx(0.33)
    assert by_date[date(2026, 10, 23)] == pytest.approx(0.34)


async def test_backfill_is_idempotent(repo, stub_sources) -> None:
    """重复跑：行数不变（按 (target, snapshot_date, factor_key) 覆盖写）。"""
    from app.services.macro_backfill import backfill_macro_history

    await backfill_macro_history(repo, target="default", days=400, today=TODAY)
    await backfill_macro_history(repo, target="default", days=400, today=TODAY, force=True)

    assert await repo.count_samples("default", "us10y", 400, end_date=TODAY) == 3
    assert await repo.count_samples("default", "dxy", 400, end_date=TODAY) == 1


async def test_backfill_skips_factors_with_enough_samples(repo, stub_sources) -> None:
    """样本已充足的因子**不再**回填（日常调度调用近乎零成本）。"""
    from app.services.macro_backfill import backfill_macro_history

    # 先灌满一个因子的历史
    rows = [
        (TODAY - timedelta(days=i), "us10y", 4.9, "2026-10-20", "美联储 H.15") for i in range(120)
    ]
    await repo.upsert_many("default", rows)

    await backfill_macro_history(repo, target="default", days=400, today=TODAY)

    # us10y 已有 120 ≥ 60 样本 → 本轮不应再写它（但行数不变，仍是 120）
    assert await repo.count_samples("default", "us10y", 400, end_date=TODAY) == 120
    # 其他因子照常回填
    assert await repo.count_samples("default", "us2y", 400, end_date=TODAY) == 3


async def test_backfill_respects_window(repo, stub_sources) -> None:
    """窗口外的数据不回填。"""
    from app.services.macro_backfill import backfill_macro_history

    stub_sources["h15"] = [
        (TODAY - timedelta(days=400), 4.0, 4.5, 5.0),  # 窗口外
        (TODAY - timedelta(days=3), 4.65, 4.96, 5.29),  # 窗口内
    ]
    await backfill_macro_history(repo, target="default", days=30, today=TODAY)

    assert await repo.count_samples("default", "us10y", 30, end_date=TODAY) == 1


async def test_backfill_skips_rows_without_2y(repo, stub_sources) -> None:
    """H.15 某行没有 2Y → 该行不产出 us2y / curve_10y2y（但 10Y/30Y 照常）。"""
    from app.services.macro_backfill import backfill_macro_history

    stub_sources["h15"] = [
        (date(2026, 10, 21), None, 5.12, 5.42),
        (date(2026, 10, 22), 4.65, 4.96, 5.29),
    ]
    await backfill_macro_history(repo, target="default", days=400, today=TODAY)

    assert await repo.count_samples("default", "us2y", 400, end_date=TODAY) == 1
    assert await repo.count_samples("default", "curve_10y2y", 400, end_date=TODAY) == 1
    assert await repo.count_samples("default", "us10y", 400, end_date=TODAY) == 2


# ───────────────────── 单源失败降级 ─────────────────────


async def test_backfill_survives_one_source_failure(repo, stub_sources) -> None:
    """一个源挂掉不影响其他源（``return_exceptions=True``）。"""
    from app.services.macro_backfill import backfill_macro_history

    stub_sources["h15"] = RuntimeError("H.15 403")
    result = await backfill_macro_history(repo, target="default", days=400, today=TODAY)

    assert "us10y" not in result
    assert "dxy" in result
    assert await repo.count_samples("default", "us10y", 400, end_date=TODAY) == 0
    assert await repo.count_samples("default", "dxy", 400, end_date=TODAY) == 1


async def test_backfill_returns_empty_when_all_sources_fail(repo, stub_sources) -> None:
    """全部源失败 → 返回空 dict，不抛异常。"""
    from app.services.macro_backfill import backfill_macro_history

    stub_sources["h15"] = RuntimeError("boom")
    stub_sources["fred"] = RuntimeError("boom")
    stub_sources["yahoo"] = RuntimeError("boom")

    result = await backfill_macro_history(repo, target="default", days=400, today=TODAY)
    assert result == {}


# ───────────────────── V0.124.0 · 深回填（11 因子 / 日历日 / point-in-time） ─────────────────────

DEEP_END = date(2026, 11, 9)


@pytest.fixture
def stub_deep_sources(monkeypatch):
    """把深回填的 5 个外部源 + 1 个本地源全部打桩。

    数据刻意做成**稀疏且不齐**（周末无观测、低频只有季度），
    这样才能验证「日历日粒度」和「point-in-time 不前视」这两条关键性质。

    ⚠ **观测日 ≠ 可得日**：源在 T 日观测到的读数，采集日最早是
    「T+1 工作日 + 1 天」（H.15/FRED）或「T+1 天」（Yahoo）——
    口径见 ``app/services/macro_history.py``。
    下面每个日期都标了它被推算出的**可得日**：

    - H.15 ``2026-10-28``（周三）→ 可得 ``10-30``（周五）
    - H.15 ``2026-11-03``（周二）→ 可得 ``11-05``（周四）
    - H.15 ``2026-11-05``（周三）→ 可得 ``11-07``（周六）
    - FRED ``2026-11-03``（周二）→ 可得 ``11-05``
    - Yahoo ``2026-11-05``（周三）→ 可得 ``11-06``
    """
    state: dict = {
        # 工作日才有的 H.15。第一条落在**窗口起点之前**（2026-10-28），
        # 用来验证「窗口前的观测要保留、给窗口第一天播种」。
        "h15": [
            (date(2026, 10, 28), 4.05, 4.25, 4.75),
            (date(2026, 11, 3), 4.10, 4.30, 4.80),
            (date(2026, 11, 5), 4.12, 4.32, 4.82),
        ],
        "fred": {
            "DFII10": [(date(2026, 11, 3), 2.10)],
            "VIXCLS": [(date(2026, 11, 3), 15.5)],
        },
        "yahoo": [(date(2026, 11, 5), 100.5)],
        # 低频 FRED：季度用**期初**日期标注（2026-04-01 = 2026Q2）
        "fred_periodic": {
            "GFDEGDQ188S": [(date(2026, 4, 1), 120.0)],
            "GGGDTACNA188N": [(date(2023, 1, 1), 88.327)],
        },
        "euro": [(date(2026, 6, 30), 88.0)],
        # WGC 全球合计行：4 个季度 ⇒ 第一个 t12m 观测在第 4 个季度期末（2026-09-30）
        "cb": [
            ("2025Q4", 200.0),
            ("2026Q1", 250.0),
            ("2026Q2", 300.0),
            ("2026Q3", 40.2),
        ],
    }

    def _wrap(key, default):
        async def fake(*_args, **_kwargs):
            result = state.get(key, default)
            if isinstance(result, BaseException):
                raise result
            return result

        return fake

    monkeypatch.setattr("app.services.macro_backfill._fetch_h15_history", _wrap("h15", []))
    monkeypatch.setattr("app.services.macro_backfill._fetch_fred_history", _wrap("fred", {}))
    monkeypatch.setattr("app.services.macro_backfill._fetch_yahoo_dxy_deep", _wrap("yahoo", []))
    monkeypatch.setattr("app.services.macro_backfill._fetch_eurostat_deep", _wrap("euro", []))
    monkeypatch.setattr(
        "app.services.macro_backfill._fetch_fred_periodic_history",
        _wrap("fred_periodic", {}),
    )
    monkeypatch.setattr("app.services.macro_backfill._fetch_cb_gold_quarters", _wrap("cb", []))
    return state


async def test_deep_backfill_covers_all_eleven_factors(repo, stub_deep_sources) -> None:
    """11 个因子（7 日频 + 4 低频）全部落表。"""
    from app.services.macro_backfill import backfill_macro_history_deep

    result = await backfill_macro_history_deep(
        repo, target="default", days=10, end=DEEP_END, dry_run=True
    )

    assert set(result) == {
        "dxy",
        "us2y",
        "us10y",
        "us30y",
        "curve_10y2y",
        "real10y",
        "vix",
        "cb_gold",
        "us_gov_debt",
        "cn_gov_debt",
        "eu_gov_debt",
    }


async def test_deep_backfill_uses_calendar_day_granularity(repo, stub_deep_sources) -> None:
    """行粒度是**日历日**（周末也有一行，值沿用上一条观测）。

    线上 ``daily_capture_loop`` 每天 07:00 触发、无星期过滤 ⇒
    滚动分位窗口（252 **日历**日）里的样本数必须与线上一致，
    否则「复算」算出来的 P10/P90 就不是生产口径。
    """
    from app.services.macro_backfill import backfill_macro_history_deep

    await backfill_macro_history_deep(repo, target="default", days=10, end=DEEP_END)

    rows = await repo.get_window("default", "us10y", 10, end_date=DEEP_END)
    by_date = {r.snapshot_date: r.value for r in rows}
    # 2026-11-07 是周六、11-08 是周日 ⇒ 必须都有行，且沿用上一条可得观测
    assert date(2026, 11, 7) in by_date
    assert date(2026, 11, 8) in by_date
    assert by_date[date(2026, 11, 7)] == pytest.approx(4.32)
    assert by_date[date(2026, 11, 8)] == pytest.approx(4.32)
    # 11-09 无新观测 ⇒ 值不变
    assert by_date[date(2026, 11, 9)] == pytest.approx(4.32)


async def test_deep_backfill_covers_every_calendar_day(repo, stub_deep_sources) -> None:
    """窗口内**每个日历日**都要有一行（周末也不许缺）。"""
    from app.services.macro_backfill import backfill_macro_history_deep

    await backfill_macro_history_deep(repo, target="default", days=10, end=DEEP_END)

    rows = await repo.get_window("default", "us10y", 10, end_date=DEEP_END)
    dates = sorted(r.snapshot_date for r in rows)
    # 窗口 = 2026-10-30 → 2026-11-09，11 个日历日**一个都不能少**
    assert len(dates) == 11
    assert dates[0] == date(2026, 10, 30)
    assert dates[-1] == DEEP_END
    # 周末连续
    assert dates[7] == date(2026, 11, 6)
    assert dates[8] == date(2026, 11, 7)
    assert dates[9] == date(2026, 11, 8)


async def test_deep_backfill_is_point_in_time_no_future_leak(repo, stub_deep_sources) -> None:
    """**不前视**：某天只能看到「**可得日 ≤ 该天**」的读数。

    可得日 ≠ 观测日：H.15 在 T 日的读数要到 ``next_business_day(T) + 1``
    才发布 ⇒ 采集日 D 看到的是「D 之前最后一个已发布的读数」。

    反向验证：把 ``asof_rows`` 改成「用最新观测回填全历史」，
    本测试必须变红（这是 V0.124.0 最核心的口径守卫）。
    """
    from app.services.macro_backfill import backfill_macro_history_deep

    await backfill_macro_history_deep(repo, target="default", days=10, end=DEEP_END)

    rows = await repo.get_window("default", "us10y", 10, end_date=DEEP_END)
    by_date = {r.snapshot_date: r.value for r in rows}
    # 11-03 的读数 11-05 才可得 ⇒ 11-04 绝不能看到它
    assert by_date[date(2026, 11, 4)] == pytest.approx(4.25)
    # 11-05 起才切到 11-03 的读数
    assert by_date[date(2026, 11, 5)] == pytest.approx(4.30)
    assert by_date[date(2026, 11, 6)] == pytest.approx(4.30)
    # 11-05 的读数 11-07 才可得
    assert by_date[date(2026, 11, 7)] == pytest.approx(4.32)
    assert by_date[date(2026, 11, 9)] == pytest.approx(4.32)
    # 10-28 的观测在窗口之前 ⇒ 用来给 10-30 播种，但不能被后面的值覆盖
    assert by_date[date(2026, 10, 30)] == pytest.approx(4.25)


async def test_deep_backfill_lowfreq_uses_period_end_and_lag(repo, stub_deep_sources) -> None:
    """低频因子按「**观测期末 + 实测发布滞后**」判定可得。

    - FRED 季度 ``2026-04-01``（= 2026Q2 期初）⇒ 期末 ``2026-06-30``
      ⇒ 可得 ``2026-06-30 + 122 天 = 2026-10-30``；
    - FRED 年度 ``2023-01-01``（= 2023 期初）⇒ 期末 ``2023-12-31``
      ⇒ 可得 ``+ 665 天 = 2025-10-26``；
    - Eurostat 已是期末日 ``2026-06-30`` ⇒ 可得 ``+ 119 天 = 2026-10-27``。

    ⇒ 可得日之前**没有行**（不前视、不兜底）。
    """
    from app.services.macro_backfill import backfill_macro_history_deep

    await backfill_macro_history_deep(repo, target="default", days=800, end=DEEP_END)

    us_rows = await repo.get_window("default", "us_gov_debt", 800, end_date=DEEP_END)
    us_dates = sorted(r.snapshot_date for r in us_rows)
    assert us_dates[0] == date(2026, 10, 30)

    cn_rows = await repo.get_window("default", "cn_gov_debt", 800, end_date=DEEP_END)
    cn_dates = sorted(r.snapshot_date for r in cn_rows)
    assert cn_dates[0] == date(2025, 10, 26)

    eu_rows = await repo.get_window("default", "eu_gov_debt", 800, end_date=DEEP_END)
    eu_dates = sorted(r.snapshot_date for r in eu_rows)
    assert eu_dates[0] == date(2026, 10, 27)


async def test_deep_backfill_lowfreq_value_is_not_written_before_availability(
    repo, stub_deep_sources
) -> None:
    """低频因子在**可得日之前**一行都不能有（否则就是前视）。"""
    from app.services.macro_backfill import backfill_macro_history_deep

    await backfill_macro_history_deep(repo, target="default", days=800, end=DEEP_END)

    us_rows = await repo.get_window("default", "us_gov_debt", 800, end_date=DEEP_END)
    assert all(r.snapshot_date >= date(2026, 10, 30) for r in us_rows)

    cb_rows = await repo.get_window("default", "cb_gold", 800, end_date=DEEP_END)
    assert all(r.snapshot_date >= date(2026, 11, 8) for r in cb_rows)


async def test_deep_backfill_cb_gold_uses_aggregate_t12m(repo, stub_deep_sources) -> None:
    """``cb_gold`` = WGC **合计行**滚动 4 季合计（不是各国行求和）。

    桩数据 200 + 250 + 300 + 40.2 = 790.2 吨 —— 与 V0.121.4 实测的
    合计行真值 790.2 一致（旧的各国行求和口径报 842.6）。

    可得日 = 窗口末季期末（2026-09-30）+ WGC 实测发布滞后 39 天 = 2026-11-08。
    """
    from app.services.macro_backfill import backfill_macro_history_deep

    await backfill_macro_history_deep(repo, target="default", days=800, end=DEEP_END)

    rows = await repo.get_window("default", "cb_gold", 800, end_date=DEEP_END)
    assert rows, "cb_gold 应有行"
    newest = max(rows, key=lambda r: r.snapshot_date)
    assert newest.value == pytest.approx(790.2)
    # 第一个 t12m 观测出现在第 4 个季度期末 + 发布滞后
    assert min(r.snapshot_date for r in rows) == date(2026, 11, 8)
    assert newest.data_date == "2025Q4–2026Q3"


async def test_deep_backfill_seeds_window_from_earlier_observation(repo, stub_deep_sources) -> None:
    """窗口起点之前的那次观测必须**保留**（用来给窗口第一天「播种」）。

    线上每个日历日都写一行，值 = 「当时能拿到的最新读数」⇒ 窗口第一天
    也要有值，哪怕那次观测发生在窗口之前。
    ⚠ 曾经的实现按 ``start <= 观测日`` 过滤 ⇒ 窗口前半段整段空白
    （低频因子更严重：一次季度观测被滤掉 ⇒ 该因子在窗口内一行都没有）。
    """
    from app.services.macro_backfill import backfill_macro_history_deep

    await backfill_macro_history_deep(repo, target="default", days=10, end=DEEP_END)

    rows = await repo.get_window("default", "us10y", 10, end_date=DEEP_END)
    by_date = {r.snapshot_date: r.value for r in rows}
    # 窗口起点 = 2026-11-09 − 10 天 = 2026-10-30；最近的一次观测是 11-06
    assert min(by_date) == date(2026, 10, 30)
    assert by_date[date(2026, 10, 30)] == pytest.approx(4.25)
    assert len(by_date) == 11  # 10 天窗口 + 首尾闭合 = 11 个日历日


async def test_deep_backfill_can_target_lowfreq_subset(repo, stub_deep_sources) -> None:
    """``factors=`` 可只写低频 4 个 ⇒ **不拉**日频源的数（省 3 次网络请求）。

    低频因子在生产上永远走静态带（``SKIP_ROLLING_FACTORS``），
    补它们只为「历史可查 + 证据复测」，不需要日频源。
    """
    from app.services.macro_backfill import DEEP_LOWFREQ_FACTORS, backfill_macro_history_deep

    calls: list[str] = []

    async def _boom(*_a, **_k):  # pragma: no cover - 不该被调用
        calls.append("boom")
        raise AssertionError("只写低频因子时不应拉日频源")

    import app.services.macro_backfill as mb

    orig_h15, orig_fred, orig_yahoo = (
        mb._fetch_h15_history,
        mb._fetch_fred_history,
        mb._fetch_yahoo_dxy_deep,
    )
    mb._fetch_h15_history = _boom
    mb._fetch_fred_history = _boom
    mb._fetch_yahoo_dxy_deep = _boom
    try:
        result = await backfill_macro_history_deep(
            repo,
            target="default",
            days=800,
            end=DEEP_END,
            dry_run=True,
            factors=DEEP_LOWFREQ_FACTORS,
        )
    finally:
        mb._fetch_h15_history, mb._fetch_fred_history, mb._fetch_yahoo_dxy_deep = (
            orig_h15,
            orig_fred,
            orig_yahoo,
        )

    assert set(result) == set(DEEP_LOWFREQ_FACTORS)
    assert not calls


async def test_deep_backfill_dry_run_does_not_write(repo, stub_deep_sources) -> None:
    """``dry_run=True`` 只统计不写库。"""
    from app.services.macro_backfill import backfill_macro_history_deep

    result = await backfill_macro_history_deep(
        repo, target="default", days=10, end=DEEP_END, dry_run=True
    )

    assert result["us10y"] > 0
    assert await repo.count_samples("default", "us10y", 10, end_date=DEEP_END) == 0


async def test_deep_backfill_is_idempotent(repo, stub_deep_sources) -> None:
    """重跑不脏：按 (target, snapshot_date, factor_key) 覆盖写。"""
    from app.services.macro_backfill import backfill_macro_history_deep

    await backfill_macro_history_deep(repo, target="default", days=10, end=DEEP_END)
    first = await repo.count_samples("default", "us10y", 10, end_date=DEEP_END)
    await backfill_macro_history_deep(repo, target="default", days=10, end=DEEP_END)
    second = await repo.count_samples("default", "us10y", 10, end_date=DEEP_END)

    assert first == second > 0


async def test_deep_backfill_survives_one_source_failure(repo, stub_deep_sources) -> None:
    """一个源挂掉不影响其它源（5 个源互相独立）。"""
    from app.services.macro_backfill import backfill_macro_history_deep

    stub_deep_sources["h15"] = RuntimeError("H.15 403")
    result = await backfill_macro_history_deep(
        repo, target="default", days=10, end=DEEP_END, dry_run=True
    )

    assert "us10y" not in result
    assert "dxy" in result
    assert "cb_gold" in result


# ───────────────────── V0.124.0 实测踩到的两个坑（各带反向验证） ─────────────────────


async def test_deep_backfill_yahoo_fetch_reserves_lookback(
    repo, stub_deep_sources, monkeypatch
) -> None:
    """Yahoo 取数必须带**回看余量**（V0.124.0 生产实测踩到的坑）。

    Yahoo 是**唯一按窗口取数**的源（H.15 / FRED / Eurostat 都是全量历史）
    ⇒ 窗口第一天的「当时能拿到的最新读数」必须来自**窗口之前**的一次观测。
    不留回看 ⇒ 窗口第一天那行**整行缺失**。

    实测症状：脚本重建有 ``2021-11-10 dxy``，生产回填没有 ⇒ X1 差 1 行。
    """
    from app.services import macro_backfill

    seen: dict = {}

    async def fake_yahoo(start, end):
        seen["start"] = start
        seen["end"] = end
        return []

    monkeypatch.setattr(macro_backfill, "_fetch_yahoo_dxy_deep", fake_yahoo)

    await macro_backfill.backfill_macro_history_deep(repo, target="default", days=10, end=DEEP_END)

    window_start = DEEP_END - timedelta(days=10)
    assert seen["start"] == window_start - timedelta(days=macro_backfill.YAHOO_LOOKBACK_DAYS)
    assert seen["start"] < window_start, "取数起点必须早于窗口起点，否则窗口第一天没有可播种的读数"


async def test_deep_backfill_window_first_day_uses_pre_window_observation(
    repo, stub_deep_sources, monkeypatch
) -> None:
    """窗口第一天的值必须来自**窗口之前**的观测（Yahoo 只回请求区间内的日线）。

    这个桩刻意模拟真实 Yahoo 的行为：**只返回请求区间里的日线** ⇒
    若取数起点 == 窗口起点，窗口第一天就没有任何可用观测 ⇒ 该行缺失。
    """
    from app.services import macro_backfill

    async def fake_yahoo(start, end):
        # 真实 Yahoo 就是「只给请求区间内的日线」
        return [(start + timedelta(days=1), 100.0), (start + timedelta(days=2), 101.0)]

    monkeypatch.setattr(macro_backfill, "_fetch_yahoo_dxy_deep", fake_yahoo)

    await macro_backfill.backfill_macro_history_deep(repo, target="default", days=10, end=DEEP_END)

    window_start = DEEP_END - timedelta(days=10)
    rows = await repo.get_window("default", "dxy", 30, end_date=DEEP_END)
    by_date = {r.snapshot_date: r.value for r in rows}
    assert window_start in by_date, "窗口第一天必须有 dxy 行（用窗口之前的最后一次观测播种）"
    # 取数起点 = 窗口起点 − 30 天 ⇒ 两条观测的**可得日**分别是 10-03 / 10-04
    # ⇒ 窗口第一天（10-30）看到的是**最后一次**可得观测（101.0）
    assert by_date[window_start] == pytest.approx(101.0)


# ───────────────────── H.15 UA 回归锁 ─────────────────────


async def test_h15_history_fetch_sends_browser_user_agent(monkeypatch) -> None:
    """H.15 必须带浏览器 UA —— 不发 UA 直接 403（Yahoo 同规则，FRED 相反）。

    这是本轮实测踩到的坑：回填脚本用「不发 UA」的 ``_http_text`` 打 H.15，
    整段历史静默为空 → 回填「成功」但一个交易日都没进来。
    """
    from app.repositories import macro_sources

    seen: dict = {}

    def fake_http_text(url: str, timeout: int = 15, user_agent: str | None = None) -> str:
        seen["url"] = url
        seen["user_agent"] = user_agent
        return "header\n"

    monkeypatch.setattr(macro_sources, "_http_text", fake_http_text)

    from app.services.macro_backfill import _fetch_h15_history

    await _fetch_h15_history()

    assert seen["user_agent"] == macro_sources.BROWSER_UA
    assert "federalreserve.gov" in seen["url"]
