"""资金流数据源解析测试（V0.120.0）。

重点是**不依赖外网**的部分：CFTC 年度包解析、A 股融资余额的两所合并、日期解析。

⚠ 外网接口（CFTC / FRED / 东财 / SSE / 央行）**不在单元测试里调** ——
门禁脚本 ``scripts/_verify_money_flow.mjs`` 走真实 API 验证「线上真的取得到数」，
单元测试只保证「拿到数据后解析不出错」。
"""

from __future__ import annotations

import sys
import types
from datetime import date, datetime

import pytest

from app.repositories import money_flow_sources as mfs

# ───────────────────── A 股融资余额（两所合并）─────────────────────


class _FakeFrame:
    """极简 DataFrame 替身：只支持列索引（本模块用不到 pandas 语义）。"""

    def __init__(self, columns: dict[str, list]) -> None:
        self._cols = columns

    def __getitem__(self, key):
        return self._cols[key]


def _install_fake_akshare(monkeypatch, sh_rows, sz_rows):
    """把 akshare 塞进 sys.modules，返回两所的假 DataFrame。"""
    fake = types.ModuleType("akshare")

    def _sh():
        return _FakeFrame({"日期": [r[0] for r in sh_rows], "融资余额": [r[1] for r in sh_rows]})

    def _sz():
        return _FakeFrame({"日期": [r[0] for r in sz_rows], "融资余额": [r[1] for r in sz_rows]})

    fake.macro_china_market_margin_sh = _sh
    fake.macro_china_market_margin_sz = _sz
    monkeypatch.setitem(sys.modules, "akshare", fake)


def test_融资余额_两所按日期相加并升序(monkeypatch):
    _install_fake_akshare(
        monkeypatch,
        sh_rows=[("2026-10-23", 100.0), ("2026-10-22", 90.0)],
        sz_rows=[("2026-10-23", 50.0), ("2026-10-22", 45.0)],
    )
    rows = mfs._cn_margin_sync()
    assert rows == [(date(2026, 10, 22), 135.0), (date(2026, 10, 23), 150.0)]
    assert rows == sorted(rows), "必须按日期升序"


def test_融资余额_只取两所都有数据的日期(monkeypatch):
    _install_fake_akshare(
        monkeypatch,
        sh_rows=[("2026-10-23", 100.0), ("2026-10-22", 90.0)],
        sz_rows=[("2026-10-22", 45.0)],
    )
    rows = mfs._cn_margin_sync()
    assert [r[0] for r in rows] == [date(2026, 10, 22)]


def test_融资余额_日期列是datetime对象也能解析(monkeypatch):
    _install_fake_akshare(
        monkeypatch,
        sh_rows=[(datetime(2026, 10, 23, 15, 0), 100.0)],
        sz_rows=[(datetime(2026, 10, 23, 15, 0), 50.0)],
    )
    rows = mfs._cn_margin_sync()
    assert rows == [(date(2026, 10, 23), 150.0)]


@pytest.mark.parametrize(
    "raw,expect",
    [
        ("2026-10-23", date(2026, 10, 23)),
        ("2026/10/23", date(2026, 10, 23)),
        ("2026-10-23 15:00:00", date(2026, 10, 23)),
        ("乱七八糟", None),
    ],
)
def test_日期解析_多种格式(raw, expect):
    assert mfs._parse_ymd(raw) == expect


def test_融资余额_不依赖pandas():
    """src/ 里不直接 import pandas（akshare 的传递依赖不算声明）。

    `scripts/check_deps.py` 会把 src/ 下所有三方 import 拿去比对 pyproject 依赖 ——
    直接 import pandas 会让门禁变红，而本模块完全用不到 pandas 的语义。
    """
    import inspect

    src = inspect.getsource(mfs)
    assert "import pandas" not in src
    assert "pd." not in src


# ───────────────────── CFTC 分类持仓解析 ─────────────────────

_CFTC_HEADER = (
    "Market_and_Exchange_Names,As_of_Date_In_Form_YYMMDD,"
    "CFTC_Contract_Market_Code,Open_Interest_All,"
    "M_Money_Positions_Long_All,M_Money_Positions_Short_All"
)


def test_CFTC_解析出黄金管理基金净多与占OI比():
    text = "\n".join(
        [
            _CFTC_HEADER,
            "GOLD - COMMODITY EXCHANGE INC.,261020,088691,400,300,100",
            "CRUDE OIL - NEW YORK MERCANTILE EXCHANGE,261020,067651,9999,1,1",
        ]
    )
    points = mfs._parse_cftc_gold(text)
    assert len(points) == 1, "只应保留黄金那一条（合约代码 088691）"
    p = points[0]
    assert p.obs_date == date(2026, 10, 20)
    assert p.net_long == 200  # long 300 - short 100
    assert p.open_interest == 400
    assert p.net_pct_oi == pytest.approx(50.0)


def test_CFTC_多周按日期升序():
    text = "\n".join(
        [
            _CFTC_HEADER,
            "GOLD,261013,088691,400,300,100",
            "GOLD,260915,088691,400,250,150",
            "GOLD,260922,088691,400,280,120",
        ]
    )
    points = mfs._parse_cftc_gold(text)
    assert [p.obs_date for p in points] == [
        date(2026, 9, 15),
        date(2026, 9, 22),
        date(2026, 10, 13),
    ]


def test_CFTC_空文本不抛异常():
    assert mfs._parse_cftc_gold("") == []


