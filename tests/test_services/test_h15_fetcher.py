"""美联储 H.15 美债收益率 fetcher 单元测试：解析、缓存、网络降级。

不依赖真实网络，所有抓取通过 monkeypatch 注入。
"""

from datetime import date

from app.repositories.market_data import USTYield, _parse_h15_csv, parse_h15_history

# 真实 H.15 CSV 头部 5 行元数据（截取自联邦储备 H.15 公开 CSV）
_H15_HEADER = (
    '"Series Description","...1-month...","...3-month...","...10-year...","...30-year..."\n'
    '"Unit:","Percent:_Per_Year","Percent:_Per_Year","Percent:_Per_Year","Percent:_Per_Year"\n'
    '"Multiplier:","1","1","1","1"\n'
    '"Currency:","NA","NA","NA","NA"\n'
    '"Unique Identifier: ","H15/H15/...","H15/H15/...","H15/H15/RIFLGFCY10_N.B","H15/H15/RIFLGFCY30_N.B"\n'
)
_H15_COL_HEADER = (
    '"Time Period","RIFLGFCM01_N.B","RIFLGFCM03_N.B","RIFLGFCY10_N.B","RIFLGFCY30_N.B"\n'
)


def _build_h15_csv(rows: list[tuple[str, str, str, str]]) -> str:
    """构造符合 H.15 格式的 CSV（5 行元数据 + 1 行列名 + N 行数据）。"""
    lines = [_H15_HEADER.rstrip("\n"), _H15_COL_HEADER.rstrip("\n")]
    for date_, m01, m03, y10, y30 in rows:
        lines.append(f"{date_},{m01},{m03},{y10},{y30}")
    return "\n".join(lines) + "\n"


def _build_h15_csv_with_2y(rows: list[tuple[str, str, str, str, str]]) -> str:
    """构造**带 2Y 列**的 H.15 CSV（V0.118.0 新增因子的数据来源）。

    真实 H.15 CSV 的列顺序：1M / 3M / 2Y / 10Y / 30Y。2Y 列名固定为
    ``RIFLGFCY02_N.B``（常量 ``_H15_COL_2Y``）。
    """
    lines = [
        _H15_HEADER.rstrip("\n"),
        '"Time Period","RIFLGFCM01_N.B","RIFLGFCM03_N.B",'
        '"RIFLGFCY02_N.B","RIFLGFCY10_N.B","RIFLGFCY30_N.B"',
    ]
    for date_, m01, m03, y2, y10, y30 in rows:
        lines.append(f"{date_},{m01},{m03},{y2},{y10},{y30}")
    return "\n".join(lines) + "\n"


def test_parse_h15_csv_basic() -> None:
    """正常 CSV：返回最近一行双非空的 10Y/30Y。"""
    csv_text = _build_h15_csv(
        [
            ("2026-09-01", "3.85", "3.92", "4.79", "5.27"),
            ("2026-09-02", "3.83", "3.92", "4.79", "5.27"),
            ("2026-09-03", "3.83", "3.89", "4.77", "5.25"),  # 最新
        ]
    )
    result = _parse_h15_csv(csv_text)
    assert result == USTYield(us10y=4.77, us30y=5.25, data_date=date(2026, 9, 3))


def test_parse_h15_csv_skips_empty_tail() -> None:
    """尾部有空行（节假日/未公布）：跳过 10Y/30Y 为空的行。"""
    csv_text = _build_h15_csv(
        [
            ("2026-09-01", "3.85", "3.92", "4.79", "5.27"),
            ("2026-09-02", "", "", "", ""),  # 完全空行
            ("2026-09-03", "3.83", "3.89", "4.77", "5.25"),
            ("2026-09-04", "3.85", "", "", ""),  # 仅 1M 有值
        ]
    )
    result = _parse_h15_csv(csv_text)
    # 从末尾反向找 → 9-04 空 → 9-03 双非空 ✓
    assert result == USTYield(us10y=4.77, us30y=5.25, data_date=date(2026, 9, 3))


