"""WGC GDT HTML fetcher + 季度聚合 单测。

历史说明：本文件原覆盖 IMF IRFCL 月度 oz → 季度吨聚合；
IMF SDMX 端点（2.1/3.0）实测不可用（3.0=404、2.1=空 DataSet），切换到
WGC Gold Demand Trends HTML chart JS。F 接口签名变了，单测同步重写。
"""

from datetime import date

import pytest

from app.repositories import central_bank_data as cb_data
from app.repositories.central_bank_data import (
    COUNTRY_NAMES,
    QuarterlyPurchase,
    _find_country_chart,
    _iso_for_country,
    _parse_chart_series,
    _previous_quarter,
    _quarter_to_data_date,
    _quarter_to_int,
    load_manual_overrides,
)

# ── 纯函数 helper ───────────────────────────────────────────────


def test_quarter_to_data_date() -> None:
    assert _quarter_to_data_date("2026Q1") == date(2026, 3, 31)
    assert _quarter_to_data_date("2026Q2") == date(2026, 6, 30)
    assert _quarter_to_data_date("2026Q3") == date(2026, 9, 30)
    assert _quarter_to_data_date("2026Q4") == date(2026, 12, 31)


def test_quarter_to_data_date_invalid() -> None:
    with pytest.raises((ValueError, KeyError)):
        _quarter_to_data_date("2026Q5")
    with pytest.raises((ValueError, KeyError)):
        _quarter_to_data_date("2026")


def test_previous_quarter() -> None:
    assert _previous_quarter("2026Q2") == "2026Q1"
    assert _previous_quarter("2026Q1") == "2025Q4"
    assert _previous_quarter("2025Q4") == "2025Q3"
    assert _previous_quarter("2020Q1") == "2019Q4"


def test_quarter_to_int() -> None:
    assert _quarter_to_int("2026Q1") == 20261
    assert _quarter_to_int("2026Q2") == 20262
    assert _quarter_to_int("2020Q1") == 20201
    # 排序用：2026Q2 > 2025Q4
    assert _quarter_to_int("2026Q2") > _quarter_to_int("2025Q4")


# ── WGC chart JS 解析 ─────────────────────────────────────────────


def test_parse_chart_series_quarterly_aggregate() -> None:
    """解析 Q2 2026 报告 Chart 8（季度合计 2014-2026）。"""
    js = """
    "series":[
      {"name":"Q1","data":[118.8,103.1,110.6]},
      {"name":"Q2","data":[169.6,141.4,84.9]},
      {"name":"Q3","data":[176.98,172.41,88.95]},
      {"name":"Q4","data":[135.76,162.72,110.4]}
    ],
    "xAxis":{"categories":[2014,2015,2016]}
    """
    cats, series = _parse_chart_series(js)
    assert cats == ["2014", "2015", "2016"]
    assert series["Q1"] == [118.8, 103.1, 110.6]
    assert series["Q4"] == [135.76, 162.72, 110.4]


def test_parse_chart_series_with_nulls() -> None:
    """chart 数据含 "null"（季度尚未发布）。"""
    js = """
    "series":[{"name":"Q3","data":[100.0,"null",200.0]}],
    "xAxis":{"categories":["2024","2025","2026"]}
    """
    cats, series = _parse_chart_series(js)
    assert cats == ["2024", "2025", "2026"]
    # "null" 转 0.0
    assert series["Q3"] == [100.0, 0.0, 200.0]


def test_parse_chart_series_by_country() -> None:
    """解析 Q2 2026 报告 Chart 9（H1 2026 按国家）。"""
    js = """
    "series":[
      {"name":"Net purchases","data":[82.2,41.4,40.1,"null","null"]},
      {"name":"Net sales","data":["null","null","null",-0.8,-83.1]}
    ],
    "xAxis":{"categories":["Poland","Uzbekistan","China","Germany","Turkey"]}
    """
    cats, series = _parse_chart_series(js)
    assert cats == ["Poland", "Uzbekistan", "China", "Germany", "Turkey"]
    assert series["Net purchases"][0] == 82.2
    assert series["Net purchases"][3] == 0.0  # null → 0
    assert series["Net sales"][4] == -83.1


def test_parse_chart_series_string_categories_quoted() -> None:
    """类别是带引号的字符串列表。"""
    js = '"categories":["Q1","Q2","Q3"]'
    cats, _ = _parse_chart_series(js)
    assert cats == ["Q1", "Q2", "Q3"]


