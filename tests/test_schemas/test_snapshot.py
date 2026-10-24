"""``schemas/snapshot.py`` 单测（V0.90.0 维护线）。

目标：覆盖 ``SnapshotOut.macro_detail`` 反序列化 validator 的全分支。

策略：
- 纯 Pydantic，**不**依赖 DB / 网络 / app fixture
- 直接构造 ``model_validate(obj)`` 验证 dict / str / None / 损坏 JSON
  四类入参路径
"""

from __future__ import annotations

from datetime import date

import pytest

from app.models.snapshot import DailySnapshot
from app.schemas.snapshot import SnapshotListOut, SnapshotOut

# ──────────────── 测试 fixture：DailySnapshot ORM 模拟 ────────────────


def _make_snapshot_row(**overrides) -> DailySnapshot:
    """构造一个 DailySnapshot ORM 行（含 macro_detail 默认 JSON 字符串）。"""
    defaults = {
        "snapshot_date": date(2026, 10, 1),
        "symbol": "518880",
        "name": "黄金ETF华安",
        "close": 5.5,
        "change_pct": 1.2,
        "high": 5.6,
        "low": 5.4,
        "ma20": 5.45,
        "ma40": 5.40,
        "direction": "up",
        "tech_index": 65.0,
        "macro_index": 58.0,
        "news_index": 60.0,
        "trend_index": 61.0,
        "index_level": "偏多",
        "tech_detail": None,
        "macro_detail": '{"DXY": {"value": 104.5, "score": -10, "direction": "up"}}',
        "data_source": "live",
    }
    defaults.update(overrides)
    return DailySnapshot(**defaults)


# ──────────────── SnapshotOut.macro_detail 反序列化 ────────────────


