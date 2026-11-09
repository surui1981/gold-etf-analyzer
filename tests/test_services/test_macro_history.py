"""``app/services/macro_history.py`` 的离线单测（V0.124.0）。

这个模块是**回填与测量共用的唯一口径真源** —— 它错了，
生产表和证据脚本会**一起错**（两边都"自洽"却都错），所以必须锁死。

三条最关键的不变量：

1. **不前视**：观测日 > D 的读数绝不出现在 D 这一天；
2. **不兜底**：第一条观测之前**不写行**（不写 0、不写常数）；
3. **日历日粒度**：区间内每个日历日都有一行（含周末，值沿用上一条观测）。

⚠ 断言**不联网**、不碰数据库 ⇒ 门禁稳定可重入。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.services.macro_history import (
    LOWFREQ_LAG_DAYS,
    asof_rows,
    calendar_days,
    cb_gold_t12m_series,
    daily_available_at,
    make_observation,
    merge_rows,
    next_business_day,
    previous_quarter,
    quarter_end,
)

# ───────────────────── 日历 ─────────────────────


def test_calendar_days_是闭区间() -> None:
    assert calendar_days(date(2026, 1, 1), date(2026, 1, 3)) == [
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 3),
    ]


def test_calendar_days_结束早于开始返回空() -> None:
    assert calendar_days(date(2026, 1, 3), date(2026, 1, 1)) == []


def test_calendar_days_单日() -> None:
    assert calendar_days(date(2026, 1, 1), date(2026, 1, 1)) == [date(2026, 1, 1)]


# ───────────────────── as-of 展开 ─────────────────────


def test_asof_首条观测之前不写行() -> None:
    """⚠ 防前视 + 不兜底：第一条观测之前**没有读数** ⇒ 不写行。

    写成 0 或写成第一条观测的值都会污染滚动分位窗口
    （「这期没数据」被伪装成「这期就是这个数」）。
    """
    rows = asof_rows(
        [(date(2026, 1, 5), 1.0, "2026-01-05", "src")],
        factor_key="x",
        start=date(2026, 1, 1),
        end=date(2026, 1, 7),
    )
    assert [r[0] for r in rows] == [
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
    ]


def test_asof_不使用未来观测() -> None:
    """观测日 > D 的读数绝不能提前出现（这是整个回填模块存在的理由）。"""
    rows = asof_rows(
        [
            (date(2026, 1, 1), 10.0, "2026-01-01", "src"),
            (date(2026, 1, 10), 99.0, "2026-01-10", "src"),
        ],
        factor_key="x",
        start=date(2026, 1, 1),
        end=date(2026, 1, 12),
    )
    by_day = {r[0]: r[2] for r in rows}
    assert by_day[date(2026, 1, 1)] == 10.0
    assert by_day[date(2026, 1, 9)] == 10.0
    assert by_day[date(2026, 1, 10)] == 99.0


def test_asof_每个日历日一行含周末() -> None:
    """线上落表每个**日历日**都有一行（周末也有，值沿用上一交易日）。

    ⇒ 重建必须是日历日粒度，否则滚动带窗口（252 日历日）里的样本数与线上不一致。
    """
    rows = asof_rows(
        [(date(2026, 1, 2), 4.0, "2026-01-02", "src")],  # 周五
        factor_key="x",
        start=date(2026, 1, 2),
        end=date(2026, 1, 5),  # 周一~周五
    )
    assert len(rows) == 4  # 1/3 周六、1/4 周日、1/5 周一
    assert all(r[2] == 4.0 for r in rows)


def test_asof_data_date与source沿用观测() -> None:
    rows = asof_rows(
        [(date(2026, 1, 2), 4.0, "2026-01-02", "美联储 H.15")],
        factor_key="us10y",
        start=date(2026, 1, 2),
        end=date(2026, 1, 3),
    )
    assert rows[0][1] == "us10y"
    assert rows[0][3] == "2026-01-02"
    assert rows[0][4] == "美联储 H.15"


def test_asof_同日多条取最后一条() -> None:
    rows = asof_rows(
        [
            (date(2026, 1, 1), 1.0, "2026-01-01", "src"),
            (date(2026, 1, 1), 2.0, "2026-01-01", "src2"),
        ],
        factor_key="x",
        start=date(2026, 1, 1),
        end=date(2026, 1, 1),
    )
    assert len(rows) == 1
    assert rows[0][2] == 2.0
    assert rows[0][4] == "src2"


def test_asof_空观测返回空() -> None:
    assert asof_rows([], factor_key="x", start=date(2026, 1, 1), end=date(2026, 1, 5)) == []


def test_asof_观测乱序也能正确排序() -> None:
    rows = asof_rows(
        [
            (date(2026, 1, 3), 3.0, "2026-01-03", "src"),
            (date(2026, 1, 1), 1.0, "2026-01-01", "src"),
        ],
        factor_key="x",
        start=date(2026, 1, 1),
        end=date(2026, 1, 3),
    )
    assert [r[2] for r in rows] == [1.0, 1.0, 3.0]


def test_asof_区间完全在观测之前则无行() -> None:
    rows = asof_rows(
        [(date(2026, 1, 10), 1.0, "2026-01-10", "src")],
        factor_key="x",
        start=date(2026, 1, 1),
        end=date(2026, 1, 5),
    )
    assert rows == []


# ───────────────────── 季度工具 ─────────────────────


@pytest.mark.parametrize(
    "quarter,expected",
    [
        ("2014Q1", date(2014, 3, 31)),
        ("2014Q2", date(2014, 6, 30)),
        ("2014Q3", date(2014, 9, 30)),
        ("2014Q4", date(2014, 12, 31)),
        ("2026Q3", date(2026, 9, 30)),
    ],
)
def test_quarter_end(quarter: str, expected: date) -> None:
    assert quarter_end(quarter) == expected


@pytest.mark.parametrize("bad", ["2014Q5", "2014Q", "14Q1", "abcd", ""])
def test_quarter_end_非法标签抛错(bad: str) -> None:
    with pytest.raises(ValueError):
        quarter_end(bad)


@pytest.mark.parametrize(
    "quarter,expected",
    [
        ("2014Q2", "2014Q1"),
        ("2014Q1", "2013Q4"),
        ("2016Q4", "2016Q3"),
    ],
)
def test_previous_quarter(quarter: str, expected: str) -> None:
    assert previous_quarter(quarter) == expected


# ───────────────────── cb_gold 滚动 4 季合计 ─────────────────────


def test_cb_gold_不足四个季度不产出() -> None:
    quarters = [("2014Q1", 100.0), ("2014Q2", 110.0), ("2014Q3", 120.0)]
    assert cb_gold_t12m_series(quarters) == []


def test_cb_gold_第四个季度起才有窗口() -> None:
    quarters = [
        ("2014Q1", 100.0),
        ("2014Q2", 110.0),
        ("2014Q3", 120.0),
        ("2014Q4", 130.0),
        ("2015Q1", 140.0),
    ]
    series = cb_gold_t12m_series(quarters)
    assert len(series) == 2
    # 第 4 个季度：2014Q1..2014Q4 = 460
    assert series[0][0] == date(2014, 12, 31) + timedelta(days=LOWFREQ_LAG_DAYS["cb_gold"])
    assert series[0][1] == 460.0
    assert series[0][2] == "2014Q1–2014Q4"
    # 第 5 个季度：2014Q2..2015Q1 = 500
    assert series[1][0] == date(2015, 3, 31) + timedelta(days=LOWFREQ_LAG_DAYS["cb_gold"])
    assert series[1][1] == 500.0
    assert series[1][2] == "2014Q2–2015Q1"


def test_cb_gold_标签用短横线且观测日为期末加发布滞后() -> None:
    quarters = [
        ("2025Q3", 226.3),
        ("2025Q4", 209.9),
        ("2026Q1", 57.7),
        ("2026Q2", 296.3),
    ]
    series = cb_gold_t12m_series(quarters)
    assert len(series) == 1
    assert series[0][2] == "2025Q3–2026Q2"  # U+2013，与线上 t12m_total 一致
    # 可得日 = 期末 + WGC GDT 的实测发布滞后（39 天）
    assert series[0][0] == date(2026, 6, 30) + timedelta(days=LOWFREQ_LAG_DAYS["cb_gold"])
    assert series[0][1] == 790.2  # 合计行口径（不是各国行相加的 842.6）
    assert series[0][3] == "央行购金表自动汇总"


def test_cb_gold_乱序输入按季度排序() -> None:
    quarters = [
        ("2015Q1", 140.0),
        ("2014Q1", 100.0),
        ("2014Q2", 110.0),
        ("2014Q3", 120.0),
        ("2014Q4", 130.0),
    ]
    series = cb_gold_t12m_series(quarters)
    assert series[0][0] == date(2014, 12, 31) + timedelta(days=LOWFREQ_LAG_DAYS["cb_gold"])
    assert series[0][1] == 460.0


# ───────────────────── 合并 ─────────────────────


def test_merge_rows_同键后者覆盖() -> None:
    a = [(date(2026, 1, 1), "x", 1.0, "d", "s1")]
    b = [(date(2026, 1, 1), "x", 2.0, "d", "s2")]
    merged = merge_rows(a, b)
    assert len(merged) == 1
    assert merged[0][2] == 2.0
    assert merged[0][4] == "s2"


def test_merge_rows_不同键都保留且按日期排序() -> None:
    a = [(date(2026, 1, 2), "x", 1.0, "d", "s")]
    b = [(date(2026, 1, 1), "y", 2.0, "d", "s")]
    merged = merge_rows(a, b)
    assert [(r[0], r[1]) for r in merged] == [
        (date(2026, 1, 1), "y"),
        (date(2026, 1, 2), "x"),
    ]


# ───────────────────── 发布时滞模型 ─────────────────────


def test_next_business_day_周五到周一() -> None:
    assert next_business_day(date(2026, 11, 6)) == date(2026, 11, 9)


def test_next_business_day_工作日顺延一天() -> None:
    assert next_business_day(date(2026, 11, 9)) == date(2026, 11, 10)


def test_next_business_day_周六到周一() -> None:
    assert next_business_day(date(2026, 11, 7)) == date(2026, 11, 9)


def test_next_business_day_周日至周一() -> None:
    assert next_business_day(date(2026, 11, 8)) == date(2026, 11, 9)


def test_next_business_day_长周末() -> None:
    """12/26 是周六 ⇒ 下个工作日是 12/28（周一），不是 12/29。"""
    assert next_business_day(date(2026, 12, 26)) == date(2026, 12, 28)


def test_daily_available_at_H15走工作日规则() -> None:
    """H.15 周五发布 ⇒ 周五的读数最早「下周一 + 1 天」可得。

    采集在 07:00 北京时间跑 ⇒ 采集日能看到的最新文件是前一日发布的那个。
    """
    assert daily_available_at(date(2026, 11, 6), source="美联储 H.15") == date(2026, 11, 10)


def test_daily_available_at_FRED走工作日规则() -> None:
    assert daily_available_at(date(2026, 11, 3), source="FRED") == date(2026, 11, 5)


def test_daily_available_at_Yahoo次日可得() -> None:
    """Yahoo 是收盘后即出 ⇒ 只要隔一天（采集日 07:00 北京 = 前一日 23:00 UTC）。"""
    assert daily_available_at(date(2026, 11, 5), source="yahoo") == date(2026, 11, 6)


def test_daily_available_at_绝不会早于观测日() -> None:
    """硬不变量：可得日 > 观测日（否则就是「当天就能拿到未来数据」）。"""
    for day in calendar_days(date(2026, 1, 1), date(2026, 3, 31)):
        for src in ("美联储 H.15", "FRED", "yahoo"):
            assert daily_available_at(day, source=src) > day


def test_make_observation_低频因子用固定滞后() -> None:
    obs = make_observation("us_gov_debt", date(2026, 6, 30), 100.0, "FRED 季度")
    assert obs[0] == date(2026, 6, 30) + timedelta(days=LOWFREQ_LAG_DAYS["us_gov_debt"])
    assert obs[1] == 100.0
    assert obs[3] == "FRED 季度"


def test_make_observation_data_date默认取观测日() -> None:
    obs = make_observation("us10y", date(2026, 11, 3), 4.3, "美联储 H.15")
    assert obs[2] == "2026-11-03"


def test_make_observation_data_date可显式覆盖() -> None:
    obs = make_observation(
        "cb_gold", date(2026, 6, 30), 790.2, "央行购金表自动汇总", data_date_text="2025Q3–2026Q2"
    )
    assert obs[2] == "2025Q3–2026Q2"
    assert obs[0] == date(2026, 6, 30) + timedelta(days=LOWFREQ_LAG_DAYS["cb_gold"])


def test_make_observation_低频滞后表覆盖四个因子() -> None:
    assert set(LOWFREQ_LAG_DAYS) == {"us_gov_debt", "eu_gov_debt", "cn_gov_debt", "cb_gold"}


def test_make_observation_低频滞后都是正数() -> None:
    assert all(v > 0 for v in LOWFREQ_LAG_DAYS.values())


def test_make_observation_观测与可得日不前视() -> None:
    """硬不变量：观测（可得）日必须严格晚于源数据的观测日。"""
    for key in ("us10y", "dxy", "vix"):
        for day in calendar_days(date(2026, 1, 1), date(2026, 3, 31)):
            obs = make_observation(key, day, 1.0, "美联储 H.15")
            assert obs[0] > day
