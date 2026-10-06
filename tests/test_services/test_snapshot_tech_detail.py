"""快照落技术面 5 维度明细（V0.79.0 · 任务 #162）。

背景
----
``daily_snapshots.tech_index`` 是「5 个子维度分 × 各自权重」的**最终加权和，
拆不回去**；而 Step G 要在回测里扫描技术面内部权重（``trend_5`` 网格）
⇒ 必须把子维度原始分落库。

对比：宏观侧不需要额外列 —— ``macro_detail`` 里已经存了 5 个因子的 ``score``。

⚠ 本文件锁死三条纪律：

1. **只落 score 非 None 的维度** —— 数据不足的维度**不可用 50 兜底**
   （V0.78.0 Step D：数据不足 ≠ 中性），缺失即键不存在；
2. **列可空且历史不回填** —— 上游 K 线只覆盖 24 条历史快照中的 16-17 天；
   读到 None 必须**显式跳过**，**绝不可用邻近日期顶替**（伪造历史）；
3. **技术面全部不可用时落 NULL**（而非空 JSON / 全 50）。
"""

from __future__ import annotations

import json

from app.schemas.snapshot import SnapshotOut


class _Ind:
    """``TrendIndicatorOut`` 替身。"""

    def __init__(self, name: str, score: float | None, weight: float, contribution: float | None):
        self.name = name
        self.score = score
        self.weight = weight
        self.contribution = contribution


class _FakeTrend:
    """``TrendService`` 替身：返回固定 indicators 的 ``TrendOut``。"""

    def __init__(self, indicators: list) -> None:
        self._indicators = indicators

    async def analyze(self, days: int = 60, target: str = "ny") -> _FakeTrendOut:
        return _FakeTrendOut(self._indicators)


class _MacroFactor:
    """``MacroFactorOut`` 替身（``macro_detail`` JSON 的元素）。"""

    def __init__(self, key: str) -> None:
        from app.schemas.common import DirectionSignal

        self.key = key
        self.value = "1.0"
        self.score = 50.0
        self.unit = "%"
        self.data_date = "2026-10-06"
        self.direction = DirectionSignal.NEUTRAL


class _Macro:
    score = 50.0

    def __init__(self) -> None:
        # 列表放 __init__：类属性里的可变值会共享状态（RUF012）
        self.factors = [_MacroFactor("dxy")]


class _News:
    score = 50.0


class _Metrics:
    end_price = 9.9
    change_pct = 0.1
    high = 10.0
    low = 9.8
    ma20 = 9.85
    ma40 = 9.7

    def __init__(self) -> None:
        from app.schemas.common import DirectionSignal

        self.direction = DirectionSignal.BULLISH


class _FakeTrendOut:
    """``TrendOut`` 替身 —— ⚠ 枚举须从真实模块导入（``schemas/market`` 而非 models）。"""

    def __init__(self, indicators: list) -> None:
        from app.schemas.market import TrendIndexLevel

        self.symbol = "518880"
        self.name = "黄金ETF华安"
        self.metrics = _Metrics()
        self.macro = _Macro()
        self.news = _News()
        self.indicators = indicators
        self.index = type("_I", (), {"score": 50.0, "level": TrendIndexLevel.SIDEWAYS})()


class _Captured:
    """捕获 ``DailySnapshot(...)`` 构造参数的替身仓储。"""

    def __init__(self) -> None:
        self.kwargs: dict = {}

    async def upsert(self, snapshot) -> None:
        self.kwargs = {k: v for k, v in vars(snapshot).items() if not k.startswith("_sa_")}


class _Session:
    async def execute(self, stmt):
        class _R:
            def scalar_one_or_none(self_inner):
                return None

        return _R()


def _service(indicators: list[_Ind]) -> tuple[object, _Captured]:
    from app.services.snapshot import DailySnapshotService

    repo = _Captured()
    svc = DailySnapshotService(repo=repo, trend=_FakeTrend(indicators))  # type: ignore[arg-type]
    return svc, repo


