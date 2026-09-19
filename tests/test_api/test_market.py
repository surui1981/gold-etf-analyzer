"""行情 API 测试：报价 + 趋势追踪（注入假数据源）。"""

from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from app.dependencies import get_market_data_repository, get_trend_service
from app.repositories.market_data import GoldKline
from app.schemas.common import DirectionSignal
from app.schemas.market import MacroIndexOut
from app.services.trend import TrendService


class FakeMacro:
    """假宏观服务：固定中性分，避免 API 测试依赖网络。"""

    async def evaluate(self) -> MacroIndexOut:
        return MacroIndexOut(
            score=50.0, direction=DirectionSignal.NEUTRAL, factors=[], summary="测试宏观"
        )


class FakeMarketRepo:
    """内存假行情仓储：避免测试依赖网络。"""

    async def get_gold_quote(self, symbol: str = "XAU"):
        return type(
            "Q",
            (),
            {"symbol": symbol, "price_usd": 5.5, "change_pct": 1.2, "updated_at": date.today()},
        )()

    async def get_gold_gram_quote(self, symbol: str = "Au99.99"):  # V0.70.0 P2 #8
        return type(
            "Q",
            (),
            {"symbol": symbol, "price_usd": 990.5, "change_pct": 0.35, "updated_at": date.today()},
        )()

    async def get_gold_history(self, days: int = 60) -> list[GoldKline]:
        base = date(2026, 6, 1)
        return [
            GoldKline(
                date=base + timedelta(days=i),
                open=5.0,
                close=round(5.0 + i * 0.02, 3),
                high=5.1,
                low=4.9,
                volume=1000.0,
            )
            for i in range(days)
        ]

    async def get_gold_gram_history(self, days: int = 60) -> list[GoldKline]:
        """克价序列：涨幅略低于 ETF，用于对照。"""
        base = date(2026, 6, 1)
        return [
            GoldKline(
                date=base + timedelta(days=i),
                open=990.0,
                close=round(990.0 + i * 1.5, 2),
                high=992.0,
                low=988.0,
                volume=0.0,
            )
            for i in range(days)
        ]

    async def get_us_gold_history(self, days: int = 60) -> list[GoldKline]:
        """纽约金序列（美元/盎司）。"""
        base = date(2026, 6, 1)
        return [
            GoldKline(
                date=base + timedelta(days=i),
                open=4400.0,
                close=round(4400.0 + i * 3.0, 2),
                high=4410.0,
                low=4390.0,
                volume=0.0,
            )
            for i in range(days)
        ]

    # V0.71.0：白银 5 方法（最小 fake 实现，给 silver 端点测试复用）

    async def get_silver_etf_quote(self, symbol: str = "562800"):
        return type(
            "Q",
            (),
            {"symbol": symbol, "price_usd": 2.45, "change_pct": 1.2, "updated_at": date.today()},
        )()

    async def get_silver_ny_quote(self, symbol: str = "SI"):
        return type(
            "Q",
            (),
            {"symbol": symbol, "price_usd": 31.5, "change_pct": 0.8, "updated_at": date.today()},
        )()

    async def get_silver_etf_history(self, days: int = 60) -> list[GoldKline]:
        base = date(2026, 6, 1)
        return [
            GoldKline(
                date=base + timedelta(days=i),
                open=2.4,
                close=round(2.4 + i * 0.01, 3),
                high=2.5,
                low=2.3,
                volume=0.0,
            )
            for i in range(days)
        ]

    async def get_silver_ny_history(self, days: int = 60) -> list[GoldKline]:
        base = date(2026, 6, 1)
        return [
            GoldKline(
                date=base + timedelta(days=i),
                open=31.0,
                close=round(31.0 + i * 0.05, 3),
                high=32.0,
                low=30.0,
                volume=0.0,
            )
            for i in range(days)
        ]

    async def get_silver_gram_quote(self):
        """V0.71.0 白银克价占位：返回 None（接口已上线，数据源留 V0.72+）。"""
        return None


@pytest.fixture(autouse=True)
def _override_market_repo():
    """所有行情用例注入假数据源（行情 + 宏观）。"""
    from app.main import app

    app.dependency_overrides[get_market_data_repository] = lambda: FakeMarketRepo()
    app.dependency_overrides[get_trend_service] = lambda: TrendService(
        FakeMarketRepo(), macro=FakeMacro()
    )
    yield
    app.dependency_overrides.clear()