def test_parse_h15_csv_partial_null_only_10y() -> None:
    """尾部仅 10Y 有值而 30Y 空：跳过，找上一个双非空行。"""
    csv_text = _build_h15_csv(
        [
            ("2026-09-02", "3.83", "3.92", "4.79", "5.27"),
            ("2026-09-03", "3.83", "3.89", "4.77", ""),  # 仅 30Y 缺失
        ]
    )
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
    """网络成功：AkshareTreasuryYieldProvider.get_treasury_yields 返回 USTYield。"""
    import io

    sample_csv = _build_h15_csv(
        [
            ("2026-09-03", "3.83", "3.89", "4.77", "5.25"),
        ]
    )

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

    # V0.59.0：H.15 拉取走 AkshareTreasuryYieldProvider
    from app.repositories.market_providers import AkshareTreasuryYieldProvider

    provider = AkshareTreasuryYieldProvider()
    result = await provider.get_treasury_yields()
    assert result == USTYield(us10y=4.77, us30y=5.25, data_date=date(2026, 9, 3))


async def test_fetch_h15_network_error(monkeypatch) -> None:
    """网络异常：provider 返回 None（不抛异常）。"""
    import urllib.request

    def fake_urlopen(req, timeout=15):
        raise ConnectionError("network unreachable")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    from app.repositories.market_providers import AkshareTreasuryYieldProvider

    provider = AkshareTreasuryYieldProvider()
    result = await provider.get_treasury_yields()
    assert result is None


async def test_fetch_h15_malformed_response(monkeypatch) -> None:
    """HTTP 200 但 CSV 损坏：provider 返回 None，不抛异常。"""
    import io
    import urllib.request

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

    from app.repositories.market_providers import AkshareTreasuryYieldProvider

    provider = AkshareTreasuryYieldProvider()
    result = await provider.get_treasury_yields()
    assert result is None


async def test_fetch_h15_timeout(monkeypatch) -> None:
    """网络超时：provider 返回 None（不抛异常）。"""
    import urllib.request

    def fake_urlopen(req, timeout=15):
        raise TimeoutError("fetch timed out")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    from app.repositories.market_providers import AkshareTreasuryYieldProvider

    provider = AkshareTreasuryYieldProvider()
    result = await provider.get_treasury_yields()
    assert result is None


# ───────────────────── V0.118.0 · 2Y 列 + 全量历史解析 ─────────────────────


def test_parse_h15_csv_reads_2y_column() -> None:
    """带 2Y 列的 CSV → us2y 被解析出来（V0.118.0 新增因子）。"""
    csv_text = _build_h15_csv_with_2y(
        [
            ("2026-09-02", "3.83", "3.92", "4.21", "4.79", "5.27"),
            ("2026-09-03", "3.83", "3.89", "4.20", "4.77", "5.25"),
        ]
    )
    result = _parse_h15_csv(csv_text)
    assert result is not None
    assert result.us2y == 4.20
    assert result.us10y == 4.77
    assert result.us30y == 5.25
    assert result.data_date == date(2026, 9, 3)


def test_parse_h15_csv_without_2y_column_keeps_us2y_none() -> None:
    """没有 2Y 列 → us2y 为 None（不牵连 10Y/30Y）。"""
    csv_text = _build_h15_csv([("2026-09-03", "3.83", "3.89", "4.77", "5.25")])
    result = _parse_h15_csv(csv_text)
    assert result is not None
    assert result.us2y is None