def _all_valid() -> list[_Ind]:
    return [
        _Ind("结构", 62.0, 0.30, 18.6),
        _Ind("动量", 45.0, 0.20, 9.0),
        _Ind("支撑", 51.0, 0.20, 10.2),
        _Ind("动能", 38.0, 0.15, 5.7),
        _Ind("回撤", 70.0, 0.15, 10.5),
    ]


# ─────────────── 纪律 1：只落 score 非 None 的维度 ───────────────


def test_all_dims_persisted_when_valid() -> None:
    """5 维度全部有效 ⇒ JSON 含 5 键，且带 score/weight/contribution。"""
    import asyncio

    svc, repo = _service(_all_valid())
    asyncio.run(svc.capture_today())

    detail = repo.kwargs["tech_detail"]
    assert detail is not None
    obj = json.loads(detail)
    assert set(obj) == {"结构", "动量", "支撑", "动能", "回撤"}
    assert obj["结构"]["score"] == 62.0
    assert obj["结构"]["weight"] == 0.30
    assert "contribution" in obj["结构"]


def test_none_score_dims_are_excluded_not_defaulted() -> None:
    """★ score=None 的维度**不出现在 JSON 里**（绝不用 50 兜底）。"""
    import asyncio

    inds = _all_valid()
    inds[1] = _Ind("动量", None, 0.20, None)  # 数据不足
    svc, repo = _service(inds)
    asyncio.run(svc.capture_today())

    obj = json.loads(repo.kwargs["tech_detail"])
    assert "动量" not in obj, "数据不足的维度不得出现，更不得填 50"
    assert set(obj) == {"结构", "支撑", "动能", "回撤"}
    # 且落库的 tech_index 只由有效维度贡献
    assert repo.kwargs["tech_index"] == round(
        sum(i.contribution for i in inds if i.score is not None), 1
    )


def test_no_dim_filled_with_neutral_50() -> None:
    """⚠ 锁死「不用 50 兜底」：JSON 里任何 score 都不应是 50。"""
    import asyncio

    inds = _all_valid()
    inds[0] = _Ind("结构", None, 0.30, None)
    svc, repo = _service(inds)
    asyncio.run(svc.capture_today())

    obj = json.loads(repo.kwargs["tech_detail"])
    for name, v in obj.items():
        assert v["score"] != 50.0 or name == "支撑", f"{name} 疑似被兜底成中性 50"


# ─────────────── 纪律 2：列可空、历史不回填 ───────────────


def test_all_dims_unavailable_persists_null() -> None:
    """5 维度全部不可用 ⇒ tech_detail 为 NULL（而非空 JSON / 全 50）。"""
    import asyncio

    inds = [
        _Ind(n, None, w, None)
        for n, w in [("结构", 0.30), ("动量", 0.20), ("支撑", 0.20), ("动能", 0.15), ("回撤", 0.15)]
    ]
    svc, repo = _service(inds)
    asyncio.run(svc.capture_today())

    assert repo.kwargs["tech_detail"] is None, "全不可用时必须落 NULL，不能是 '{}' 或全 50"
    assert repo.kwargs["tech_index"] == 0.0


def test_schema_accepts_null_tech_detail() -> None:
    """历史行 tech_detail=None ⇒ schema 校验通过（不报错、不填默认值）。"""
    snap = SnapshotOut(
        snapshot_date="2026-08-30",
        symbol="518880",
        name="黄金ETF华安",
        close=9.9,
        change_pct=0.1,
        high=10.0,
        low=9.8,
        ma20=9.85,
        ma40=9.7,
        direction="sideways",
        tech_index=50.0,
        macro_index=50.0,
        news_index=50.0,
        trend_index=50.0,
        index_level="SIDEWAYS",
        tech_detail=None,
    )
    assert snap.tech_detail is None


def test_schema_default_tech_detail_is_none() -> None:
    """⚠ 默认值必须是 None（保守侧）：漏传时不能宣称「有子维度分」。"""
    from app.schemas.snapshot import SnapshotOut as S

    fields = S.model_fields
    assert "tech_detail" in fields
    assert fields["tech_detail"].default is None


# ─────────────── 迁移声明 ───────────────


