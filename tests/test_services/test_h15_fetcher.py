"""美联储 H.15 美债收益率 fetcher 单元测试：解析、缓存、网络降级。

不依赖真实网络，所有抓取通过 monkeypatch 注入。
"""

from datetime import date

from app.repositories import market_data
from app.repositories.market_data import (
    USTYield,
    _cache_get,
    _parse_h15_csv,
    fetch_us_treasury_h15,
)


# 真实 H.15 CSV 头部 5 行元数据（截取自联邦储备 H.15 公开 CSV）
_H15_HEADER = (
    '"Series Description","...1-month...","...3-month...","...10-year...","...30-year..."\n'
    '"Unit:","Percent:_Per_Year","Percent:_Per_Year","Percent:_Per_Year","Percent:_Per_Year"\n'
    '"Multiplier:","1","1","1","1"\n'
    '"Currency:","NA","NA","NA","NA"\n'
    '"Unique Identifier: ","H15/H15/...","H15/H15/...","H15/H15/RIFLGFCY10_N.B","H15/H15/RIFLGFCY30_N.B"\n'
)
_H15_COL_HEADER = '"Time Period","RIFLGFCM01_N.B","RIFLGFCM03_N.B","RIFLGFCY10_N.B","RIFLGFCY30_N.B"\n'


def _build_h15_csv(rows: list[tuple[str, str, str, str]]) -> str:
    """构造符合 H.15 格式的 CSV（5 行元数据 + 1 行列名 + N 行数据）。"""
    lines = [_H15_HEADER.rstrip("\n"), _H15_COL_HEADER.rstrip("\n")]
    for date_, m01, m03, y10, y30 in rows:
        lines.append(f"{date_},{m01},{m03},{y10},{y30}")
    return "\n".join(lines) + "\n"


def test_parse_h15_csv_basic() -> None:
    """正常 CSV：返回最近一行双非空的 10Y/30Y。"""
    csv_text = _build_h15_csv([
        ("2026-09-01", "3.85", "3.92", "4.79", "5.27"),
        ("2026-09-02", "3.83", "3.92", "4.79", "5.27"),
        ("2026-09-03", "3.83", "3.89", "4.77", "5.25"),  # 最新
    ])
    result = _parse_h15_csv(csv_text)
    assert result == USTYield(us10y=4.77, us30y=5.25, data_date=date(2026, 9, 3))


def test_parse_h15_csv_skips_empty_tail() -> None:
    """尾部有空行（节假日/未公布）：跳过 10Y/30Y 为空的行。"""
    csv_text = _build_h15_csv([
        ("2026-09-01", "3.85", "3.92", "4.79", "5.27"),
        ("2026-09-02", "", "", "", ""),  # 完全空行
        ("2026-09-03", "3.83", "3.89", "4.77", "5.25"),
        ("2026-09-04", "3.85", "", "", ""),  # 仅 1M 有值
    ])
    result = _parse_h15_csv(csv_text)
    # 从末尾反向找 → 9-04 空 → 9-03 双非空 ✓
    assert result == USTYield(us10y=4.77, us30y=5.25, data_date=date(2026, 9, 3))


def test_parse_h15_csv_partial_null_only_10y() -> None:
    """尾部仅 10Y 有值而 30Y 空：跳过，找上一个双非空行。"""
    csv_text = _build_h15_csv([
        ("2026-09-02", "3.83", "3.92", "4.79", "5.27"),
        ("2026-09-03", "3.83", "3.89", "4.77", ""),  # 仅 30Y 缺失
    ])
    result = _parse_h15_csv(csv_text)
    assert result == USTYield(us10y=4.79, us30y=5.27, data_date=date(2026, 9, 2))


def test_parse_h15_csv_short_input_returns_none() -> None:
    """输入不足 6 行（少于元数据+列名）：返回 None。"""
    assert _parse_h15_csv("a,b,c\n1,2,3\n") is None


def test_parse_h15_csv_missing_columns_returns_none() -> None:
    """缺少 10Y/30Y 列：返回 None。"""
    bad = (
        '"Series Description","col1"\n'
        '"Unit:","X"\n'
        '"Multiplier:","1"\n'
        '"Currency:","NA"\n'
        '"Unique Identifier:","..."\n'
        '"Time Period","col1"\n'
        "2026-09-03,1.5\n"
    )
    assert _parse_h15_csv(bad) is None


