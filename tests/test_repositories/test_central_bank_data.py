"""央行黄金购买数据采集（central_bank_data.py）单元测试。

**测试范围**（深覆盖，含 mock fetcher 完整隔离）：
- ``QuarterlyPurchase`` dataclass 不可变语义
- ``_quarter_to_data_date`` / ``_previous_quarter`` / ``_quarter_to_int`` 边界
- ``_parse_chart_series`` 含 null/非数字值兜底
- ``_fetch_report_charts`` 网络失败降级
- ``_find_country_chart`` 关键字匹配
- ``_iso_for_country`` WGC 别名映射（含 Q3 2025 + Q2 2026 两套别名）
- ``fetch_global_quarterly_aggregate`` / ``fetch_h1_2026_by_country`` 完整 mock
- ``load_manual_overrides`` 含文件缺失 / 非法 JSON / 非法条目
- ``build_full_dataset`` 编排三源数据

**Mock 策略**：
- 所有 ``_http_get`` 通过 monkeypatch 注入（不连真实网络）
- 每个测试前后清空模块级 ``_CACHE``（避免 TTL 干扰）
- 不依赖 ``conftest._reset_db``（不写数据库）
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from app.repositories import central_bank_data as cbd


# ──────────────── 公共 fixture：清缓存 + monkeypatch 入口 ────────────────


@pytest.fixture(autouse=True)
def _clear_cbd_cache():
    """每个用例前后清空中央银行数据缓存（避免跨测试污染）。"""
    with cbd._CACHE_LOCK:
        cbd._CACHE.clear()
    yield
    with cbd._CACHE_LOCK:
        cbd._CACHE.clear()


def _patch_http(monkeypatch: pytest.MonkeyPatch, body_or_map):
    """把 ``_http_get`` 全部 mock 成 body_or_map。

    ``body_or_map`` 可以是：
    - str：所有 URL 都返回这一段 body
    - dict[URL → body]：按 URL 路由返回（未注册 URL 抛 AssertionError）
    """
    if isinstance(body_or_map, str):

        def _fake(url: str, timeout: int = 30) -> str:
            return body_or_map

    else:

        def _fake(url: str, timeout: int = 30) -> str:
            assert url in body_or_map, f"unexpected URL in mock: {url}"
            return body_or_map[url]

    monkeypatch.setattr(cbd, "_http_get", _fake)


# ──────────────── dataclass ────────────────


class TestQuarterlyPurchase:
    """``QuarterlyPurchase`` 不可变 dataclass 的语义保护。"""

    def test_construction_and_field_access(self) -> None:
        """正常构造：5 字段都能读出来。"""
        item = cbd.QuarterlyPurchase(
            country_iso="CHN",
            country_name="中国",
            quarter="2026Q2",
            tonnes_net=10.5,
            source="WGC GDT",
            data_date=date(2026, 6, 30),
        )
        assert item.country_iso == "CHN"
        assert item.country_name == "中国"
        assert item.quarter == "2026Q2"
        assert item.tonnes_net == 10.5
        assert item.source == "WGC GDT"
        assert item.data_date == date(2026, 6, 30)

    def test_frozen_immutability(self) -> None:
        """dataclass(frozen=True)：字段不能改写（防止外部代码意外改值）。"""
        item = cbd.QuarterlyPurchase(
            country_iso="CHN",
            country_name="中国",
            quarter="2026Q2",
            tonnes_net=10.5,
            source="WGC GDT",
            data_date=date(2026, 6, 30),
        )
        with pytest.raises((AttributeError, Exception)):
            item.tonnes_net = 99.9  # type: ignore[misc]

    def test_equality_by_value(self) -> None:
        """相同字段的两个实例相等（dataclass 自动 __eq__）。"""
        a = cbd.QuarterlyPurchase(
            country_iso="POL", country_name="波兰", quarter="2026Q1",
            tonnes_net=5.0, source="x", data_date=date(2026, 3, 31),
        )
        b = cbd.QuarterlyPurchase(
            country_iso="POL", country_name="波兰", quarter="2026Q1",
            tonnes_net=5.0, source="x", data_date=date(2026, 3, 31),
        )
        assert a == b


# ──────────────── 季度工具 ────────────────


class TestQuarterUtils:
    """``_quarter_to_data_date`` / ``_previous_quarter`` / ``_quarter_to_int``。"""

    @pytest.mark.parametrize(
        "quarter,expected",
        [
            ("2026Q1", date(2026, 3, 31)),
            ("2026Q2", date(2026, 6, 30)),
            ("2026Q3", date(2026, 9, 30)),
            ("2026Q4", date(2026, 12, 31)),
            # 闰年 2 月不影响季度月末
            ("2024Q1", date(2024, 3, 31)),
            # 2020Q1 平年
            ("2020Q1", date(2020, 3, 31)),
        ],
    )
    def test_quarter_to_data_date(self, quarter: str, expected: date) -> None:
        """4 个季度的月末日期正确（含跨年/平年/闰年）。"""
        assert cbd._quarter_to_data_date(quarter) == expected

    @pytest.mark.parametrize(
        "quarter,prev",
        [
            ("2026Q2", "2026Q1"),
            ("2026Q3", "2026Q2"),
            ("2026Q4", "2026Q3"),
            ("2026Q1", "2025Q4"),  # 跨年
            ("2020Q1", "2019Q4"),  # 跨年 + 起始边界
        ],
    )
    def test_previous_quarter(self, quarter: str, prev: str) -> None:
        """上季度回溯：Q2→Q1 / Q1→上一年 Q4 / 2020Q1→2019Q4。"""
        assert cbd._previous_quarter(quarter) == prev

    def test_quarter_to_int_sortable(self) -> None:
        """``_quarter_to_int`` 必须可排序：用于同期比较与排序。"""
        quarters = ["2026Q1", "2025Q4", "2026Q2", "2024Q1"]
        ints = sorted(cbd._quarter_to_int(q) for q in quarters)
        assert ints == sorted(ints)
        assert cbd._quarter_to_int("2026Q2") == 20262
        assert cbd._quarter_to_int("2026Q1") == 20261
        assert cbd._quarter_to_int("2026Q4") == 20264


# ──────────────── 进程内缓存 ────────────────


class TestCache:
    """``_cache_get`` / ``_cache_set`` 的 TTL 语义。"""

    def test_cache_get_miss_returns_none(self) -> None:
        """空缓存：返回 None。"""
        assert cbd._cache_get(("k1",)) is None

    def test_cache_set_and_get_within_ttl(self) -> None:
        """写入后立即读取：返回写入的值。"""
        cbd._cache_set(("k1",), {"a": 1})
        assert cbd._cache_get(("k1",)) == {"a": 1}

    def test_cache_ttl_expiry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TTL 过期（24h）：返回 None。"""
        cbd._cache_set(("k1",), "v1")
        # 模拟时间过去 25h
        ts_now = cbd._CACHE[("k1",)][0]
        monkeypatch.setattr(cbd.time, "time", lambda: ts_now + 25 * 3600)
        assert cbd._cache_get(("k1",)) is None

    def test_cache_keys_isolated(self) -> None:
        """不同 key 互不干扰。"""
        cbd._cache_set(("a",), 1)
        cbd._cache_set(("b",), 2)
        assert cbd._cache_get(("a",)) == 1
        assert cbd._cache_get(("b",)) == 2
        assert cbd._cache_get(("c",)) is None