def test_db_migrate_declares_tech_detail() -> None:
    """``db_migrate.py`` 的幂等补列表须含 tech_detail（老库路径的必需项）。"""
    from app.utils.db_migrate import COLUMN_MIGRATIONS

    cols = dict((name, (typ, dflt)) for name, typ, dflt in COLUMN_MIGRATIONS["daily_snapshots"])
    assert "tech_detail" in cols, "老库经 db_migrate 升级时必须补上该列"
    assert cols["tech_detail"][0] == "TEXT"


def test_migration_file_exists_and_is_idempotent() -> None:
    """迁移文件须存在、带幂等探测（避免「已补列的老库」升级失败）。"""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    f = root / "migrations" / "versions" / "e1f2a3b4c5d6_snapshot_tech_detail.py"
    assert f.exists(), "迁移文件缺失"
    src = f.read_text(encoding="utf-8")
    assert "_column_exists" in src, "迁移必须先探测列是否存在（保证可重复执行）"
    assert "down_revision" in src and "d5f81a3c9b47" in src


def test_null_and_empty_json_are_distinguishable() -> None:
    """⚠ NULL（无子维度分）与 ``{}``（空对象）语义不同，消费方须能区分。

    - ``None`` ⇒ 该日**未落** tech_detail（历史行 / 全维度不可用）
    - ``"{}"`` ⇒ 落了但一个维度都没有（逻辑上不该出现，若出现即为 bug）

    两者都**不可**被解读为「维度分都是 0」或「都是 50」。
    """
    null_row = SnapshotOut(**_base_kwargs(tech_detail=None))
    empty_row = SnapshotOut(**_base_kwargs(tech_detail="{}"))

    assert null_row.tech_detail is None
    assert empty_row.tech_detail == "{}"
    assert null_row.tech_detail != empty_row.tech_detail
    # 两者都不得被解析成「有可用的 0 分」
    assert json.loads(empty_row.tech_detail or "{}") == {}


def _base_kwargs(**over) -> dict:
    from datetime import date

    base = {
        "snapshot_date": date(2026, 10, 6),
        "symbol": "518880",
        "name": "黄金ETF华安",
        "close": 9.9,
        "change_pct": 0.1,
        "high": 10.0,
        "low": 9.8,
        "ma20": 9.85,
        "ma40": 9.7,
        "direction": "sideways",
        "tech_index": 50.0,
        "macro_index": 50.0,
        "news_index": 50.0,
        "trend_index": 50.0,
        "index_level": "SIDEWAYS",
    }
    base.update(over)
    return base


# ─────────────── upsert 白名单：新列必须同时覆盖 insert 与 update 两条路径 ───────────────


def test_upsert_update_path_includes_tech_detail() -> None:
    """★ 同日重复捕获走 **update** 分支 ⇒ 字段白名单必须含 ``tech_detail``。

    实测踩坑（2026-10-06）：API 返回了 tech_detail 但库里仍为 NULL ——
    因当日快照已存在 ⇒ 走 update 分支，而该分支的字段列表是**硬编码白名单**，
    新列不在其中就永远不更新。**新列的写入路径有两条**（insert / update），
    只改一处必然漏，且现象是「接口有、库里无」，极易误判为序列化问题。
    """
    import inspect

    from app.repositories.snapshot import SnapshotRepository

    src = inspect.getsource(SnapshotRepository.upsert)
    assert '"tech_detail"' in src, "update 分支的字段白名单缺 tech_detail"


def test_upsert_update_path_covers_both_insert_and_update() -> None:
    """两条路径都须能写入：insert 走整对象、update 走白名单。"""
    import inspect

    from app.repositories.snapshot import SnapshotRepository

    src = inspect.getsource(SnapshotRepository.upsert)
    assert "self._session.add(snapshot)" in src, "insert 分支缺失"
    assert "setattr(existing" in src, "update 分支缺失"
    # 白名单里不能漏关键字段
    for field in ("tech_index", "macro_detail", "tech_detail"):
        assert f'"{field}"' in src, f"update 白名单缺 {field}"