class TestMacroDetailDeserialization:
    """V0.90.0 schema bug fix：``macro_detail`` 必须被 Pydantic 白名单保留 + 反序列化。"""

    def test_macro_detail_str_json_is_parsed_to_dict(self) -> None:
        """从 ORM 读出的 str JSON 字符串 → 自动反序列化为 dict（V0.90.0 修复的核心路径）。"""
        row = _make_snapshot_row(macro_detail='{"DXY": {"value": 104.5}, "US10Y": {"value": 4.2}}')
        out = SnapshotOut.model_validate(row)

        assert isinstance(out.macro_detail, dict)
        assert out.macro_detail["DXY"]["value"] == 104.5
        assert out.macro_detail["US10Y"]["value"] == 4.2

    def test_macro_detail_dict_input_is_passed_through(self) -> None:
        """dict 入参：直接透传（不重新 JSON 化）。"""
        out = SnapshotOut.model_validate(
            _make_snapshot_row(macro_detail={"DXY": {"value": 104.5}, "CPI": {"value": 3.1}})
        )
        assert out.macro_detail == {"DXY": {"value": 104.5}, "CPI": {"value": 3.1}}

    def test_macro_detail_none_is_preserved(self) -> None:
        """None 入参：保持 None（与 tech_detail 历史 NULL 同语义）。"""
        out = SnapshotOut.model_validate(_make_snapshot_row(macro_detail=None))
        assert out.macro_detail is None

    def test_macro_detail_corrupt_json_returns_none_and_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """损坏 JSON（V0.79.0 之前可能的脏数据）：log warning + 置 None（不兜底为 {}）。

        V0.78.0 Step D 纪律：「数据不足 ≠ 中性」，不应用空 dict 假装有数据。
        """
        row = _make_snapshot_row(macro_detail="{invalid json")
        with caplog.at_level("WARNING"):
            out = SnapshotOut.model_validate(row)

        assert out.macro_detail is None
        # 验证日志含「JSON 反序列化失败」+ 「置 None」
        assert any("JSON 反序列化失败" in r.message for r in caplog.records)

    def test_macro_detail_non_dict_parsed_returns_none(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """JSON 解析成功但不是 dict（罕见脏数据如顶层 list）：置 None + warning。

        ``macro_detail`` 的语义是「因子名 → 因子明细」的字典；list 不是合法形态。
        """
        row = _make_snapshot_row(macro_detail="[1, 2, 3]")  # 合法 JSON 但不是 dict
        with caplog.at_level("WARNING"):
            out = SnapshotOut.model_validate(row)
        assert out.macro_detail is None
        assert any(
            "顶层非 dict" in r.message or "JSON 反序列化失败" in r.message for r in caplog.records
        )

    def test_macro_detail_unexpected_type_returns_none(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """非 str/dict/None 类型（如 int / list 原始值）：置 None + warning。"""
        row = _make_snapshot_row(macro_detail=42)  # 数字 —— 完全不预期
        with caplog.at_level("WARNING"):
            out = SnapshotOut.model_validate(row)
        assert out.macro_detail is None
        assert any("非预期类型" in r.message for r in caplog.records)

    def test_macro_detail_empty_dict_is_preserved(self) -> None:
        """空 dict ``{}``：透传为 ``{}``（与 None 区分 —— 空 dict 是「有因子但全为 0」合法态）。"""
        row = _make_snapshot_row(macro_detail={})
        out = SnapshotOut.model_validate(row)
        assert out.macro_detail == {}

    def test_macro_detail_empty_string_returns_none(self) -> None:
        """空字符串 ``""``：JSON.loads 返回 None → 通过 is None 检查。"""
        row = _make_snapshot_row(macro_detail="")
        out = SnapshotOut.model_validate(row)
        # 空字符串 json.loads → 不是 dict（是 NoneType）→ 走 corrupted 分支
        # None 不是 dict → 应该返回 None
        assert out.macro_detail is None


# ──────────────── SnapshotOut 既有字段不变 ────────────────


class TestExistingFieldsUnchanged:
    """V0.90.0 schema fix 必须**只增不减**——已有字段行为不变（防回归）。"""

    def test_tech_detail_remains_str_type(self) -> None:
        """``tech_detail`` 保持 ``str | None``（V0.79.0 任务 #162 既有契约不破坏）。"""
        out = SnapshotOut.model_validate(_make_snapshot_row(tech_detail='{"trend": {"score": 70}}'))
        assert isinstance(out.tech_detail, str)
        assert out.tech_detail == '{"trend": {"score": 70}}'

    def test_tech_detail_none_preserved(self) -> None:
        """``tech_detail=None``（V0.79.0 历史 24 条）：保持 None。"""
        out = SnapshotOut.model_validate(_make_snapshot_row(tech_detail=None))
        assert out.tech_detail is None

    def test_data_source_field_works(self) -> None:
        """``data_source='mock'``（V0.79.0 任务 #163）：保持 str 透传。"""
        out = SnapshotOut.model_validate(_make_snapshot_row(data_source="mock"))
        assert out.data_source == "mock"

    def test_data_source_none_preserved(self) -> None:
        """``data_source=None``（历史未标记）：保持 None。"""
        out = SnapshotOut.model_validate(_make_snapshot_row(data_source=None))
        assert out.data_source is None

    def test_all_required_fields_present(self) -> None:
        """所有 V0.86 之前的必填字段都仍存在 + 类型正确。"""
        out = SnapshotOut.model_validate(_make_snapshot_row())
        assert out.snapshot_date == date(2026, 10, 1)
        assert out.symbol == "518880"
        assert out.close == 5.5
        assert out.trend_index == 61.0
        assert out.index_level == "偏多"


# ──────────────── SnapshotListOut 包装 ────────────────


class TestSnapshotListOutWrapping:
    """``SnapshotListOut`` 容器（V0.79.0 已稳定）；V0.90.0 不改，但快照内嵌字段受 schema fix 影响。"""

    def test_list_with_macro_detail_via_orm(self) -> None:
        """内嵌 ORM rows → macro_detail 反序列化沿用（container 不破坏）。"""
        rows = [
            _make_snapshot_row(
                snapshot_date=date(2026, 10, 1),
                macro_detail='{"DXY": {"value": 104.5}}',
            ),
            _make_snapshot_row(
                snapshot_date=date(2026, 10, 2),
                macro_detail=None,
            ),
        ]
        # SnapshotListOut 通常用 list[SnapshotOut] 装 dict/list 入参
        # —— 这里模拟 ORM 转 dict 的场景
        items = [SnapshotOut.model_validate(r) for r in rows]
        out = SnapshotListOut(total=2, snapshots=items)
        assert out.total == 2
        assert out.snapshots[0].macro_detail == {"DXY": {"value": 104.5}}
        assert out.snapshots[1].macro_detail is None