def test_parse_h15_history_returns_every_row() -> None:
    """全量历史解析：每行都吐出来（不是「最近一行」语义），按日期升序。"""
    csv_text = _build_h15_csv_with_2y(
        [
            ("2026-09-03", "3.83", "3.89", "4.20", "4.77", "5.25"),
            ("2026-09-01", "3.85", "3.92", "4.23", "4.79", "5.27"),
            ("2026-09-02", "3.83", "3.92", "4.21", "4.79", "5.27"),
        ]
    )
    rows = parse_h15_history(csv_text)
    assert len(rows) == 3
    assert [r[0] for r in rows] == [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)]
    assert rows[0] == (date(2026, 9, 1), 4.23, 4.79, 5.27)


def test_parse_h15_history_skips_rows_missing_10y_or_30y() -> None:
    """10Y/30Y 缺失的行直接跳过（回填宁可少一天也不要造脏数据）。"""
    csv_text = _build_h15_csv_with_2y(
        [
            ("2026-09-01", "3.85", "3.92", "4.23", "4.79", "5.27"),
            ("2026-09-02", "3.83", "3.92", "4.21", "", ""),  # 10Y/30Y 缺失
            ("2026-09-03", "3.83", "3.89", "4.20", "4.77", "5.25"),
        ]
    )
    rows = parse_h15_history(csv_text)
    assert [r[0] for r in rows] == [date(2026, 9, 1), date(2026, 9, 3)]


def test_parse_h15_history_without_2y_column_yields_none_2y() -> None:
    """无 2Y 列 → us2y 为 None（其余照常）。"""
    csv_text = _build_h15_csv([("2026-09-03", "3.83", "3.89", "4.77", "5.25")])
    rows = parse_h15_history(csv_text)
    assert rows == [(date(2026, 9, 3), None, 4.77, 5.25)]


def test_parse_h15_history_garbage_returns_empty() -> None:
    """非 CSV 输入 → 空列表（不抛异常）。"""
    assert parse_h15_history("this is not CSV") == []


async def test_repo_marks_ust_source() -> None:
    """MarketDataRepository.get_us_treasury_yields 标记 source_meta 中 ust 状态。

    V0.59.0：通过 bundle.treasury 注入 provider；测试用 fake bundle 替代 monkeypatch。
    """
    from app.repositories.market_data import MarketDataRepository
    from app.repositories.market_providers import MarketProviderBundle

    sample = USTYield(us10y=4.5, us30y=5.0, data_date=date(2026, 9, 3))

    class FakeTreasury:
        async def get_treasury_yields(self):
            return sample

    class FakeHistory:
        async def get_history(self, symbol="518880", days=60):
            return []

        async def get_gram_history(self, symbol="Au99.99", days=60):
            return []

        async def get_us_gold_history(self, symbol="GC", days=60):
            return []

    class FakeLive:
        async def get_live_quote(self):
            return None

    bundle = MarketProviderBundle(history=FakeHistory(), live=FakeLive(), treasury=FakeTreasury())
    repo = MarketDataRepository(bundle=bundle)
    result = await repo.get_us_treasury_yields()

    assert result == sample
    meta = repo.source_meta()
    assert meta["ust"]["status"] == "live"
    assert meta["ust"]["last_date"] == date(2026, 9, 3)


async def test_repo_marks_ust_failed() -> None:
    """H.15 拉取失败时，source_meta 标记 ust 为 mock。"""
    from app.repositories.market_data import MarketDataRepository
    from app.repositories.market_providers import MarketProviderBundle

    class FakeTreasury:
        async def get_treasury_yields(self):
            return None

    class FakeHistory:
        async def get_history(self, symbol="518880", days=60):
            return []

        async def get_gram_history(self, symbol="Au99.99", days=60):
            return []

        async def get_us_gold_history(self, symbol="GC", days=60):
            return []

    class FakeLive:
        async def get_live_quote(self):
            return None

    bundle = MarketProviderBundle(history=FakeHistory(), live=FakeLive(), treasury=FakeTreasury())
    repo = MarketDataRepository(bundle=bundle)
    result = await repo.get_us_treasury_yields()

    assert result is None
    meta = repo.source_meta()
    assert meta["ust"]["status"] == "mock"
