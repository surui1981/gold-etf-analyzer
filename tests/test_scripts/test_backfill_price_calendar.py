"""``scripts/backfill_price_calendar.py`` 单元测试（V0.127.0 · 金价区间预测的前置）。

这个脚本会**批量改写生产库的价格日历** ⇒ 它的两条失效路径都是静默的：

1. **连错库** —— ``get_settings()`` 读的是 ``.env``（开发 SQLite），
   而 ``app.repositories.db`` 在**模块导入时**就按 ``settings.database_url`` 建好 engine
   ⇒ 注入 ``DATABASE_URL`` 晚了，人以为写生产、其实写开发库（或反过来）。
   ⇒ 本文件用 **AST**（不是文本匹配）断言 ``main()`` 里注入调用**先于** ``app.config`` 的导入。
   ⚠ 用 AST 而不是 grep 是有意的：注释里写一行假的调用顺序就能骗过文本断言
   （仓库铁律：断言必须先剥注释）。

2. **写入编造的 mock 价格** —— ``MarketDataRepository.get_us_gold_history``
   取数失败时会**静默降级为 mock**；mock 价格入库 ⇒ 回测/区间预测基于编造的价格
   给出看似正常的结论，比「无数据」危险得多。
   ⇒ 本文件断言 mock 源时脚本**拒绝写入并返回非 0**。

策略：全部离线，不联网、不碰数据库 —— 用假仓储替身 + ``monkeypatch``。
"""

from __future__ import annotations

import ast
import inspect
import os
import textwrap
from datetime import date

import pytest

from scripts import backfill_price_calendar as bpc

# ──────────────── inject_database_url ────────────────