# ──────────────── WGC chart JS 解析 ────────────────


class TestParseChartSeries:
    """``_parse_chart_series`` 解析 WGC chart JS body 的健壮性。"""

    def test_standard_two_series(self) -> None:
        """标准 2 series chart（Net purchases + Net sales）。"""
        js = (
            '{"series":[{"name":"Net purchases","data":[1,2,3]},'
            '{"name":"Net sales","data":[0,-1,-2]}],'
            '"xAxis":{"categories":["POL","CHN","RUS"]}}'
        )
        cats, series = cbd._parse_chart_series(js)
        assert cats == ["POL", "CHN", "RUS"]
        assert series["Net purchases"] == [1.0, 2.0, 3.0]
        assert series["Net sales"] == [0.0, -1.0, -2.0]

    def test_null_values_to_zero(self) -> None:
        """series 里有 "null"/"Null"/null → 转 0.0。"""
        js = (
            '{"series":[{"name":"Q1","data":[1,null,3]}],'
            '"xAxis":{"categories":["a","b","c"]}}'
        )
        cats, series = cbd._parse_chart_series(js)
        assert series["Q1"] == [1.0, 0.0, 3.0]

    def test_non_numeric_to_zero(self) -> None:
        """series 里混非数字字符串 → fallback 0.0（不抛异常）。"""
        js = (
            '{"series":[{"name":"Q1","data":[1,"?",3]}],'
            '"xAxis":{"categories":["a","b","c"]}}'
        )
        cats, series = cbd._parse_chart_series(js)
        assert series["Q1"] == [1.0, 0.0, 3.0]

    def test_numeric_categories(self) -> None:
        """categories 是数字列表（年份）也能识别。"""
        js = (
            '{"series":[{"name":"Q1","data":[10,20]}],'
            '"xAxis":{"categories":[2014,2015]}}'
        )
        cats, series = cbd._parse_chart_series(js)
        # 数字 categories 走 split(",") 路径
        assert cats == ["2014", "2015"]
        assert series["Q1"] == [10.0, 20.0]

    def test_no_categories_returns_empty(self) -> None:
        """无 categories 字段：返回 ([], {})。"""
        js = '{"series":[{"name":"Q1","data":[1,2]}]}'
        cats, series = cbd._parse_chart_series(js)
        assert cats == []
        assert series == {}

    def test_empty_chart(self) -> None:
        """空 body / 全是 metadata：返回空。"""
        cats, series = cbd._parse_chart_series("")
        assert cats == []
        assert series == {}