def test_CFTC_缺列时返回空而不是崩():
    """年度包格式若变（缺列），必须安静跳过而不是把整个因子打挂。"""
    assert mfs._parse_cftc_gold("a,b,c\n1,2,3") == []


def test_CFTC_净多占OI比_持仓为0时不除零():
    text = "\n".join([_CFTC_HEADER, "GOLD,261020,088691,0,0,0"])
    points = mfs._parse_cftc_gold(text)
    assert points[0].net_pct_oi == 0.0


# ───────────────────── 周网格锚点（week_end_days）─────────────────────


def test_周末日_每个ISO周只留最后一个交易日():
    """周频因子的观测锚点：一周一个，周内哪一天当周最后一天就取哪一天。"""
    days = [
        date(2026, 10, 26),  # 周一
        date(2026, 10, 27),  # 周二
        date(2026, 10, 28),  # 周三
        date(2026, 10, 29),  # 周四
        date(2026, 10, 30),  # 周五
        date(2026, 11, 2),  # 下周一
        date(2026, 11, 6),  # 下周五
    ]
    got = mfs.week_end_days(days, today=date(2026, 11, 7))
    assert got == [date(2026, 10, 30), date(2026, 11, 6)]


def test_周末日_本周还没过完时丢掉最后一个锚点():
    """⚠️ 关键：锚点若跟着「最新交易日」走，每日调度就会一天写一行。

    本周还没过完 ⇒ 最后一个锚点会随每天推进 ⇒ 必须丢掉，
    否则窗口里同一周被重复计入（4 周累计窗口在相邻几天几乎是同一个数）。
    """
    days = [date(2026, 10, 23), date(2026, 10, 26), date(2026, 10, 27)]
    # 2026-10-27 是周二；本周（10-26 ~ 11-01）的周日是 11-01，还没到
    got = mfs.week_end_days(days, today=date(2026, 10, 27))
    assert got == [date(2026, 10, 23)]


def test_周末日_本周过完后保留最后一个锚点():
    days = [date(2026, 10, 23), date(2026, 10, 26), date(2026, 10, 27)]
    # 周六：本周（10-26 ~ 11-01）已经过了（周日 11-01 > 今天？否，11-01 > 10-31）
    got = mfs.week_end_days(days, today=date(2026, 10, 31))
    assert got == [date(2026, 10, 23), date(2026, 10, 27)]


def test_周末日_乱序输入也能算对():
    days = [date(2026, 10, 30), date(2026, 10, 26), date(2026, 10, 27)]
    got = mfs.week_end_days(days, today=date(2026, 11, 7))
    assert got == [date(2026, 10, 30)]


def test_周末日_节假日短周取当周最后一个交易日():
    """国庆假期那周只有 09-28/29/30 三个交易日 ⇒ 锚点是 09-30（周三）。"""
    days = [
        date(2026, 9, 24),
        date(2026, 9, 28),
        date(2026, 9, 29),
        date(2026, 9, 30),
        date(2026, 10, 9),
    ]
    got = mfs.week_end_days(days, today=date(2026, 10, 10))
    assert got == [date(2026, 9, 24), date(2026, 9, 30), date(2026, 10, 9)]


# ───────────────────── 月网格锚点（month_end_days）─────────────────────


def test_月末锚点_每个月一个且是日历月末():
    """月频因子的观测锚点 = **日历月末**（不要求当天真的有观测）。"""
    days = [
        date(2026, 9, 2),
        date(2026, 9, 30),
        date(2026, 10, 7),
        date(2026, 10, 21),
    ]
    got = mfs.month_end_days(days, today=date(2026, 11, 5))
    # 9 月末 = 09-30；10 月末 = 10-31（锚点日当天没有观测也要给）
    assert got == [date(2026, 9, 30), date(2026, 10, 31)]


def test_月末锚点_当月还没过完时丢掉():
    """⚠️ 关键：锚点若跟着「最新观测」走，每日调度就会一天写一行。

    当月的「月末」其实是月内至今 ⇒ 与历史行的「月末 vs 月末」不是同一个量。
    """
    days = [date(2026, 9, 30), date(2026, 10, 7), date(2026, 10, 21)]
    got = mfs.month_end_days(days, today=date(2026, 10, 28))
    assert got == [date(2026, 9, 30)]


def test_月末锚点_跨月后前进一格():
    days = [date(2026, 9, 30), date(2026, 10, 7)]
    assert mfs.month_end_days(days, today=date(2026, 10, 28)) == [date(2026, 9, 30)]
    assert mfs.month_end_days(days, today=date(2026, 11, 1)) == [
        date(2026, 9, 30),
        date(2026, 10, 31),
    ]


def test_月末锚点_乱序输入也能算对():
    days = [date(2026, 10, 21), date(2026, 9, 2), date(2026, 9, 30)]
    got = mfs.month_end_days(days, today=date(2026, 11, 5))
    assert got == [date(2026, 9, 30), date(2026, 10, 31)]


def test_月末锚点_空输入返回空():
    assert mfs.month_end_days([], today=date(2026, 11, 5)) == []


def test_asof_取当天或之前最近一条():
    points = [
        (date(2026, 9, 30), 100.0),
        (date(2026, 10, 7), 200.0),
        (date(2026, 10, 21), 300.0),
    ]
    asof = mfs.asof_series(points)
    assert asof(date(2026, 9, 30)) == 100.0
    assert asof(date(2026, 10, 15)) == 200.0
    assert asof(date(2026, 10, 21)) == 300.0
    assert asof(date(2026, 10, 31)) == 300.0
    assert asof(date(2026, 9, 1)) is None