class TestInjectDatabaseUrl:
    """``DATABASE_URL`` 注入：必须在导入 ``app.*`` 之前生效。"""

    def test_env_file_space_separated(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        f = tmp_path / ".env.mysql"
        f.write_text("DATABASE_URL=mysql+asyncmy://u:p@127.0.0.1:3306/d\n", encoding="utf-8")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        bpc.inject_database_url(["--env-file", str(f)])
        assert os.environ["DATABASE_URL"] == "mysql+asyncmy://u:p@127.0.0.1:3306/d"

    def test_env_file_equals_form(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        f = tmp_path / ".env.mysql"
        f.write_text("OTHER=1\nDATABASE_URL='sqlite+aiosqlite:///./x.db'\n", encoding="utf-8")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        bpc.inject_database_url([f"--env-file={f}"])
        # 引号必须被剥掉，否则 SQLAlchemy 会把带引号的整串当 URL
        assert os.environ["DATABASE_URL"] == "sqlite+aiosqlite:///./x.db"

    def test_database_url_forms(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        bpc.inject_database_url(["--database-url", "sqlite+aiosqlite:///./a.db"])
        assert os.environ["DATABASE_URL"] == "sqlite+aiosqlite:///./a.db"
        monkeypatch.delenv("DATABASE_URL", raising=False)
        bpc.inject_database_url(["--database-url=sqlite+aiosqlite:///./b.db"])
        assert os.environ["DATABASE_URL"] == "sqlite+aiosqlite:///./b.db"

    def test_database_url_wins_over_env_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        f = tmp_path / ".env.mysql"
        f.write_text("DATABASE_URL=sqlite+aiosqlite:///./from-file.db\n", encoding="utf-8")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        bpc.inject_database_url(
            ["--env-file", str(f), "--database-url", "sqlite+aiosqlite:///./direct.db"]
        )
        assert os.environ["DATABASE_URL"] == "sqlite+aiosqlite:///./direct.db"

    def test_missing_env_file_exits(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(SystemExit):
            bpc.inject_database_url(["--env-file", str(tmp_path / "nope.env")])

    def test_env_file_without_database_url_exits(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        f = tmp_path / ".env"
        f.write_text("OTHER=1\n", encoding="utf-8")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(SystemExit):
            bpc.inject_database_url(["--env-file", str(f)])

    def test_no_flag_leaves_env_untouched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./keep.db")
        bpc.inject_database_url(["--target", "ny", "--deep"])
        assert os.environ["DATABASE_URL"] == "sqlite+aiosqlite:///./keep.db"


# ──────────────── 导入顺序（AST 守卫） ────────────────


class TestImportOrderGuard:
    """注入必须**先于** ``app.config`` 的导入 —— 否则会连错库。"""

    def test_injection_precedes_app_import(self) -> None:
        src = textwrap.dedent(inspect.getsource(bpc.main))
        tree = ast.parse(src)

        inject_lines = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "inject_database_url"
        ]
        import_lines = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "app.config"
        ]
        assert inject_lines, "main() 里找不到 inject_database_url 调用"
        assert import_lines, "main() 里找不到 app.config 的导入"
        assert min(inject_lines) < min(import_lines), (
            "DATABASE_URL 的注入必须早于 app.config 的导入 —— "
            "app.repositories.db 在导入期就按 settings.database_url 建好 engine"
        )

    def test_guard_is_not_satisfiable_by_a_comment(self) -> None:
        """反向验证：把注入调用挪到导入之后 ⇒ 断言必须变红。

        ⚠ 这是「断言必须反向验证」纪律的落地：断言只认 AST 节点，
        注释里写一行 ``inject_database_url(...)`` 不该能骗过它。
        """
        src = textwrap.dedent(inspect.getsource(bpc.main))
        # 在源码里插一行注释，声称先注入
        tampered = src.replace(
            "inject_database_url(sys.argv[1:])",
            "# inject_database_url(sys.argv[1:])  # 注释里写一遍不算",
            1,
        )
        tree = ast.parse(tampered)
        inject_lines = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "inject_database_url"
        ]
        assert inject_lines == [], "注释里的调用不该被 AST 当成真实调用"


# ──────────────── _redact / _dedupe ────────────────


class TestRedact:
    def test_masks_password(self) -> None:
        out = bpc._redact("mysql+asyncmy://gold_etf_app:s3cr3t@127.0.0.1:3306/gold_etf")
        assert "s3cr3t" not in out
        assert out == "mysql+asyncmy://gold_etf_app:***@127.0.0.1:3306/gold_etf"

    def test_keeps_sqlite_untouched(self) -> None:
        url = "sqlite+aiosqlite:///./data/gold_etf.db"
        assert bpc._redact(url) == url


class TestDedupe:
    def test_same_date_keeps_last(self) -> None:
        bars = [("2026-01-02", 10.0), ("2026-01-02", 11.0)]
        assert bpc._dedupe(bars) == [("2026-01-02", 11.0)]

    def test_drops_non_positive_and_none(self) -> None:
        bars = [("2026-01-02", 10.0), ("2026-01-03", 0.0), ("2026-01-04", -1.0)]
        assert bpc._dedupe(bars) == [("2026-01-02", 10.0)]

    def test_sorted_ascending(self) -> None:
        bars = [("2026-01-03", 3.0), ("2026-01-02", 2.0)]
        assert bpc._dedupe(bars) == [("2026-01-02", 2.0), ("2026-01-03", 3.0)]


def test_target_fetchers_cover_three_markets() -> None:
    assert bpc._TARGET_FETCHERS == {
        "ny": "get_us_gold_history",
        "etf": "get_gold_history",
        "gram": "get_gold_gram_history",
    }


# ──────────────── _run 的两条失效路径 ────────────────


class _FakeBar:
    def __init__(self, d: str, c: float) -> None:
        self.date = date.fromisoformat(d)
        self.close = c


class _FakeMarketRepo:
    """``MarketDataRepository`` 替身。"""

    source = "live"

    def __init__(self) -> None:
        self.written_targets: list[str] = []

    def source_status(self) -> dict:
        return {"ny": self.source}

    async def get_us_gold_history(self, days: int = 90) -> list[_FakeBar]:
        return [
            _FakeBar("2026-01-02", 100.0),
            _FakeBar("2026-01-05", 101.0),
            _FakeBar("2026-01-06", 102.0),
        ]


class _FakeGoldRepo:
    """``GoldPriceRepository`` 替身：记录写入。"""

    def __init__(self, session=None) -> None:
        self.upserts: list[tuple] = []

    async def count(self, target: str) -> int:
        return 0

    async def latest_before(self, target: str, d):
        return None

    async def list_range(self, target: str) -> list:
        return []

    async def upsert_many(self, target: str, bars, source: str) -> int:
        self.upserts.append((target, list(bars), source))
        return len(bars)


class _FakeSessionFactory:
    def __init__(self, gold: _FakeGoldRepo) -> None:
        self.gold = gold

    def __call__(self):
        class _Ctx:
            async def __aenter__(self_inner):
                return None

            async def __aexit__(self_inner, *exc):
                return False

        return _Ctx()


@pytest.fixture()
def _patched(monkeypatch: pytest.MonkeyPatch):
    """把真实仓储替身装上去，并交回替身供断言。"""

    def _install(source: str):
        market = _FakeMarketRepo()
        market.source = source
        gold = _FakeGoldRepo()
        monkeypatch.setattr("app.repositories.market_data.MarketDataRepository", lambda: market)
        monkeypatch.setattr("app.repositories.review.GoldPriceRepository", lambda session: gold)
        monkeypatch.setattr("app.repositories.db.async_session_factory", _FakeSessionFactory(gold))
        return market, gold

    return _install


class TestRunGuards:
    @pytest.mark.asyncio
    async def test_mock_source_is_refused(self, _patched) -> None:
        """mock 行情 ⇒ 拒绝写入（返回 3），且一个格子都不写。"""
        _market, gold = _patched("mock")
        rc = await bpc._run("ny", days=90, apply=True, chunk_size=1000)
        assert rc == 3
        assert gold.upserts == []

    @pytest.mark.asyncio
    async def test_unknown_source_is_refused(self, _patched) -> None:
        """来源无法确定（空串）⇒ 同样拒绝 —— 不兜底成 live。"""
        _patched("")
        rc = await bpc._run("ny", days=90, apply=True, chunk_size=1000)
        assert rc == 3

    @pytest.mark.asyncio
    async def test_trusted_source_dry_run_writes_nothing(self, _patched) -> None:
        """干跑（apply=False）⇒ 不写库。"""
        _market, gold = _patched("live")
        rc = await bpc._run("ny", days=90, apply=False, chunk_size=1000)
        assert rc == 0
        assert gold.upserts == []

    @pytest.mark.asyncio
    async def test_trusted_source_apply_writes_in_chunks(self, _patched) -> None:
        """真写 ⇒ 分块 upsert，source 原样带出。"""
        _market, gold = _patched("live")
        rc = await bpc._run("ny", days=90, apply=True, chunk_size=2)
        assert rc == 0
        assert len(gold.upserts) == 2  # 3 根 / 每块 2 根
        assert sum(len(b) for _t, b, _s in gold.upserts) == 3
        assert gold.upserts[0][2] == "live"

    @pytest.mark.asyncio
    async def test_too_few_bars_aborts(self, monkeypatch: pytest.MonkeyPatch, _patched) -> None:
        """取数不足 2 根 ⇒ 放弃（返回 2），不写。"""
        _market, gold = _patched("live")

        class _Market(_FakeMarketRepo):
            async def get_us_gold_history(self, days: int = 90):
                return [_FakeBar("2026-01-02", 100.0)]

        monkeypatch.setattr("app.repositories.market_data.MarketDataRepository", lambda: _Market())
        rc = await bpc._run("ny", days=90, apply=True, chunk_size=1000)
        assert rc == 2
        assert gold.upserts == []