# ──────────────── WGC 报告页 chart 列表 ────────────────


class TestFetchReportCharts:
    """``_fetch_report_charts`` 网络抓取 + HTML 解析。"""

    _SAMPLE_HTML = """
    <html><body>
      <article>
        <h3>Chart 8: Central bank buying rebounded</h3>
        <div data-chart-data-lib="https://fsapi.gold.org/api/v12/charts/js/gdt-q2-2026-abc/3431"></div>
      </article>
      <article>
        <h3>Chart 9: Poland in pole position</h3>
        <div data-chart-data-lib="https://fsapi.gold.org/api/v12/charts/js/gdt-q2-2026-abc/3432"></div>
      </article>
    </body></html>
    """

    def test_two_charts_parsed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """HTML 含 2 chart：返回 2 个 dict（含 title + lib path）。"""
        _patch_http(monkeypatch, self._SAMPLE_HTML)
        out = cbd._fetch_report_charts(2026, "q2")
        assert len(out) == 2
        assert out[0]["title"] == "Chart 8: Central bank buying rebounded"
        assert out[0]["lib"] == "/gdt-q2-2026-abc/3431"
        assert out[1]["title"] == "Chart 9: Poland in pole position"
        assert out[1]["lib"] == "/gdt-q2-2026-abc/3432"

    def test_http_failure_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """网络异常：返回 []（不抛异常 + 缓存空结果，避免反复失败）。"""
        def _boom(url: str, timeout: int = 30) -> str:
            raise ConnectionError("network down")

        monkeypatch.setattr(cbd, "_http_get", _boom)
        out = cbd._fetch_report_charts(2026, "q2")
        assert out == []

    def test_empty_html_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """HTML 无 chart article：返回 []。"""
        _patch_http(monkeypatch, "<html><body>no charts</body></html>")
        out = cbd._fetch_report_charts(2026, "q2")
        assert out == []


