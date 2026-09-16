"""K 线聚合函数测试（V0.64.0 多时间框架核心工具）。

覆盖 ``app.services.trend.aggregate_klines`` 在日/周/月三种粒度下的行为，
重点验证：
- ISO 周界（周一-周日）跨月仍归同周；
- 月聚合按 (year, month) 分桶，跨年独立；
- 单点桶正常输出（OHLC = 自己）；
- volume 求和；
- 空输入兜底返回 []；
- D 模式为浅拷贝（不污染原列表）。
"""

from datetime import date, timedelta

import pytest

from app.repositories.market_data import GoldKline
from app.services.trend import aggregate_klines


def _mk(date_: date, open_: float, close: float, high: float, low: float, volume: float = 100.0) -> GoldKline:
    """构造单根测试 K 线（参数顺序贴近表意，便于阅读）。"""
    return GoldKline(
        date=date_,
        open=open_,
        close=close,
        high=high,
        low=low,
        volume=volume,
    )


def test_v064_aggregate_daily_returns_new_list() -> None:
    """D 模式原样返回（但产出新 list，不与输入共享引用）。"""
    src = [
        _mk(date(2026, 6, 1), 1.0, 1.5, 1.6, 0.9),
        _mk(date(2026, 6, 2), 1.5, 2.0, 2.1, 1.4),
        _mk(date(2026, 6, 3), 2.0, 1.8, 2.2, 1.7),
    ]
    out = aggregate_klines(src, "D")
    assert out == src
    assert out is not src, "D 模式必须返回新 list（避免污染原数据）"


def test_v064_aggregate_weekly_handles_iso_week_boundary() -> None:
    """ISO 周聚合：周一-周日归同周，跨月/跨年周界由 ISO (year, week) 决定。"""
    # 2026-06-01 是周一，跨 2 个 ISO 周：
    #   Week 23: 06-01 ~ 06-07
    #   Week 24: 06-08 ~ 06-14
    base = date(2026, 6, 1)
    src = [
        _mk(base + timedelta(days=i), open_=i + 1, close=i + 1, high=i + 1.1, low=i + 0.9)
        for i in range(14)
    ]
    out = aggregate_klines(src, "W")
    assert len(out) == 2
    # Week 23: open=首日 1.0, close=末日 7.0
    assert out[0].date == base
    assert out[0].open == 1.0
    assert out[0].close == 7.0
    assert out[0].high == pytest.approx(7.1, abs=0.01)
    assert out[0].low == pytest.approx(0.9, abs=0.01)
    # Week 24: open=8.0, close=14.0
    assert out[1].date == base + timedelta(days=7)
    assert out[1].open == 8.0
    assert out[1].close == 14.0


def test_v064_aggregate_month_handles_year_boundary() -> None:
    """月聚合按 (year, month) 分桶，跨年独立分桶（2025-12 / 2026-01 / 2026-02）。"""
    # 显式构造 3 个非连续日期序列（避免 14 天跨度落到同一两个月）
    src = [
        # 2025-12：5 根（12-27 ~ 12-31），close 从 10 → 14
        _mk(date(2025, 12, 27), 10, 10, 10.1, 9.9),
        _mk(date(2025, 12, 28), 11, 11, 11.1, 10.9),
        _mk(date(2025, 12, 29), 12, 12, 12.1, 11.9),
        _mk(date(2025, 12, 30), 13, 13, 13.1, 12.9),
        _mk(date(2025, 12, 31), 14, 14, 14.1, 13.9),
        # 2026-01：5 根（01-01 ~ 01-05），close 从 20 → 24
        _mk(date(2026, 1, 1), 20, 20, 20.1, 19.9),
        _mk(date(2026, 1, 2), 21, 21, 21.1, 20.9),
        _mk(date(2026, 1, 3), 22, 22, 22.1, 21.9),
        _mk(date(2026, 1, 4), 23, 23, 23.1, 22.9),
        _mk(date(2026, 1, 5), 24, 24, 24.1, 23.9),
        # 2026-02：4 根（02-01 ~ 02-04），close 从 30 → 33
        _mk(date(2026, 2, 1), 30, 30, 30.1, 29.9),
        _mk(date(2026, 2, 2), 31, 31, 31.1, 30.9),
        _mk(date(2026, 2, 3), 32, 32, 32.1, 31.9),
        _mk(date(2026, 2, 4), 33, 33, 33.1, 32.9),
    ]
    out = aggregate_klines(src, "M")
    assert len(out) == 3
    # 2025-12 桶
    assert out[0].date == date(2025, 12, 27)
    assert out[0].close == 14.0
    # 2026-01 桶（跨年单独成桶）
    assert out[1].date == date(2026, 1, 1)
    assert out[1].close == 24.0
    # 2026-02 桶
    assert out[2].date == date(2026, 2, 1)
    assert out[2].close == 33.0


def test_v064_aggregate_weekly_single_point() -> None:
    """单点桶（仅 1 个交易日）正常输出，OHLC = 自己。"""
    src = [_mk(date(2026, 6, 3), 5.0, 5.5, 5.8, 4.9, volume=200.0)]
    out_w = aggregate_klines(src, "W")
    assert len(out_w) == 1
    assert out_w[0].open == 5.0
    assert out_w[0].close == 5.5
    assert out_w[0].high == 5.8
    assert out_w[0].low == 4.9
    assert out_w[0].volume == 200.0
    # 单点月
    out_m = aggregate_klines(src, "M")
    assert len(out_m) == 1
    assert out_m[0] == out_w[0]


def test_v064_aggregate_sums_volume() -> None:
    """volume 字段在桶内求和（不取 max/min）。"""
    src = []
    base = date(2026, 6, 1)  # 周一
    for i in range(7):
        v = float(100 + i)
        src.append(_mk(base + timedelta(days=i), open_=v, close=v, high=v, low=v, volume=50.0 * (i + 1)))
    out = aggregate_klines(src, "W")
    assert len(out) == 1
    # 50 + 100 + 150 + 200 + 250 + 300 + 350 = 1400
    assert out[0].volume == pytest.approx(1400.0, abs=0.01)


def test_v064_aggregate_empty_input_returns_empty() -> None:
    """空输入在所有 interval 下均返回 []，不抛错。"""
    for interval in ("D", "W", "M"):
        out = aggregate_klines([], interval)  # type: ignore[arg-type]
        assert out == [], f"空输入 + interval={interval} 应返回 []"
