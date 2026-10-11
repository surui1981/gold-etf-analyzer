"""``scripts/import_central_bank.py`` 单元测试（V0.88.0 维护线覆盖率扩充）。

目标覆盖率：22% → **80%+**。

策略（基于 V0.88.0 计划）：
- **不**用 subprocess 跑 ``main()``（CLI smoke 在门禁里跑更稳，详见 plan R5）；
  本测试只覆盖 ``upsert_rows`` + ``run_import`` 函数体。
- ``main()`` 的 ``print`` / ``argparse`` / ``sys.exit(2)`` 分支接受作为未覆盖行
  （占总行 ~35/135，对覆盖率目标无明显收益）。
- mock 入口：``monkeypatch.setattr("app.scripts.import_central_bank.build_full_dataset", ...)``
  （V0.87.0 时 ``tests/test_services/test_scheduler.py`` 已验证该字符串路径可用）。
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

import pytest

from app.repositories import central_bank_data
from app.repositories.central_bank_data import QuarterlyPurchase
from app.scripts import import_central_bank


def _make_row(
    iso: str = "CHN",
    name: str = "中国",
    quarter: str = "2026Q1",
    tonnes: float = 10.0,
    source: str = "WGC GDT Q2 2026 H1",
) -> QuarterlyPurchase:
    """构造单行测试数据（默认值走最常见 happy path）。"""
    return QuarterlyPurchase(
        country_iso=iso,
        country_name=name,
        quarter=quarter,
        tonnes_net=tonnes,
        source=source,
        data_date=date(2026, 3, 31),
    )


# ──────────────── upsert_rows ────────────────


class TestUpsertRows:
    """``upsert_rows`` 写入 / 冲突替换 / 空入参。"""

    async def test_empty_rows_returns_zero(self) -> None:
        """入参空 list：直接返回 0（不打开 session.begin）。"""
        result = await import_central_bank.upsert_rows([])
        assert result == 0

    async def test_insert_new_rows(self, db_session) -> None:
        """插入新行：返回受影响行数（≥ 1）。"""
        rows = [_make_row(iso="CHN", quarter="2026Q1")]
        n = await import_central_bank.upsert_rows(rows)
        assert n >= 1
        # 验证 DB 写入
        from sqlalchemy import select
        from app.models.central_bank import CentralBankPurchase

        result = await db_session.execute(
            select(CentralBankPurchase).where(CentralBankPurchase.country_iso == "CHN")
        )
        items = result.scalars().all()
        assert len(items) == 1
        assert items[0].country_name == "中国"
        assert items[0].tonnes_net == 10.0

    async def test_upsert_replaces_existing(self, db_session) -> None:
        """同 (country_iso, quarter) 已存在：覆盖（on_conflict_do_update）。

        第一次写入 10 t → 第二次写入 20 t → DB 应只剩 1 行且值为 20。
        """
        rows_first = [_make_row(iso="POL", quarter="2026Q1", tonnes=10.0)]
        await import_central_bank.upsert_rows(rows_first)

        rows_second = [_make_row(iso="POL", quarter="2026Q1", tonnes=20.0, name="波兰新名")]
        await import_central_bank.upsert_rows(rows_second)

        from sqlalchemy import select, func
        from app.models.central_bank import CentralBankPurchase

        result = await db_session.execute(
            select(func.count()).select_from(CentralBankPurchase).where(
                CentralBankPurchase.country_iso == "POL"
            )
        )
        count = result.scalar_one()
        assert count == 1, "冲突替换应保持 1 行"

        # 值更新为 20.0
        result = await db_session.execute(
            select(CentralBankPurchase).where(CentralBankPurchase.country_iso == "POL")
        )
        item = result.scalar_one()
        assert item.tonnes_net == 20.0
        assert item.country_name == "波兰新名"

    async def test_multiple_iso_quarter_combinations(self, db_session) -> None:
        """多条不同 (iso, quarter) 组合：DB 写入 N 行（无冲突）。"""
        rows = [
            _make_row(iso="CHN", quarter="2026Q1", tonnes=5.0),
            _make_row(iso="CHN", quarter="2026Q2", tonnes=7.0),
            _make_row(iso="POL", quarter="2026Q1", tonnes=3.0),
        ]
        n = await import_central_bank.upsert_rows(rows)
        assert n >= 3
        from sqlalchemy import select, func
        from app.models.central_bank import CentralBankPurchase
        result = await db_session.execute(
            select(func.count()).select_from(CentralBankPurchase)
        )
        assert result.scalar_one() == 3


# ──────────────── run_import ────────────────


class TestRunImport:
    """``run_import`` 完整流程：build_full_dataset → 过滤 → 落库 → 日志。"""

    async def test_run_import_no_data_returns_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """build_full_dataset 返回 [] 时：run_import 返回 0 + 记 error 日志。"""
        async def _empty():
            return []
        monkeypatch.setattr(
            import_central_bank, "build_full_dataset", _empty
        )

        result = await import_central_bank.run_import(include_manual=True)
        assert result == 0

    async def test_run_import_full_path(
        self, monkeypatch: pytest.MonkeyPatch, db_session
    ) -> None:
        """正常路径：build_full_dataset 返回 2 行 → upsert → DB 写入。"""
        rows = [
            _make_row(iso="CHN", quarter="2026Q1", tonnes=15.0),
            _make_row(iso="POL", quarter="2026Q1", tonnes=8.0, name="波兰"),
        ]
        async def _mock():
            return rows
        monkeypatch.setattr(
            import_central_bank, "build_full_dataset", _mock
        )

        n = await import_central_bank.run_import(include_manual=True)
        assert n >= 2

        from sqlalchemy import select, func
        from app.models.central_bank import CentralBankPurchase
        result = await db_session.execute(
            select(func.count()).select_from(CentralBankPurchase)
        )
        assert result.scalar_one() == 2

    async def test_run_import_excludes_manual_when_disabled(
        self, monkeypatch: pytest.MonkeyPatch, db_session
    ) -> None:
        """``include_manual=False``：过滤掉 source='WGC 月报估读' 的行。"""
        rows = [
            _make_row(iso="CHN", quarter="2026Q1", tonnes=15.0,
                      source="WGC GDT Q2 2026 H1"),
            _make_row(iso="UZB", quarter="2026Q1", tonnes=2.0,
                      name="乌兹别克斯坦", source="WGC 月报估读"),
        ]
        async def _mock():
            return rows
        monkeypatch.setattr(
            import_central_bank, "build_full_dataset", _mock
        )

        n = await import_central_bank.run_import(include_manual=False)
        assert n == 1, "应只 upsert 1 条 WGC GDT 行，过滤掉手工补丁"

        from sqlalchemy import select, func
        from app.models.central_bank import CentralBankPurchase
        result = await db_session.execute(
            select(func.count()).select_from(CentralBankPurchase)
        )
        assert result.scalar_one() == 1

    async def test_run_import_logs_summary(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """``run_import`` 完成后记一条 INFO 日志，含「导入完成：N 行」+ 国家数 + sources。"""
        rows = [
            _make_row(iso="CHN", quarter="2026Q1", tonnes=10.0),
            _make_row(iso="POL", quarter="2026Q1", tonnes=5.0, name="波兰"),
        ]
        async def _mock():
            return rows
        monkeypatch.setattr(
            import_central_bank, "build_full_dataset", _mock
        )

        with caplog.at_level("INFO"):
            await import_central_bank.run_import(include_manual=True)

        # 验证日志含「导入完成」
        log_text = "\n".join(r.message for r in caplog.records)
        assert "导入完成" in log_text
        assert "countries=2" in log_text


# ──────────────── build_full_dataset 端到端 mock（与 central_bank_data 测试协作） ────────────────


def test_build_full_dataset_is_callable() -> None:
    """``build_full_dataset`` 是异步函数（CLI + scheduler 都调用它）。"""
    import inspect
    assert inspect.iscoroutinefunction(central_bank_data.build_full_dataset)


# ──────────────── main() CLI 入口（V0.88.0 增量：补到 80%+） ────────────────


class TestMainCli:
    """``main()`` CLI 入口的 argparse + 打印 + dry_run / no_manual / 落库 三分支。

    通过 ``monkeypatch`` 注入：
    - ``sys.argv``：喂 argparse
    - ``sys.exit``：避免真正退出
    - ``build_full_dataset``：返回受控的行
    - ``run_import``：跳过真实 DB 写入（dry-run / 空数据场景）
    """

    async def test_main_dry_run_skips_db_write(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """``--dry-run``：打印预览 + 不调用 ``run_import``（不入库）。"""
        rows = [_make_row(iso="CHN", quarter="2026Q1", tonnes=10.0)]
        async def _mock():
            return rows
        monkeypatch.setattr(import_central_bank, "build_full_dataset", _mock)
        monkeypatch.setattr(import_central_bank, "run_import", AsyncMock(return_value=99))

        monkeypatch.setattr("sys.argv", ["import_central_bank", "--dry-run"])

        await import_central_bank.main()

        # 验证 run_import 没被调用（dry-run 应跳过落库）
        import_central_bank.run_import.assert_not_called()

        # 验证 stdout 含预期行
        captured = capsys.readouterr()
        assert "[import] rows=1" in captured.out
        assert "[import] dry-run" in captured.out

    async def test_main_no_manual_filters_out_manual_rows(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """``--no-manual``：rows 被过滤后再统计；run_import 仍被调用。"""
        rows = [
            _make_row(iso="CHN", quarter="2026Q1", tonnes=10.0,
                      source="WGC GDT Q2 2026 H1"),
            _make_row(iso="UZB", quarter="2026Q1", tonnes=2.0,
                      name="乌兹别克斯坦", source="WGC 月报估读"),
        ]
        async def _mock():
            return rows
        monkeypatch.setattr(import_central_bank, "build_full_dataset", _mock)
        monkeypatch.setattr(import_central_bank, "run_import", AsyncMock(return_value=1))

        monkeypatch.setattr("sys.argv", ["import_central_bank", "--no-manual"])

        await import_central_bank.main()

        # run_import 应被调用（默认非 dry-run）；include_manual=not args.no_manual=False
        import_central_bank.run_import.assert_awaited_once_with(include_manual=False)

        captured = capsys.readouterr()
        # 过滤后只剩 1 行 → countries=1
        assert "rows=1" in captured.out

    async def test_main_no_data_exits_with_code_2(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """build_full_dataset 返回 [] 时：``main()`` 调用 ``sys.exit(2)``。"""
        async def _empty():
            return []
        monkeypatch.setattr(import_central_bank, "build_full_dataset", _empty)

        # 替换 sys.exit（避免真退出 + 捕获退出码）
        exit_codes: list[int] = []
        def _fake_exit(code: int = 0):
            exit_codes.append(code)
            raise SystemExit(code)
        monkeypatch.setattr("sys.exit", _fake_exit)

        monkeypatch.setattr("sys.argv", ["import_central_bank"])

        with pytest.raises(SystemExit) as exc_info:
            await import_central_bank.main()
        assert exc_info.value.code == 2
        assert exit_codes == [2]

    async def test_main_full_path_prints_summary_and_calls_run_import(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
        db_session,
    ) -> None:
        """正常路径：build_full_dataset → stats 打印 → run_import(include_manual=True) → 落库。"""
        rows = [
            _make_row(iso="CHN", quarter="2026Q1", tonnes=15.0),
            _make_row(iso="POL", quarter="2026Q2", tonnes=8.0, name="波兰"),
        ]
        async def _mock():
            return rows
        monkeypatch.setattr(import_central_bank, "build_full_dataset", _mock)

        monkeypatch.setattr("sys.argv", ["import_central_bank"])

        await import_central_bank.main()

        captured = capsys.readouterr()
        # 验证 4 行打印
        assert "[import] rows=2 countries=2" in captured.out
        assert "[import] quarter range:" in captured.out
        assert "[import] sources:" in captured.out
        assert "[import] T12M top buyers:" in captured.out
        assert "upserted" in captured.out

        # 验证 DB 真的写入（main 全路径）
        from sqlalchemy import select, func
        from app.models.central_bank import CentralBankPurchase
        result = await db_session.execute(
            select(func.count()).select_from(CentralBankPurchase)
        )
        assert result.scalar_one() == 2