def test_parse_h15_csv_malformed_date_returns_none() -> None:
    """日期格式非 YYYY-MM-DD：返回 None（不抛异常）。"""
    csv_text = _build_h15_csv([("bad-date", "3.83", "3.89", "4.77", "5.25")])
    assert _parse_h15_csv(csv_text) is None


async def test_fetch_h15_success(monkeypatch) -> None:
    """网络成功：返回 USTYield，并写入缓存。"""
    import io
    from app.repositories.market_data import _CACHE

    # 清缓存
    with market_data._CACHE_LOCK:
        market_data._CACHE.pop(("ust",), None)

    sample_csv = _build_h15_csv([
        ("2026-09-03", "3.83", "3.89", "4.77", "5.25"),
    ])

    class FakeResp:
        def __init__(self, text: str):
            self._buf = io.BytesIO(text.encode("utf-8"))

        def read(self) -> bytes:
            return self._buf.read()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import urllib.request

    def fake_urlopen(req, timeout=15):
        return FakeResp(sample_csv)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = await fetch_us_treasury_h15()
    assert result == USTYield(us10y=4.77, us30y=5.25, data_date=date(2026, 9, 3))
    # 缓存命中：再次调用直接返回缓存（无副作用）
    r2 = await fetch_us_treasury_h15()
    assert r2 == result
    # 缓存确实写入了
    assert _cache_get(("ust",)) == result


async def test_fetch_h15_network_error(monkeypatch) -> None:
    """网络异常：返回 None，不缓存失败状态（便于快速重试）。"""
    with market_data._CACHE_LOCK:
        market_data._CACHE.pop(("ust",), None)

    import urllib.request

    def fake_urlopen(req, timeout=15):
        raise ConnectionError("network unreachable")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = await fetch_us_treasury_h15()
    assert result is None
    # 失败不缓存：_CACHE 中无 ("ust",) 键
    with market_data._CACHE_LOCK:
        assert ("ust",) not in market_data._CACHE


async def test_fetch_h15_malformed_response(monkeypatch) -> None:
    """HTTP 200 但 CSV 损坏：返回 None，不抛异常。"""
    import io
    import urllib.request

    with market_data._CACHE_LOCK:
        market_data._CACHE.pop(("ust",), None)

    class FakeResp:
        def __init__(self):
            self._buf = io.BytesIO(b"this is not CSV")

        def read(self) -> bytes:
            return self._buf.read()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=15: FakeResp())

    result = await fetch_us_treasury_h15()
    assert result is None


async def test_fetch_h15_timeout(monkeypatch) -> None:
    """网络超时：返回 None，不缓存失败状态。"""
    import urllib.request

    with market_data._CACHE_LOCK:
        market_data._CACHE.pop(("ust",), None)

    def fake_urlopen(req, timeout=15):
        raise TimeoutError("fetch timed out")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = await fetch_us_treasury_h15()
    assert result is None


async def test_repo_marks_ust_source(monkeypatch) -> None:
    """MarketDataRepository.get_us_treasury_yields 标记 source_meta 中 ust 状态。"""
    from app.repositories.market_data import MarketDataRepository

    sample = USTYield(us10y=4.5, us30y=5.0, data_date=date(2026, 9, 3))

    async def fake_fetch():
        return sample

    monkeypatch.setattr(market_data, "fetch_us_treasury_h15", fake_fetch)

    repo = MarketDataRepository()
    result = await repo.get_us_treasury_yields()

    assert result == sample
    meta = repo.source_meta()
    assert meta["ust"]["status"] == "live"
    assert meta["ust"]["last_date"] == date(2026, 9, 3)


async def test_repo_marks_ust_failed(monkeypatch) -> None:
    """H.15 拉取失败时，source_meta 标记 ust 为 mock。"""
    from app.repositories.market_data import MarketDataRepository

    async def fake_fetch():
        return None

    monkeypatch.setattr(market_data, "fetch_us_treasury_h15", fake_fetch)

    repo = MarketDataRepository()
    result = await repo.get_us_treasury_yields()

    assert result is None
    meta = repo.source_meta()
    assert meta["ust"]["status"] == "mock"