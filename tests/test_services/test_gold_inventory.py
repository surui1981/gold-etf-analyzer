"""COMEX 黄金库存 Service 单测：多窗口变化率、空表降级、is_stale 判定。"""

from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.gold_inventory import GoldInventoryDaily
from app.repositories.gold_inventory import GoldInventoryRepository
from app.services.gold_inventory import GoldInventoryService

# 固定「今天」，免得用例随日历漂移
TODAY = date.today()


def _svc(db: AsyncSession) -> GoldInventoryService:
    return GoldInventoryService(GoldInventoryRepository(db))


async def _seed(db: AsyncSession, rows: list[dict]) -> None:
    for r in rows:
        db.add(GoldInventoryDaily(**r))
    await db.commit()


def _series(latest: float, days_back: int = 400, start: float | None = None) -> list[dict]:
    """造一条线性序列：最早 start 吨 → 今天 latest 吨。

    ``start=None`` 时让今天往前第 1 天就是 latest（即整条线持平），
    用来验证「持平」算 0.0 而「无基线」算 None —— 两者绝不能混淆。
    """
    if start is None:
        start = latest
    out = []
    for i in range(days_back):
        d = TODAY - timedelta(days=i)
        frac = (days_back - 1 - i) / max(days_back - 1, 1)
        out.append({"inv_date": d, "tonnes": start + (latest - start) * frac, "ounces": None})
    return out


# ──────────────── 空表 ────────────────


async def test_snapshot_empty_table_degrades(db_session: AsyncSession) -> None:
    """空表：latest=None、points=[]、degraded=True，四个窗口全 None。

    ⚠ 绝不能返回 0 —— 「库存 0 吨」和「没数据」在投资语境里完全相反。
    """
    out = await _svc(db_session).snapshot(days=90)
    assert out.points == []
    assert out.latest_tonnes is None
    assert out.as_of is None
    assert out.degraded is True
    assert [c.window for c in out.changes] == ["1w", "1m", "3m", "1y"]
    assert all(c.change_pct is None for c in out.changes)
    assert all(c.base_date is None for c in out.changes)


# ──────────────── 多窗口变化率 ────────────────


async def test_snapshot_all_windows_have_baselines(db_session: AsyncSession) -> None:
    """400 天序列 → 1w/1m/3m/1y **全部**有基线。

    这条钉的是 V0.115.0 修掉的那个 bug：原先回看起点用 ``today - 365d``，
    而最新观测常比今天早 2-3 天（交易日频），于是「1 年前」那个点正好落在
    查询窗口之外 → 1y 恒为 None。1m/3m 看着正常，只有 1y 悄悄空着。
    """
    await _seed(db_session, _series(latest=800.0, start=1000.0))
    out = await _svc(db_session).snapshot(days=90)
    assert out.degraded is False
    for c in out.changes:
        assert c.change_pct is not None, f"{c.window} 窗口没有基线"
        assert c.base_date is not None


async def test_snapshot_change_pct_values(db_session: AsyncSession) -> None:
    """变化率算术正确。

    ⚠ 期望值**自己算**，不写死常数。原先手写 ``== -20.0`` —— 而 1y 的基线落在
    ``今天-365d``，那里只是 400 天斜坡的第 35 天，不是坡的起点，实际是 -18.6%。
    实现是对的，错的是那个手猜的常数；这类「按经验值写死」的断言会在斜坡参数
    一改时给出误导性的红。这里改成拿基线吨数现算。
    """
    rows = _series(latest=800.0, start=1000.0, days_back=400)
    await _seed(db_session, rows)
    out = await _svc(db_session).snapshot(days=90)
    by = {c.window: c for c in out.changes}

    latest_t = out.latest_tonnes
    assert latest_t is not None
    for c in out.changes:
        assert c.base_date is not None and c.change_pct is not None
        base_t = next(r["tonnes"] for r in rows if r["inv_date"] == c.base_date)
        expected = round((latest_t - base_t) / base_t * 100, 2)
        assert c.change_pct == expected, f"{c.window} 期望 {expected}，实得 {c.change_pct}"

    # 线性下降时，短窗口的跌幅必然小于长窗口
    assert by["1w"].change_pct > by["1m"].change_pct > by["3m"].change_pct > by["1y"].change_pct


async def test_snapshot_flat_series_is_zero_not_none(db_session: AsyncSession) -> None:
    """持平的序列 → 变化率 0.0，**不是** None。

    「没变」与「没数据」必须可区分：前者是结论，后者是未知。
    """
    await _seed(db_session, _series(latest=500.0, start=None))
    out = await _svc(db_session).snapshot(days=90)
    for c in out.changes:
        assert c.change_pct == 0.0, f"{c.window} 应为 0.0 而非 None"
        assert c.base_date is not None


