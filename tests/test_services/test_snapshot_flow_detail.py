"""每日快照的资金流面落库测试（V0.120.0）。

覆盖两件容易写错的事：

1. **面分可空** —— 资金流面「整面不可用」时（一个因子都没取到真实读数）
   存 **NULL**，不是 0.0（0 会被读成「资金正在撤离黄金」），也不是 50.0
   （50 是「中性」，而真相是「没数」）。
2. **同日重复捕获会更新新列** —— 仓储的 update 分支有一份**硬编码白名单**，
   新列漏加 ⇒ 当日第二次捕获时该字段**永远不更新**（V0.79.0 `tech_detail` 踩过）。
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.market_data import GoldKline
from app.repositories.snapshot import SnapshotRepository
from app.schemas.common import DirectionSignal
from app.schemas.market import MacroIndexOut, MoneyFlowFactorOut, MoneyFlowIndexOut
from app.services.snapshot import DailySnapshotService
from app.services.trend import TrendService


class FakeRepo:
    def __init__(self, klines: list[GoldKline]) -> None:
        self._k = klines

    async def get_gold_history(self, days: int = 60) -> list[GoldKline]:
        return self._k

    async def get_gold_gram_history(self, days: int = 60) -> list[GoldKline]:
        return self._k

    async def get_us_gold_history(self, days: int = 60) -> list[GoldKline]:
        return self._k


class FakeMacro:
    async def evaluate(self) -> MacroIndexOut:
        return MacroIndexOut(
            score=50.0, direction=DirectionSignal.NEUTRAL, factors=[], summary="测试"
        )


class FakeFlow:
    """假资金流面：可切换「有分」/「整面不可用」。

    ⚠ 口径与真实现一致：**整面不可用时 ``factors`` 是空列表**（见
    ``services/money_flow.py``）—— 不是「6 个因子各带 None 分」。
    """

    def __init__(self, score: float | None, factors: list[MoneyFlowFactorOut]) -> None:
        self._score = score
        self._factors = factors

    async def evaluate(self) -> MoneyFlowIndexOut:
        return MoneyFlowIndexOut(
            score=self._score,
            direction=DirectionSignal.BEARISH,
            factors=self._factors,
            summary="测试",
        )


def _factor(key: str, score: float = 60.0) -> MoneyFlowFactorOut:
    return MoneyFlowFactorOut(
        key=key,
        name=key,
        value="1.0",
        unit="%",
        data_date="2026-09-30",
        source="测试源",
        tier="live",
        cadence="monthly",
        max_lag_days=60,
        window_days=1826,
        score=score,
        direction=DirectionSignal.NEUTRAL,
        weight=0.14,
        contribution=0.0,
        detail="测试",
    )


def _mk_klines() -> list[GoldKline]:
    closes = [round(1 + i * 0.01, 3) for i in range(60)]
    base = date(2026, 6, 1)
    return [
        GoldKline(date=base + timedelta(days=i), open=c, close=c, high=c, low=c, volume=0.0)
        for i, c in enumerate(closes)
    ]


def _service(db: AsyncSession, flow=None) -> DailySnapshotService:
    trend = TrendService(FakeRepo(_mk_klines()), macro=FakeMacro(), flow=flow)
    return DailySnapshotService(SnapshotRepository(db), trend)


# ───────────────────── 1. 未注入资金流服务 ─────────────────────


async def test_未注入资金流服务时两列都是NULL(db_session: AsyncSession) -> None:
    """没注入资金流服务 ⇒ 该面不参与 ⇒ 快照里不能出现 0 分或 50 分。"""
    svc = _service(db_session)
    await svc.capture_today()

    snaps = await SnapshotRepository(db_session).list_recent(5)
    assert len(snaps) == 1
    assert snaps[0].flow_index is None, "没数据 ≠ 0 分"
    assert snaps[0].flow_detail is None


# ───────────────────── 2. 整面不可用（score=None） ─────────────────────


async def test_整面不可用时面分存NULL而不是0(db_session: AsyncSession) -> None:
    """一个因子都没取到读数 ⇒ 整面 score=None、factors=[] ⇒ 快照两列都存 NULL。"""
    svc = _service(db_session, flow=FakeFlow(None, []))
    await svc.capture_today()

    snaps = await SnapshotRepository(db_session).list_recent(5)
    assert snaps[0].flow_index is None, "整面不可用必须存 NULL（0 会被读成极度利空）"
    assert snaps[0].flow_detail is None


# ───────────────────── 3. 正常有分 ─────────────────────


async def test_有分时面分与明细都落库(db_session: AsyncSession) -> None:
    svc = _service(
        db_session,
        flow=FakeFlow(41.9, [_factor("cot_gold_net", 22.5), _factor("us_liq_net", 69.6)]),
    )
    await svc.capture_today()

    snaps = await SnapshotRepository(db_session).list_recent(5)
    assert snaps[0].flow_index == pytest.approx(41.9)

    detail = json.loads(snaps[0].flow_detail)
    assert set(detail) == {"cot_gold_net", "us_liq_net"}
    assert detail["us_liq_net"]["score"] == pytest.approx(69.6)
    assert detail["cot_gold_net"]["data_date"] == "2026-09-30"
    assert detail["us_liq_net"]["unit"] == "%"
    assert detail["us_liq_net"]["direction"] == "neutral"


# ───────────────────── 4. 同日重复捕获会更新新列（白名单陷阱） ─────────────────────


async def test_同日重复捕获会更新资金流两列(db_session: AsyncSession) -> None:
    """仓储 update 分支有**硬编码白名单** —— 漏加新列 ⇒ 当日第二次捕获不更新。

    V0.79.0 的 ``tech_detail`` 就踩过（API 已有值、库里仍是 NULL）。
    """
    repo = SnapshotRepository(db_session)
    svc = _service(db_session, flow=FakeFlow(41.9, [_factor("cot_gold_net", 22.5)]))
    await svc.capture_today()

    # 换成另一组读数再捕获一次（同日 ⇒ update 分支）。
    # ⚠ 必须先失效 served_cache —— ``TrendService.analyze`` 命中当日缓存就原样返回，
    # 不失效的话第二次捕获拿到的还是第一份结果（测的是缓存，不是 update 分支）。
    TrendService.invalidate_cached_results()
    svc2 = _service(db_session, flow=FakeFlow(77.7, [_factor("cot_gold_net", 88.8)]))
    await svc2.capture_today()

    snaps = await repo.list_recent(5)
    assert len(snaps) == 1, "同日重复捕获不应新增行"
    assert snaps[0].flow_index == pytest.approx(77.7), "新列没进 update 白名单 ⇒ 仍是旧值"
    assert json.loads(snaps[0].flow_detail)["cot_gold_net"]["score"] == pytest.approx(88.8)


# ───────────────────── 5. 老库升级路径 ─────────────────────


def test_db_migrate_declares_flow_columns() -> None:
    """``db_migrate.py`` 的幂等补列表须含两列（老库路径的必需项）。

    ⚠ ``main.py`` 启动时仍会调 ``ensure_sqlite_columns`` —— 老库走这条路时
    若不补列，ORM 的 ``SELECT`` 会直接报 ``no such column: flow_index``。
    """
    from app.utils.db_migrate import COLUMN_MIGRATIONS

    cols = dict((name, (typ, dflt)) for name, typ, dflt in COLUMN_MIGRATIONS["daily_snapshots"])
    assert "flow_index" in cols, "老库经 db_migrate 升级时必须补上该列"
    assert cols["flow_index"][0] == "FLOAT"
    assert "flow_detail" in cols, "老库经 db_migrate 升级时必须补上该列"
    assert cols["flow_detail"][0] == "TEXT"


def test_db_migrate_flow_columns_default_null() -> None:
    """⚠ 两列的默认值必须是 NULL —— 不能是 0。

    ``flow_index`` 回填 0 会被读成「资金正在撤离黄金」（极度利空），
    而真相是「历史行没这个面」。``news_index`` 当年用 50 是因为消息面
    天天打分、历史行也有真值；资金流面**今天才开始攒历史**（§4.5 回测网格不动）。
    """
    from app.utils.db_migrate import COLUMN_MIGRATIONS

    cols = dict((name, (typ, dflt)) for name, typ, dflt in COLUMN_MIGRATIONS["daily_snapshots"])
    assert cols["flow_index"][1].upper() == "NULL"
    assert cols["flow_detail"][1].upper() == "NULL"


def test_migration_file_exists_and_is_idempotent() -> None:
    """迁移文件须存在、带幂等探测（避免「已补列的老库」升级失败）。"""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    f = root / "migrations" / "versions" / "r2s3t4u5v6w_add_flow_to_daily_snapshots.py"
    assert f.exists(), "迁移文件缺失"
    src = f.read_text(encoding="utf-8")
    assert "_columns" in src, "迁移必须先探测列是否存在（保证可重复执行）"
    assert "down_revision" in src and "n2o3p4q5r6a1" in src