class TestFindCountryChart:
    """``_find_country_chart`` 按标题关键字找 chart。"""

    def test_keyword_match(self) -> None:
        """关键字命中：返回匹配的 chart。"""
        charts = [
            {"title": "Chart 8: tonnes", "lib": "/x"},
            {"title": "Chart 9: poland in pole position", "lib": "/y"},
        ]
        out = cbd._find_country_chart(charts, "poland in pole position")
        assert out == charts[1]

    def test_no_match_returns_none(self) -> None:
        """无匹配：返回 None。"""
        charts = [{"title": "Chart 8: tonnes", "lib": "/x"}]
        assert cbd._find_country_chart(charts, "no-such-keyword") is None

    def test_case_insensitive(self) -> None:
        """大小写不敏感（keyword 与 title 都 lower() 比较）。"""
        charts = [{"title": "Chart 9: Poland In Pole Position", "lib": "/y"}]
        out = cbd._find_country_chart(charts, "POLAND IN POLE")
        assert out is not None
        assert out["lib"] == "/y"


# ──────────────── ISO3 映射 ────────────────


class TestIsoForCountry:
    """``_iso_for_country`` WGC 别名 + 中文 fallback。"""

    def test_q2_2026_alias(self) -> None:
        """Q2 2026 别名：'Poland' → 'POL'。"""
        assert cbd._iso_for_country("Poland") == "POL"
        assert cbd._iso_for_country("China") == "CHN"

    def test_q2_2026_rep_alias(self) -> None:
        """Q2 2026 'Rep.' 缩写：'Czech Rep.' → 'CZE'。"""
        assert cbd._iso_for_country("Czech Rep.") == "CZE"
        assert cbd._iso_for_country("Kyrgyz Rep.") == "KGZ"

    def test_q3_2025_long_name(self) -> None:
        """Q3 2025 长名：'Russian Federation' → 'RUS'。"""
        assert cbd._iso_for_country("Russian Federation") == "RUS"
        assert cbd._iso_for_country("Türkiye, Republic of") == "TUR"
        assert cbd._iso_for_country("Egypt, Arab Republic of") == "EGY"

    def test_unknown_returns_self(self) -> None:
        """未识别国家：返回原名（仍可展示，但 ISO 留白）。"""
        assert cbd._iso_for_country("Atlantis") == "Atlantis"

    def test_azerbaijan_sofaz_alias(self) -> None:
        """'Azerbaijan (SOFAZ)' → 'AZE'（SOFAZ 是阿塞拜疆主权基金缩写）。"""
        assert cbd._iso_for_country("Azerbaijan (SOFAZ)") == "AZE"


# ──────────────── 拉取全球合计（Chart 8） ────────────────