async def test_snapshot_short_history_leaves_far_windows_none(db_session: AsyncSession) -> None:
    """只有 40 天历史 → 1m 有值，3m/1y 无基线（返回 None，不是 0）。"""
    await _seed(db_session, _series(latest=800.0, start=1000.0, days_back=40))
    out = await _svc(db_session).snapshot(days=90)
    by = {c.window: c for c in out.changes}
    assert by["1w"].change_pct is not None
    assert by["1m"].change_pct is not None
    assert by["3m"].change_pct is None
    assert by["1y"].change_pct is None


# ──────────────── days 截断 ────────────────


async def test_snapshot_days_limits_returned_points_not_changes(db_session: AsyncSession) -> None:
    """``days`` 只截**返回的序列**，不截变化率窗口。

    ``days=90`` 时序列约 90 天，但 1y 变化率仍要有值 —— 这是两个独立口径。
    """
    await _seed(db_session, _series(latest=800.0, start=1000.0, days_back=400))
    out = await _svc(db_session).snapshot(days=90)
    assert len(out.points) <= 91  # 90 自然日 + 当天
    by = {c.window: c for c in out.changes}
    assert by["1y"].change_pct is not None


async def test_snapshot_points_sorted_ascending(db_session: AsyncSession) -> None:
    """序列必须升序 —— 前端直接画走势，倒序会画出折返线。"""
    await _seed(db_session, _series(latest=800.0, start=1000.0))
    out = await _svc(db_session).snapshot(days=90)
    dates = [p.date for p in out.points]
    assert dates == sorted(dates)


async def test_snapshot_marks_stale_when_source_stopped(db_session: AsyncSession) -> None:
    """最新观测距今 10 天 → degraded=True（源停更，页面须能提示）。"""
    rows = [
        {"inv_date": TODAY - timedelta(days=10 + i), "tonnes": 800.0 - i, "ounces": None}
        for i in range(30)
    ]
    await _seed(db_session, rows)
    out = await _svc(db_session).snapshot(days=90)
    assert out.degraded is True
    assert out.as_of == TODAY - timedelta(days=10)


# ──────────────── is_stale（scheduler bootstrap 判据）──


async def test_is_stale_on_empty_table(db_session: AsyncSession) -> None:
    assert await _svc(db_session).is_stale() is True


async def test_is_stale_fresh_when_updated_today(db_session: AsyncSession) -> None:
    await _seed(db_session, [{"inv_date": TODAY, "tonnes": 728.0, "ounces": None}])
    assert await _svc(db_session).is_stale() is False


async def test_is_stale_boundary_one_day_old(db_session: AsyncSession) -> None:
    """最新观测 1 天前：``> max_age_days(1)`` 不成立 → 不陈旧。

    边界就在这儿，少一天不补、多一天补。
    """
    await _seed(db_session, [{"inv_date": TODAY - timedelta(days=1), "tonnes": 728.0, "ounces": None}])
    assert await _svc(db_session).is_stale() is False


async def test_is_stale_when_latest_is_three_days_old(db_session: AsyncSession) -> None:
    """最新观测 3 天前（周一看到的是上周五的数）→ 陈旧，scheduler 应回填。

    ⚠ 别把这条理解成「周末是源故障」：判定纯粹按 ``max_age_days=1``，
    长周末之后回填一次是对的 —— 幂等 upsert，重抓同一天不会增行。
    """
    await _seed(db_session, [{"inv_date": TODAY - timedelta(days=3), "tonnes": 728.0, "ounces": None}])
    assert await _svc(db_session).is_stale() is True


async def test_is_stale_honours_custom_max_age(db_session: AsyncSession) -> None:
    """``max_age_days`` 可调：周报口径传 7 就不会每天回填。"""
    await _seed(db_session, [{"inv_date": TODAY - timedelta(days=5), "tonnes": 728.0, "ounces": None}])
    svc = _svc(db_session)
    assert await svc.is_stale(max_age_days=1) is True
    assert await svc.is_stale(max_age_days=7) is False


# ──────────────── upsert 幂等 ────────────────


async def test_upsert_bulk_is_idempotent(db_session: AsyncSession) -> None:
    """同一天重复 upsert 不增行（scheduler 每天重跑，行数必须稳定）。"""
    repo = GoldInventoryRepository(db_session)
    rows = [
        {"inv_date": date(2026, 10, 19), "tonnes": 728.0, "ounces": 1.0},
        {"inv_date": date(2026, 10, 20), "tonnes": 727.0, "ounces": 1.0},
    ]
    from app.models.gold_inventory import GoldInventoryDaily as M

    await repo.upsert_bulk([M(**r) for r in rows])
    assert await repo.count() == 2
    await repo.upsert_bulk([M(**r) for r in rows])
    assert await repo.count() == 2, "重复 upsert 不得增行"
    # 值确实被更新了（不是 no-op）
    await repo.upsert_bulk([M(**{**rows[1], "tonnes": 999.0})])
    latest = await repo.latest()
    assert latest is not None and latest.tonnes == 999.0