async def test_gold_quote(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/market/gold")
    assert resp.status_code == 200
    body = resp.json()
    assert body["price_usd"] > 0
    assert "updated_at" in body


async def test_gold_gram_quote(client: AsyncClient) -> None:
    """V0.70.0 P2 #8：Au99.99 克价（元/克）。"""
    resp = await client.get("/api/v1/market/gold/gram-quote")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "Au99.99"
    assert body["price_usd"] == pytest.approx(990.5, abs=0.01)
    assert "updated_at" in body


async def test_gold_trend(client: AsyncClient) -> None:
    """默认指引基准为纽约金（COMEX GC，美元/盎司）。"""
    resp = await client.get("/api/v1/market/gold/trend?days=60")
    assert resp.status_code == 200
    body = resp.json()

    assert body["symbol"] == "GC"
    assert "纽约金" in body["name"]
    assert len(body["points"]) == 60
    assert body["metrics"]["trading_days"] == 60
    assert body["metrics"]["direction"] in {"up", "down", "sideways"}
    # 上升序列 → change_pct > 0
    assert body["metrics"]["change_pct"] > 0
    assert body["metrics"]["ma20"] is not None
    # 计价单位随指引标的切换
    assert body["metrics"]["unit"] == "美元/盎司"
    assert body["metrics"]["end_price"] > 4000
    # 趋势参数与追踪指数
    assert len(body["indicators"]) == 5
    assert 0 <= body["index"]["score"] <= 100
    assert body["index"]["level"] in {"strong_up", "up", "sideways", "down", "strong_down"}
    # 宏观参考指数
    assert body["macro"]["score"] == 50.0
    assert "宏观" in body["index"]["summary"]
    # 数据时效（UX 6.1）：时效等级 + 交易时段 + 数据截止日
    fresh = body["freshness"]
    assert fresh["market"] == "ny"
    assert fresh["freshness"] in {
        "realtime",
        "delayed",
        "t1",
        "lagged",
        "cached",
        "mock",
        "unknown",
    }
    assert fresh["freshness_label"]
    assert fresh["data_date"]
    assert fresh["session"]["state"] in {"open", "pre", "break", "closed"}
    assert fresh["session"]["windows"]


async def test_gold_trend_etf_target(client: AsyncClient) -> None:
    """显式指定 target=etf 仍返回黄金ETF（518880，元）。"""
    resp = await client.get("/api/v1/market/gold/trend?days=60&target=etf")
    assert resp.status_code == 200
    body = resp.json()

    assert body["symbol"] == "518880"
    assert body["metrics"]["unit"] == "元"
    assert len(body["points"]) == 60
    assert body["metrics"]["trading_days"] == 60


async def test_gold_trend_days_validation(client: AsyncClient) -> None:
    """days 超出范围应 422。"""
    resp = await client.get("/api/v1/market/gold/trend?days=10")
    assert resp.status_code == 422


async def test_gold_compare(client: AsyncClient) -> None:
    """ETF vs 克价对照。"""
    resp = await client.get("/api/v1/market/gold/compare?days=60")
    assert resp.status_code == 200
    body = resp.json()

    assert body["days"] == 60
    assert body["etf"]["change_pct"] > 0  # 上升序列
    assert body["gram"]["change_pct"] > 0
    assert body["leader"] in {"etf", "gram", "tie"}
    assert len(body["points"]) == 60
    assert body["points"][0]["etf"] == 100.0
    assert body["points"][0]["gram"] == 100.0
    assert "对照" in body["summary"]


async def test_ny_gold_trend(client: AsyncClient) -> None:
    """纽约金 60 天趋势曲线。"""
    resp = await client.get("/api/v1/market/gold/ny-trend?days=60")
    assert resp.status_code == 200
    body = resp.json()

    assert body["symbol"] == "GC"
    assert "纽约金" in body["name"]
    assert len(body["points"]) == 60
    assert body["metrics"]["change_pct"] > 0
    assert body["metrics"]["end_price"] > 4000  # 美元/盎司量级


# ───────────────────── V0.64.0 多时间框架 API 测试 ─────────────────────


async def test_v064_gold_trend_interval_w_aggregates_to_weekly(client: AsyncClient) -> None:
    """V0.64.0：interval=W 后端拉 365 天 → 聚合到 ~52 根周 K。"""
    resp = await client.get("/api/v1/market/gold/trend?days=365&interval=W")
    assert resp.status_code == 200
    body = resp.json()

    assert body["interval"] == "W"
    # 365 天 ≈ 52 个 ISO 周（精度 ±2 兼容边界）；points 数 == trading_days
    assert 49 <= len(body["points"]) <= 53
    assert body["metrics"]["trading_days"] == len(body["points"])
    # W 模式下 indicators 旁路（空列表），但综合指数仍输出
    assert body["indicators"] == []
    assert "tech" in body["index"]["components"]
    # 摘要反映「近 1 年」窗口
    assert "近 1 年" in body["metrics"]["summary"]


async def test_v064_gold_trend_interval_m_aggregates_to_monthly(client: AsyncClient) -> None:
    """V0.64.0：interval=M 后端拉 730 天 → 聚合到 ~24 根月 K。"""
    resp = await client.get("/api/v1/market/gold/trend?days=730&interval=M")
    assert resp.status_code == 200
    body = resp.json()

    assert body["interval"] == "M"
    # 730 天 ≈ 24 个月（精度 ±2）
    assert 22 <= len(body["points"]) <= 26
    assert body["metrics"]["trading_days"] == len(body["points"])
    # M 模式 indicators 旁路；MA 在聚合后序列上重算
    assert body["indicators"] == []
    last = body["points"][-1]
    assert last["ma5"] is not None
    assert last["ma20"] is not None
    assert last["ma40"] is None  # 24 月数据不够 MA40 窗口
    # 摘要反映「近 2 年」窗口
    assert "近 2 年" in body["metrics"]["summary"]


async def test_v064_gold_trend_interval_invalid_returns_422(client: AsyncClient) -> None:
    """V0.64.0：非法 interval 触发 FastAPI 422（Query 正则 ^[DWM]$ 拦截）。"""
    resp = await client.get("/api/v1/market/gold/trend?days=60&interval=X")
    assert resp.status_code == 422


async def test_v064_gold_trend_days_upper_limit_750(client: AsyncClient) -> None:
    """V0.64.0：days 上限提升至 750（旧 250 → 新 750 支持 24M 月 K 聚合）。"""
    resp = await client.get("/api/v1/market/gold/trend?days=750&interval=M")
    assert resp.status_code == 200  # 750 在新上限内
    resp_over = await client.get("/api/v1/market/gold/trend?days=900")
    assert resp_over.status_code == 422  # 超出新上限 750


# ───────────────────── V0.71.0：白银端点测试 ─────────────────────


async def test_silver_quote_returns_200(client: AsyncClient) -> None:
    """GET /market/silver/quote：纽约白银 SI（美元/盎司）。"""
    resp = await client.get("/api/v1/market/silver/quote")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "SI"
    assert body["price_usd"] == pytest.approx(31.5, abs=0.01)
    assert "updated_at" in body


async def test_silver_etf_quote_returns_200(client: AsyncClient) -> None:
    """GET /market/silver/etf-quote：白银 ETF 562800（元/份）。"""
    resp = await client.get("/api/v1/market/silver/etf-quote")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "562800"
    assert body["price"] == pytest.approx(2.45, abs=0.01)
    assert body["currency"] == "CNY"
    assert body["unit"] == "元/份"


async def test_silver_trend_returns_silver_trend_out(client: AsyncClient) -> None:
    """GET /market/silver/trend：白银 ETF 趋势追踪（SilverTrendOut）。"""
    resp = await client.get("/api/v1/market/silver/trend?days=60")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "562800"
    assert "白银ETF" in body["name"]
    assert len(body["points"]) == 60
    assert body["metrics"]["unit"] == "元"
    # 综合指数字段存在
    assert 0 <= body["index"]["score"] <= 100
    assert body["index"]["level"] in {"strong_up", "up", "sideways", "down", "strong_down"}


async def test_silver_ny_trend_returns_silver_trend_out(client: AsyncClient) -> None:
    """GET /market/silver/ny-trend：纽约白银趋势（SilverTrendOut）。"""
    resp = await client.get("/api/v1/market/silver/ny-trend?days=60")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "SI"
    assert "纽约白银" in body["name"]
    assert body["metrics"]["unit"] == "美元/盎司"


async def test_silver_compare_returns_silver_compare_out(client: AsyncClient) -> None:
    """GET /market/silver/compare：白银 ETF vs 纽约白银对照（SilverCompareOut）。"""
    resp = await client.get("/api/v1/market/silver/compare?days=60")
    assert resp.status_code == 200
    body = resp.json()
    assert body["days"] >= 2
    assert body["silver_etf"]["symbol"] == "562800"
    assert body["silver_ny"]["symbol"] == "SI"
    assert body["leader"] in {"silver_etf", "silver_ny", "tie"}
    assert "领先" in body["summary"] or "持平" in body["summary"]
    assert len(body["points"]) >= 2
    # 每个点 silver_etf / silver_ny 都是归一化值
    for p in body["points"]:
        assert p["silver_etf"] > 0
        assert p["silver_ny"] > 0