class TestFetchGlobalQuarterlyAggregate:
    """``fetch_global_quarterly_aggregate`` 端到端 mock。"""

    _REPORT_HTML = """
    <html><body>
      <article>
        <h3>Chart 8: Quarterly central bank buying rebounded</h3>
        <div data-chart-data-lib="https://fsapi.gold.org/api/v12/charts/js/gdt-q2-2026-x/3431"></div>
      </article>
    </body></html>
    """

    _CHART_JS = (
        '{"series":[{"name":"Q1","data":[50,60,70,80,null,55,65,75,85,95,100,110,120]},'
        '{"name":"Q2","data":[40,50,65,75,null,50,60,70,80,90,95,105,115]}],'
        '"xAxis":{"categories":[2014,2015,2016,2017,2018,2019,2020,2021,2022,2023,2024,2025,2026]}}'
    )

    def test_returns_wgc_aggr_rows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """正常：返回 WGC_AGGR 行（country_iso='WGC_AGGR'）。"""
        _patch_http(monkeypatch, {
            cbd._WGC_REPORT_URL.format(quarter="q2", year=2026): self._REPORT_HTML,
            cbd._WGC_CHART_API + "/gdt-q2-2026-x/3431": self._CHART_JS,
        })
        rows = cbd.fetch_global_quarterly_aggregate()
        assert len(rows) > 0
        assert all(r.country_iso == "WGC_AGGR" for r in rows)
        assert all(r.source == "WGC GDT Q2 2026 合计行" for r in rows)
        # Q1 + Q2 都有 → 至少 2 个 quarter
        quarters = {r.quarter for r in rows}
        assert "2014Q1" in quarters
        assert "2014Q2" in quarters

    def test_zero_value_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """val == 0.0 的项被跳过（保持稀疏性）。"""
        # 2018Q1 = null 已被 parse 转为 0.0 → 应被跳过
        _patch_http(monkeypatch, {
            cbd._WGC_REPORT_URL.format(quarter="q2", year=2026): self._REPORT_HTML,
            cbd._WGC_CHART_API + "/gdt-q2-2026-x/3431": self._CHART_JS,
        })
        rows = cbd.fetch_global_quarterly_aggregate()
        quarters = {r.quarter for r in rows}
        # 2018Q1/Q2 因为 null → 0.0 被跳过
        assert "2018Q1" not in quarters
        assert "2018Q2" not in quarters

    def test_chart8_missing_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Chart 8 不在 HTML 中：返回 []（不抛异常）。"""
        empty_html = "<html><body><article><h3>Chart 99: other</h3></article></body></html>"
        _patch_http(monkeypatch, {
            cbd._WGC_REPORT_URL.format(quarter="q2", year=2026): empty_html,
        })
        assert cbd.fetch_global_quarterly_aggregate() == []


# ──────────────── 拉取 H1 2026 按国家（Chart 9） ────────────────


class TestFetchH1ByCountry:
    """``fetch_h1_2026_by_country`` 端到端 mock + Q1/Q2 拆分。"""

    _REPORT_HTML = """
    <html><body>
      <article>
        <h3>Chart 8: Quarterly central bank buying rebounded</h3>
        <div data-chart-data-lib="https://fsapi.gold.org/api/v12/charts/js/gdt-q2-2026-x/3431"></div>
      </article>
      <article>
        <h3>Chart 9: Poland in pole position (H1 2026)</h3>
        <div data-chart-data-lib="https://fsapi.gold.org/api/v12/charts/js/gdt-q2-2026-x/3432"></div>
      </article>
    </body></html>
    """

    _CHART_8_JS = (
        '{"series":[{"name":"Q1","data":[100,110,120,130,null,null,55,65,75,85,95,100,110]},'
        '{"name":"Q2","data":[40,50,65,75,null,null,50,60,70,80,90,95,105]}],'
        '"xAxis":{"categories":[2014,2015,2016,2017,2018,2019,2020,2021,2022,2023,2024,2025,2026]}}'
    )

    _CHART_9_JS = (
        '{"series":[{"name":"Net purchases","data":[20,15,10,8,5,3,2,2,2,1,1,1,0.5,0.5,0.5,0.5,0.5,0.5,0.5]},'
        '{"name":"Net sales","data":[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,-1,-2]}],'
        '"xAxis":{"categories":["Poland","Uzbekistan","China","Kazakhstan","Czech Rep.",'
        '"Chile","Jordan","Ghana","Malaysia","Singapore","Kyrgyz Rep.","Cambodia",'
        '"Guatemala","Serbia","Indonesia","Bolivia","Uruguay","Germany","Russia"]}}'
    )

    def test_returns_country_split(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """正常：返回按国家 + 按 Q1/Q2 拆分的行。"""
        _patch_http(monkeypatch, {
            cbd._WGC_REPORT_URL.format(quarter="q2", year=2026): self._REPORT_HTML,
            cbd._WGC_CHART_API + "/gdt-q2-2026-x/3431": self._CHART_8_JS,
            cbd._WGC_CHART_API + "/gdt-q2-2026-x/3432": self._CHART_9_JS,
        })
        rows = cbd.fetch_h1_2026_by_country()
        assert len(rows) > 0
        # 至少出现 2 个国家
        isos = {r.country_iso for r in rows}
        assert "POL" in isos
        assert "CHN" in isos
        # 拆分到 Q1 + Q2
        quarters = {r.quarter for r in rows}
        assert "2026Q1" in quarters
        assert "2026Q2" in quarters
        # 来源标注
        assert all(r.source == "WGC GDT Q2 2026 H1" for r in rows)

    def test_fallback_5050_split_when_aggregate_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Chart 8 缺失时（无 aggregate）：Q1/Q2 等分 0.5/0.5 fallback。"""
        no_c8_html = """
        <html><body>
          <article>
            <h3>Chart 9: Poland in pole position</h3>
            <div data-chart-data-lib="https://fsapi.gold.org/api/v12/charts/js/gdt-q2-2026-x/3432"></div>
          </article>
        </body></html>
        """
        _patch_http(monkeypatch, {
            cbd._WGC_REPORT_URL.format(quarter="q2", year=2026): no_c8_html,
            cbd._WGC_CHART_API + "/gdt-q2-2026-x/3432": self._CHART_9_JS,
        })
        rows = cbd.fetch_h1_2026_by_country()
        # 即使无 aggregate，0.5/0.5 等分也能产出 Q1+Q2 行
        quarters = {r.quarter for r in rows}
        assert "2026Q1" in quarters
        assert "2026Q2" in quarters

    def test_chart9_missing_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Chart 9 不在 HTML 中：返回 []。"""
        no_c9_html = """
        <html><body>
          <article>
            <h3>Chart 8: tonnes</h3>
            <div data-chart-data-lib="https://fsapi.gold.org/api/v12/charts/js/gdt-q2-2026-x/3431"></div>
          </article>
        </body></html>
        """
        _patch_http(monkeypatch, {
            cbd._WGC_REPORT_URL.format(quarter="q2", year=2026): no_c9_html,
            cbd._WGC_CHART_API + "/gdt-q2-2026-x/3431": self._CHART_8_JS,
        })
        assert cbd.fetch_h1_2026_by_country() == []


# ──────────────── 手工补丁 ────────────────


class TestLoadManualOverrides:
    """``load_manual_overrides`` 读 data/central_bank_manual_overrides.json。"""

    def test_missing_file_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """文件不存在：返回 []（不抛异常）。"""
        monkeypatch.setattr(cbd, "_OVERRIDES_PATH", Path("/nonexistent/path/overrides.json"))
        assert cbd.load_manual_overrides() == []

    def test_valid_json_returns_rows(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """正常 JSON：返回 ISO + 季度 + 吨数 的行。"""
        payload = {
            "_comment": "test fixture",
            "TST": {
                "name": "测试国",
                "source": "test source",
                "data": [["2026Q1", 5.0], ["2026Q2", 7.5]],
            },
        }
        p = tmp_path / "overrides.json"
        p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(cbd, "_OVERRIDES_PATH", p)

        rows = cbd.load_manual_overrides()
        assert len(rows) == 2
        assert rows[0].country_iso == "TST"
        assert rows[0].country_name == "测试国"
        assert rows[0].quarter == "2026Q1"
        assert rows[0].tonnes_net == 5.0
        assert rows[0].source == "test source"
        assert rows[0].data_date == date(2026, 3, 31)
        assert rows[1].data_date == date(2026, 6, 30)

    def test_invalid_json_returns_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """非法 JSON：返回 []（不抛异常）。"""
        p = tmp_path / "overrides.json"
        p.write_text("{not valid json", encoding="utf-8")
        monkeypatch.setattr(cbd, "_OVERRIDES_PATH", p)
        assert cbd.load_manual_overrides() == []

    def test_invalid_entry_skipped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """条目缺 data 或 tonnes 非数字：跳过该条 + 记录 warning。"""
        payload = {
            "OK": {"name": "A", "data": [["2026Q1", 1.0]]},
            "BAD1": {"name": "B"},  # 缺 data
            "BAD2": {"name": "C", "data": [["2026Q1", "not_a_number"]]},  # 非数字
        }
        p = tmp_path / "overrides.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setattr(cbd, "_OVERRIDES_PATH", p)

        rows = cbd.load_manual_overrides()
        isos = {r.country_iso for r in rows}
        assert "OK" in isos
        assert "BAD1" not in isos
        assert "BAD2" not in isos

    def test_comment_key_skipped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """``_comment`` 这种下划线前缀的 key 必须被跳过。"""
        payload = {
            "_comment": "metadata",
            "_another_meta": "ignored",
            "REAL": {"name": "X", "data": [["2026Q1", 1.0]]},
        }
        p = tmp_path / "overrides.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setattr(cbd, "_OVERRIDES_PATH", p)

        rows = cbd.load_manual_overrides()
        isos = {r.country_iso for r in rows}
        assert isos == {"REAL"}

    def test_default_source_and_name(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """未指定 name/source 时使用 fallback（name=iso, source='WGC 手工'）。"""
        payload = {
            "DEF": {"data": [["2026Q1", 1.0]]},
        }
        p = tmp_path / "overrides.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setattr(cbd, "_OVERRIDES_PATH", p)

        rows = cbd.load_manual_overrides()
        assert rows[0].country_name == "DEF"  # fallback = iso
        assert rows[0].source == "WGC 手工"


# ──────────────── 编排 ────────────────


class TestBuildFullDataset:
    """``build_full_dataset`` 异步编排三源。"""

    _REPORT_HTML = """
    <html><body>
      <article>
        <h3>Chart 8: Quarterly central bank buying rebounded</h3>
        <div data-chart-data-lib="https://fsapi.gold.org/api/v12/charts/js/gdt-q2-2026-x/3431"></div>
      </article>
      <article>
        <h3>Chart 9: Poland in pole position</h3>
        <div data-chart-data-lib="https://fsapi.gold.org/api/v12/charts/js/gdt-q2-2026-x/3432"></div>
      </article>
    </body></html>
    """

    _CHART_8_JS = (
        '{"series":[{"name":"Q1","data":[100,110,120,130,null,null,55,65,75,85,95,100,110]},'
        '{"name":"Q2","data":[40,50,65,75,null,null,50,60,70,80,90,95,105]}],'
        '"xAxis":{"categories":[2014,2015,2016,2017,2018,2019,2020,2021,2022,2023,2024,2025,2026]}}'
    )

    _CHART_9_JS = (
        '{"series":[{"name":"Net purchases","data":[20,15,10]},'
        '{"name":"Net sales","data":[0,0,0]}],'
        '"xAxis":{"categories":["Poland","Uzbekistan","China"]}}'
    )

    async def test_orchestrates_all_three_sources(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """正常：合并 Chart 8 + Chart 9 + 手工补丁的输出。"""
        _patch_http(monkeypatch, {
            cbd._WGC_REPORT_URL.format(quarter="q2", year=2026): self._REPORT_HTML,
            cbd._WGC_CHART_API + "/gdt-q2-2026-x/3431": self._CHART_8_JS,
            cbd._WGC_CHART_API + "/gdt-q2-2026-x/3432": self._CHART_9_JS,
        })
        payload = {
            "MAN": {"name": "测试手工", "data": [["2026Q1", 1.0]]},
        }
        p = tmp_path / "overrides.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setattr(cbd, "_OVERRIDES_PATH", p)

        out = await cbd.build_full_dataset(start="2020-01", end="2026-06")
        isos = {r.country_iso for r in out}
        # WGC_AGGR (Chart 8) + POL/UZB/CHN (Chart 9) + MAN (手工)
        assert "WGC_AGGR" in isos
        assert "POL" in isos
        assert "MAN" in isos

    async def test_empty_when_all_sources_fail(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """所有源都拿不到数据：返回 []（不抛异常）。"""
        def _boom(url: str, timeout: int = 30) -> str:
            raise ConnectionError("network down")

        monkeypatch.setattr(cbd, "_http_get", _boom)
        monkeypatch.setattr(cbd, "_OVERRIDES_PATH", tmp_path / "no-such.json")
        out = await cbd.build_full_dataset(start="2020-01", end="2026-06")
        assert out == []