def test_parse_chart_series_empty() -> None:
    cats, series = _parse_chart_series('{"series":[]}')
    assert cats == []
    assert series == {}


def test_find_country_chart_by_keyword() -> None:
    charts = [
        {"title": "Chart 1: demand overview", "lib": "/x/1"},
        {"title": "Chart 8: Central bank buying rebounded sharply in Q2", "lib": "/x/8"},
        {"title": "Chart 9: Reported data puts Poland in pole position y-t-d", "lib": "/x/9"},
    ]
    assert _find_country_chart(charts, "central bank buying rebounded")["lib"] == "/x/8"
    assert _find_country_chart(charts, "poland in pole position")["lib"] == "/x/9"
    assert _find_country_chart(charts, "nonexistent") is None
    # 大小写不敏感
    assert _find_country_chart(charts, "POLAND")["lib"] == "/x/9"


# ── ISO 映射 ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "wgc_name,expected_iso",
    [
        ("Poland", "POL"),
        ("Uzbekistan", "UZB"),
        ("Uzbekistan, Republic of", "UZB"),
        ("China", "CHN"),
        ("China, People's Republic of", "CHN"),
        ("Kazakhstan", "KAZ"),
        ("Czech Rep.", "CZE"),
        ("Czech Republic", "CZE"),
        ("Russia", "RUS"),
        ("Russian Federation", "RUS"),
        ("Turkey", "TUR"),
        ("Türkiye, Republic of", "TUR"),
        ("Germany", "DEU"),
        ("Azerbaijan (SOFAZ)", "AZE"),
        ("Egypt, Arab Republic of", "EGY"),
    ],
)
def test_iso_for_country_known(wgc_name: str, expected_iso: str) -> None:
    assert _iso_for_country(wgc_name) == expected_iso


def test_iso_for_country_unknown_returns_input() -> None:
    """未知国家原样返回（仍可展示，不抛错）。"""
    assert _iso_for_country("Atlantis") == "Atlantis"


# ── 手工补丁 ───────────────────────────────────────────────


@pytest.mark.skipif(
    not cb_data._OVERRIDES_PATH.exists(),
    reason="需本地 data/central_bank_manual_overrides.json（.gitignore 内，新克隆不携带）",
)
def test_load_manual_overrides_returns_uZB_and_irn() -> None:
    """UZB + IRN 手工补丁能加载，含 26 季度（2020Q1-2026Q2）。"""
    rows = load_manual_overrides()
    assert len(rows) >= 52
    isos = {r.country_iso for r in rows}
    assert "UZB" in isos
    assert "IRN" in isos

    quarters = {r.quarter for r in rows}
    # 至少 2020Q1 到 2026Q2（26 个季度）
    assert "2020Q1" in quarters
    assert "2026Q2" in quarters
    # 数据连续性：所有 26 季度都应存在
    for y in (2020, 2021, 2022, 2023, 2024, 2025, 2026):
        for q in ("Q1", "Q2", "Q3", "Q4"):
            label = f"{y}{q}"
            if y == 2026 and q in ("Q3", "Q4"):
                continue  # 未来季度不要求
            assert label in quarters, f"missing {label}"


def test_load_manual_overrides_uZB_positive() -> None:
    """UZB 历史补丁是正数（持续购金）。"""
    rows = [r for r in load_manual_overrides() if r.country_iso == "UZB"]
    assert all(r.tonnes_net > 0 for r in rows)


def test_load_manual_overrides_irn_zero() -> None:
    """IRN 历史补丁是 0（未披露数据，按 0 处理）。"""
    rows = [r for r in load_manual_overrides() if r.country_iso == "IRN"]
    assert all(r.tonnes_net == 0 for r in rows)


# ── 端到端（mock WGC chart JS）────────────────────────────────────


