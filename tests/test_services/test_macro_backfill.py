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
