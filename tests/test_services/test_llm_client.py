"""LLM client + tool dispatcher 测试（V0.97.0 C2a）

4 例覆盖：
1. test_claude_client_parses_text_response —— 文本响应解析
2. test_claude_client_parses_tool_use_response —— tool_use 响应解析
3. test_claude_client_retries_on_5xx —— 5xx 重试退避（短退避避免测试慢）
4. test_tool_dispatcher_executes_5_tools —— 5 个 tool 都能调起来

⚠ 测试中不调真实 Claude API（成本 + 网络）；用 monkeypatch httpx。
⚠ 重试用 ``_RETRY_BACKOFFS = (0.0,)`` 覆盖原表，跑得快。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm.claude import (
    ClaudeClient,
    ClaudeResponse,
    LLMError,
    LLMRetryable,
)
from app.services.llm.tools import SCHEMAS, ToolCall, ToolDispatcher


# ────────────── 1. 文本响应解析 ──────────────


@pytest.mark.asyncio
async def test_claude_client_parses_text_response() -> None:
    """Claude 文本响应 → ClaudeResponse.text / token / stop_reason。"""
    client = ClaudeClient(api_key="sk-test", model="claude-sonnet-4-5", timeout=5.0)

    fake_payload = {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "content": [
            {"type": "text", "text": "现在 NY 金 2400 美元，综合指数 65（偏多）。"},
            {"type": "text", "text": "建议关注支撑位 2380。"},
        ],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 200, "output_tokens": 80},
    }

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = fake_payload
    fake_resp.raise_for_status = MagicMock()

    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.post = AsyncMock(return_value=fake_resp)

    with patch("app.services.llm.claude.httpx.AsyncClient", return_value=fake_client):
        result = await client.ask(
            system="你是黄金分析助手",
            messages=[{"role": "user", "content": "现在金价多少？"}],
        )

    assert isinstance(result, ClaudeResponse)
    assert "2400" in result.text
    assert "支撑位" in result.text
    assert result.input_tokens == 200
    assert result.output_tokens == 80
    assert result.stop_reason == "end_turn"
    assert result.tool_calls == []


# ────────────── 2. tool_use 响应解析 ──────────────


@pytest.mark.asyncio
async def test_claude_client_parses_tool_use_response() -> None:
    """Claude tool_use 响应 → ClaudeResponse.tool_calls 列表。"""
    client = ClaudeClient(api_key="sk-test", timeout=5.0)

    fake_payload = {
        "id": "msg_02",
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_abc123",
                "name": "get_market_overview",
                "input": {},
            }
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = fake_payload
    fake_resp.raise_for_status = MagicMock()

    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.post = AsyncMock(return_value=fake_resp)

    with patch("app.services.llm.claude.httpx.AsyncClient", return_value=fake_client):
        result = await client.ask(
            system="你可用工具",
            messages=[{"role": "user", "content": "查金价"}],
            tools=SCHEMAS,
        )

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "toolu_abc123"
    assert result.tool_calls[0].name == "get_market_overview"
    assert result.tool_calls[0].input == {}
    assert result.stop_reason == "tool_use"


# ────────────── 3. 5xx 重试退避（覆盖退避表跑得快） ──────────────


@pytest.mark.asyncio
async def test_claude_client_retries_on_5xx() -> None:
    """第 1 次 503 → 第 2 次 200，最终返回成功（用 0 退避表）。"""
    client = ClaudeClient(api_key="sk-test", timeout=5.0)
    # ⚠ 覆盖退避表，跑得快
    client._RETRY_BACKOFFS = (0.0, 0.0)  # 2 次重试，0 秒退避

    call_count = 0

    def make_resp(status, payload=None):
        r = MagicMock()
        r.status_code = status
        if payload is not None:
            r.json.return_value = payload
        r.text = "ok" if status == 200 else "overloaded"
        return r

    success_payload = {
        "content": [{"type": "text", "text": "成功"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }

    async def fake_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return make_resp(503)
        return make_resp(200, success_payload)

    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.post = fake_post

    with patch("app.services.llm.claude.httpx.AsyncClient", return_value=fake_client):
        result = await client.ask(system="sys", messages=[{"role": "user", "content": "x"}])

    assert call_count == 2  # 第 1 次失败 + 第 2 次成功
    assert "成功" in result.text


@pytest.mark.asyncio
async def test_claude_client_4xx_no_retry() -> None:
    """4xx 业务错误不重试，直接抛 LLMError。"""
    client = ClaudeClient(api_key="sk-test", timeout=5.0)

    fake_resp = MagicMock()
    fake_resp.status_code = 400
    fake_resp.text = "bad request: invalid api key"

    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.post = AsyncMock(return_value=fake_resp)

    with patch("app.services.llm.claude.httpx.AsyncClient", return_value=fake_client):
        with pytest.raises(LLMError, match="client error 400"):
            await client.ask(system="sys", messages=[{"role": "user", "content": "x"}])


# ────────────── 4. tool dispatcher: 5 个 tool 都能调 ──────────────


@dataclass
class _FakeTrend:
    async def analyze(self, days: int, target: str, interval: str) -> Any:
        from app.schemas.market import (
            GoldTrendMetrics,
            GoldTrendOut,
            GoldTrendPoint,
            MacroIndexOut,
            NewsIndexOut,
            TrendDirection,
            TrendIndexLevel,
            TrendIndexOut,
        )
        from app.schemas.common import DirectionSignal
        from datetime import date
        return GoldTrendOut(
            symbol="GC",
            name="NY Gold",
            days=60,
            points=[GoldTrendPoint(date=date(2026, 10, 14), close=2400.0, ma5=None, ma20=None, ma40=None)],
            metrics=GoldTrendMetrics(
                start_date=date(2026, 8, 14), end_date=date(2026, 10, 14),
                trading_days=42, start_price=2350.0, end_price=2400.0,
                change_pct=2.13, high=2420.0, low=2320.0, ma20=None, ma40=None,
                change_pct_1d=0.5, change_pct_5d=1.2, direction=TrendDirection.UP,
                unit="美元/盎司", summary="上行",
            ),
            indicators=[],
            index=TrendIndexOut(score=65.0, level=TrendIndexLevel.UP,
                                direction=DirectionSignal.BULLISH, summary="偏多"),
            macro=MacroIndexOut(score=55.0, factors=[],
                                direction=DirectionSignal.NEUTRAL, summary="稳"),
            news=NewsIndexOut(score=50.0, direction=DirectionSignal.NEUTRAL,
                              note="中性", scored=True),
            data_sources={"ny": "live"},
            degraded=False,
            freshness=None,
            interval="D",
            served_at=__import__("datetime").datetime.utcnow(),
        )


@dataclass
class _FakeScoring:
    async def hit_stats_all_horizons(self, start, end) -> Any:
        from app.schemas.scoring_wide import (
            ScoringHitStatsAllHorizon,
            ScoringHitStatsAllMiniCard,
            ScoringHitStatsAllOut,
            ScoringSummaryBucket,
        )
        bucket = ScoringSummaryBucket(period="2026-10", days=14, hit_rate_t0=0.4,
                                      hit_rate_t1=0.407, hit_rate_t3=0.4, hit_rate_t5=0.391)
        return ScoringHitStatsAllOut(
            from_date=start, to_date=end,
            by_horizon={
                h: ScoringHitStatsAllHorizon(horizon=h, by_month=[bucket])
                for h in ("t0", "t1", "t3", "t5")
            },
            mini_card=ScoringHitStatsAllMiniCard(
                last_30d={"t0": 0.357, "t1": 0.407, "t3": 0.4, "t5": 0.391},
                last_30d_mom={"t0": None, "t1": None, "t3": None, "t5": None},
                best_horizon="t1",
            ),
        )


@dataclass
class _FakePosition:
    async def equity_curve(self, days: int, account_id: Any) -> Any:
        from app.schemas.portfolio import EquityCurveOut, EquityPoint, EquitySummary
        return EquityCurveOut(
            days=days,
            points=[EquityPoint(date="2026-10-14", value=120000.0)],
            summary=EquitySummary(),
        )

    async def performance(self, account_id: Any) -> Any:
        from app.schemas.portfolio import PerformanceOut
        return PerformanceOut(
            total_pnl=5000.0, realized_pnl=2000.0, unrealized_pnl=3000.0,
            total_cost=100000.0, total_invested=100000.0, total_return_pct=5.0,
            open_positions=2, closed_positions=1, closed_trades=1,
            win_trades=1, loss_trades=0, win_rate=100.0,
            buy_count=3, sell_count=1, best_trade_pnl=2000.0, worst_trade_pnl=0.0,
            avg_trade_pnl=2000.0, gross_profit=2000.0, gross_loss=0.0,
            profit_factor=None, avg_holding_days=15.0,
            summary="累计收益 5%",
        )


@dataclass
class _FakeFreshness:
    async def snapshot(self) -> Any:
        from app.schemas.market import (
            DataFreshnessOut, FreshnessLevel, FreshnessOut, MarketSessionOut,
        )
        from datetime import datetime
        markets = {
            "ny": DataFreshnessOut(
                market="ny", name="纽约金", status="live",
                freshness=FreshnessLevel.REALTIME, freshness_label="实时",
                data_date="2026-10-14", fetched_at="2026-10-14T10:00:00Z",
                age_minutes=5.0,
                session=MarketSessionOut(
                    market="ny", name="纽约金", state="open", state_label="交易中",
                ), note="",
            ),
        }
        return FreshnessOut(
            server_time="2026-10-14T10:00:00Z",
            markets=markets, degraded=False, summary="全部实时",
        )


@dataclass
class _FakeMarket:
    async def get_gold_history(self, days: int) -> Any:
        from app.repositories.market_data import GoldKline
        from datetime import date
        return [GoldKline(date=date(2026, 10, 14), open=6.5, high=6.6, low=6.4, close=6.55, volume=1000.0)]


@pytest.mark.asyncio
async def test_tool_dispatcher_executes_5_tools() -> None:
    """5 个 tool 都能调起来，返非空 result。"""
    dispatcher = ToolDispatcher(
        trend_service=_FakeTrend(),
        scoring_service=_FakeScoring(),
        position_service=_FakePosition(),
        freshness_service=_FakeFreshness(),
        market_data_repository=_FakeMarket(),
    )

    # 1. get_market_overview
    r1 = await dispatcher.execute(
        ToolCall(id="t1", name="get_market_overview", input={}), user_id=1,
    )
    assert r1.is_error is False
    assert "index_score" in r1.content
    assert r1.tool_call_id == "t1"

    # 2. get_scoring_summary
    r2 = await dispatcher.execute(
        ToolCall(id="t2", name="get_scoring_summary",
                 input={"from": "2026-10-01", "to": "2026-10-14"}),
        user_id=1,
    )
    assert r2.is_error is False
    assert "best_horizon" in r2.content

    # 3. get_user_portfolio
    r3 = await dispatcher.execute(
        ToolCall(id="t3", name="get_user_portfolio", input={}), user_id=1,
    )
    assert r3.is_error is False
    assert "open_positions" in r3.content

    # 4. get_warning_summary
    r4 = await dispatcher.execute(
        ToolCall(id="t4", name="get_warning_summary", input={}), user_id=1,
    )
    assert r4.is_error is False
    assert "markets" in r4.content

    # 5. get_etf_recent_flows
    r5 = await dispatcher.execute(
        ToolCall(id="t5", name="get_etf_recent_flows", input={"days": 30}),
        user_id=1,
    )
    assert r5.is_error is False
    assert "bars" in r5.content


@pytest.mark.asyncio
async def test_tool_dispatcher_unknown_tool_returns_error() -> None:
    """未知 tool 名 → is_error=True，不抛异常。"""
    dispatcher = ToolDispatcher(
        trend_service=_FakeTrend(),
        scoring_service=_FakeScoring(),
        position_service=_FakePosition(),
        freshness_service=_FakeFreshness(),
        market_data_repository=_FakeMarket(),
    )
    r = await dispatcher.execute(
        ToolCall(id="x", name="nonexistent", input={}), user_id=1,
    )
    assert r.is_error is True
    assert "unknown tool" in r.content