def test_global_quarterly_aggregate_with_mock(monkeypatch) -> None:
    """mock WGC Chart 8 数据，验证全球季度合计解析。"""
    sample_js = """
    "series":[
      {"name":"Q1","data":[118.8,103.1,110.6,92.0,84.8]},
      {"name":"Q2","data":[169.6,141.4,84.9,96.3,152.8]},
      {"name":"Q3","data":[177.0,172.4,89.0,96.6,240.5]},
      {"name":"Q4","data":[135.8,162.7,110.4,93.7,178.1]}
    ],
    "xAxis":{"categories":[2014,2015,2016,2017,2018]}
    """
    # 同时 mock _fetch_report_charts 和 _fetch_chart_js
    monkeypatch.setattr(
        cb_data,
        "_fetch_report_charts",
        lambda year, quarter: [
            {"title": "Chart 8: Quarterly central bank net purchases, tonnes", "lib": "/test/lib"}
        ],
    )
    monkeypatch.setattr(cb_data, "_fetch_chart_js", lambda lib: sample_js)

    rows = cb_data.fetch_global_quarterly_aggregate()
    # 5 年 × 4 季度 = 20 行
    assert len(rows) == 20
    # 全部是 WGC_AGGR
    assert all(r.country_iso == "WGC_AGGR" for r in rows)
    assert all(r.country_name == "全球合计" for r in rows)
    # 2014Q1 应该是 118.8
    r2014q1 = next(r for r in rows if r.quarter == "2014Q1")
    assert r2014q1.tonnes_net == 118.8
    assert r2014q1.source == "WGC GDT Q2 2026 合计行"
    assert r2014q1.data_date == date(2014, 3, 31)
    # 2018Q4 = 178.1
    r2018q4 = next(r for r in rows if r.quarter == "2018Q4")
    assert r2018q4.tonnes_net == 178.1


def test_h1_2026_by_country_with_mock(monkeypatch) -> None:
    """mock WGC Chart 9 数据，验证按国家拆分 H1 → Q1+Q2。"""
    sample_js = """
    "series":[
      {"name":"Net purchases","data":[82.2,40.1,"null","null","null"]},
      {"name":"Net sales","data":["null","null",-83.1,-43.5,"null"]}
    ],
    "xAxis":{"categories":["Poland","China","Turkey","Russia","Germany"]}
    """
    monkeypatch.setattr(
        cb_data,
        "_fetch_report_charts",
        lambda year, quarter: [
            {
                "title": "Chart 9: Reported data puts Poland in pole position y-t-d",
                "lib": "/test/c9",
            }
        ],
    )
    monkeypatch.setattr(cb_data, "_fetch_chart_js", lambda lib: sample_js)
    monkeypatch.setattr(
        cb_data,
        "fetch_global_quarterly_aggregate",
        lambda: [
            QuarterlyPurchase(
                country_iso="WGC_AGGR",
                country_name="全球合计",
                quarter="2026Q1",
                tonnes_net=120.0,
                source="mock",
                data_date=date(2026, 3, 31),
            ),
            QuarterlyPurchase(
                country_iso="WGC_AGGR",
                country_name="全球合计",
                quarter="2026Q2",
                tonnes_net=180.0,
                source="mock",
                data_date=date(2026, 6, 30),
            ),
        ],
    )

    rows = cb_data.fetch_h1_2026_by_country()
    # Poland: H1=82.2 → 拆分比例 120/(120+180)=0.4, 180/300=0.6
    #   Q1 = 82.2*0.4 = 32.9, Q2 = 82.2*0.6 = 49.3
    pol = [r for r in rows if r.country_iso == "POL"]
    assert len(pol) == 2
    assert {r.quarter for r in pol} == {"2026Q1", "2026Q2"}
    total_pol = sum(r.tonnes_net for r in pol)
    assert total_pol == pytest.approx(82.2, abs=0.2)

    # China: H1=40.1 → 类似拆分
    chn = [r for r in rows if r.country_iso == "CHN"]
    assert len(chn) == 2
    total_chn = sum(r.tonnes_net for r in chn)
    assert total_chn == pytest.approx(40.1, abs=0.2)

    # Turkey: 卖出 H1=-83.1 → 拆分到 Q1+Q2（负值）
    tur = [r for r in rows if r.country_iso == "TUR"]
    assert len(tur) == 2
    total_tur = sum(r.tonnes_net for r in tur)
    assert total_tur == pytest.approx(-83.1, abs=0.2)


def test_country_names_coverage() -> None:
    """确保主要购金国 ISO 都有中文名映射（前端展示用）。"""
    expected = ["CHN", "POL", "TUR", "IND", "RUS", "KAZ", "CZE", "UZB", "IRN", "WGC_AGGR"]
    for iso in expected:
        assert iso in COUNTRY_NAMES, f"missing {iso}"
        assert COUNTRY_NAMES[iso] != iso, f"{iso} not mapped to Chinese"
