"""AI tool 调度器（V0.97.0 · 5 个只读 tool）

Tool 协议
---------
Claude tool_use JSON schema 格式：
``[{"name": "...", "description": "...", "input_schema": {...}}, ...]``

执行约束
--------
- **只读** —— 永不暴露 mutation 端点
- **错误降级** —— 单 tool 失败返 ``{"error": "..."}`` dict，不抛异常到 LLM
  （让 model 能告诉用户「数据获取失败」而不是整轮 abort）
- **输出截断** —— 单 tool 结果超过 4000 字符截断（防 context 爆炸）

5 个 tool 映射到现有 services：
- ``get_market_overview`` → ``TrendService.analyze()``（NY 金 + 综合指数）
- ``get_scoring_summary`` → ``ScoringWideService.hit_stats_all_horizons()``
- ``get_user_portfolio`` → ``PositionService.equity_curve() + performance()``
- ``get_warning_summary`` → ``FreshnessService.report()`` 派生
  （取各数据源的 staleness 状态作为「健康警示」）
- ``get_etf_recent_flows`` → ``MarketDataRepository.get_etf_history()``
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from app.utils.market_clock import cn_today

logger = logging.getLogger(__name__)

# 单 tool 结果最大字符数（防 LLM context 撑爆）
_MAX_RESULT_CHARS = 4000

# 系统提示（每个 tool 描述要给 LLM 充分信息以判断何时调用）
SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "get_market_overview",
        "description": (
            "取最近一次 NY 金（COMEX 美元/盎司）/ 上海金（人民币/克）/ 沪金 ETF "
            "（518880 元/份）/ 白银（COMEX 美元/盎司）的收盘价 + 综合趋势指数"
            "（技术 30% + 宏观 40% + 消息面 30% 合成）。回答用户关于「现在金价多少」/"
            "「市场整体怎么走」时必调。"
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_scoring_summary",
        "description": (
            "取指定日期范围（from/to 可选，缺省=近 30 天）的打分汇总，含 4 horizon "
            "(t0/t1/t3/t5) 命中率 + 月度聚合 + 最近 30 天 / MoM / 最佳 horizon 摘要。"
            "回答「近期命中率怎么样」/「哪个月预测最准」时必调。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "from": {
                    "type": "string",
                    "format": "date",
                    "description": "起始日期 YYYY-MM-DD（缺省=今天往前 30 天）",
                },
                "to": {
                    "type": "string",
                    "format": "date",
                    "description": "结束日期 YYYY-MM-DD（缺省=今天）",
                },
            },
        },
    },
    {
        "name": "get_user_portfolio",
        "description": (
            "取当前用户的持仓总览：成本 / 现价 / 浮盈 / 90 日权益曲线 + 业绩概览 "
            "（累计收益率 / 最大回撤 / 夏普）。回答「我的持仓怎样」/「现在盈亏"
            "多少」时必调。"
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_warning_summary",
        "description": (
            "取数据健康警示：哪些数据源过期 / 失效（如 NY 金行情 3 天未更新、宏观"
            "因子缺失等）。回答「现在数据可靠吗」/「为什么今天没数据」时必调。"
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_etf_recent_flows",
        "description": (
            "取最近 N 天（1-90）的沪金 ETF（518880）历史价格 / 成交量走势。"
            "回答「ETF 最近涨了多少」/「最近成交量」时调。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "minimum": 1, "maximum": 90, "description": "回看天数"},
            },
            "required": ["days"],
        },
    },
]


@dataclass
class ToolCall:
    """LLM 一次 tool_use block。"""

    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ToolResult:
    """Tool 执行结果。"""

    tool_call_id: str
    name: str
    content: str  # 已经是 JSON 字符串
    is_error: bool = False


def _truncate(payload: Any) -> str:
    """JSON 序列化 + 截断到 4000 字符（防 LLM context 爆炸）。"""
    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) > _MAX_RESULT_CHARS:
        return text[:_MAX_RESULT_CHARS] + "\n...[truncated; ask user for more detail]..."
    return text


def _err(tool_call_id: str, name: str, msg: str) -> ToolResult:
    """统一错误返回（不抛异常到 LLM，model 能继续对话）。"""
    return ToolResult(
        tool_call_id=tool_call_id,
        name=name,
        content=json.dumps({"error": msg[:200]}, ensure_ascii=False),
        is_error=True,
    )


class ToolDispatcher:
    """5 个只读 tool 的统一调度器。"""

    def __init__(
        self,
        *,
        trend_service: Any,
        scoring_service: Any,
        position_service: Any,
        portfolio_service: Any,
        freshness_service: Any,
        market_data_repository: Any,
    ) -> None:
        self._trend = trend_service
        self._scoring = scoring_service
        self._position = position_service
        # ⚠️ V0.120.3：``equity_curve`` / ``performance`` 在 **PortfolioAnalyticsService**
        # 上，不在 PositionService 上 —— 两者混用会让 get_user_portfolio 线上 100% 报错。
        self._portfolio = portfolio_service
        self._freshness = freshness_service
        self._market = market_data_repository

    def schemas(self) -> list[dict[str, Any]]:
        return SCHEMAS

    async def execute(self, call: ToolCall, *, user_id: int) -> ToolResult:
        """单 tool 执行。永不抛异常（错误走 is_error=True ToolResult）。"""
        try:
            if call.name == "get_market_overview":
                return await self._exec_market(call)
            if call.name == "get_scoring_summary":
                return await self._exec_scoring(call)
            if call.name == "get_user_portfolio":
                return await self._exec_portfolio(call, user_id=user_id)
            if call.name == "get_warning_summary":
                return await self._exec_warnings(call)
            if call.name == "get_etf_recent_flows":
                return await self._exec_etf_flows(call)
            return _err(call.id, call.name, f"unknown tool: {call.name}")
        except Exception as exc:
            logger.warning("tool %s failed: %s", call.name, exc)
            return _err(call.id, call.name, f"{type(exc).__name__}: {str(exc)[:150]}")

    # ────────────── 5 个 tool 实现 ──────────────

    async def _exec_market(self, call: ToolCall) -> ToolResult:
        """get_market_overview: NY 金 + 综合指数。"""
        result = await self._trend.analyze(days=60, target="ny", interval="D")
        idx = result.index
        last_close = result.points[-1].close if result.points else None
        payload = {
            "name": result.name,
            "index_score": idx.score,
            "index_level": idx.level.value if idx and idx.level else None,
            "index_direction": idx.direction.value if idx and idx.direction else None,
            "tech_index": result.macro.score if result.macro else None,  # placeholder
            "macro_index": result.macro.score if result.macro else None,
            "news_index": result.news.score if result.news else None,
            "last_close": last_close,
            "change_pct_2m": result.metrics.change_pct if result.metrics else None,
            "change_pct_1d": result.metrics.change_pct_1d if result.metrics else None,
            "degraded": result.degraded,
            "as_of": result.served_at.isoformat() if result.served_at else None,
        }
        return ToolResult(call.id, call.name, _truncate(payload))

    async def _exec_scoring(self, call: ToolCall) -> ToolResult:
        """get_scoring_summary: 4 horizon 命中 + 30d 摘要。

        ⚠️ **V0.120.3 修的真缺陷**：模型经常**漏掉** from/to ⇒ 原实现直接返
        ``{"error": "from/to required"}`` ⇒ 模型拿到错误就反复重试同一个工具 ⇒
        工具轮次（max_tool_rounds=3）耗尽 ⇒ **最终正文为空**。
        现在缺省取「近 30 天」（与本 tool 的 mini_card「最近 30 天」口径一致），
        并在返回体里报告**实际使用的区间** ⇒ 不产生假数据，模型也能拿到真数字。
        """
        from_str = call.input.get("from")
        to_str = call.input.get("to")
        today = cn_today()
        if not to_str:
            to_str = today.isoformat()
        if not from_str:
            from_str = (today - timedelta(days=30)).isoformat()
        try:
            start = date.fromisoformat(from_str)
            end = date.fromisoformat(to_str)
        except ValueError as exc:
            return _err(call.id, call.name, f"date format: {exc}")
        if start > end:
            return _err(call.id, call.name, "from > to")

        out = await self._scoring.hit_stats_all_horizons(start=start, end=end)
        # Pydantic → dict（json.dumps 不认 Pydantic 模型）
        by_horizon_dict = {
            h_name: {
                "horizon": h_data.horizon,
                "by_month": [
                    {
                        "period": b.period,
                        "days": b.days,
                        "hit_rate": getattr(b, f"hit_rate_{h_data.horizon}", None),
                    }
                    for b in h_data.by_month
                ],
            }
            for h_name, h_data in out.by_horizon.items()
        }
        payload = {
            "from": out.from_date.isoformat(),
            "to": out.to_date.isoformat(),
            "by_horizon": by_horizon_dict,
            "mini_card": {
                "last_30d": out.mini_card.last_30d,
                "last_30d_mom": out.mini_card.last_30d_mom,
                "best_horizon": out.mini_card.best_horizon,
            },
        }
        return ToolResult(call.id, call.name, _truncate(payload))

    async def _exec_portfolio(self, call: ToolCall, *, user_id: int) -> ToolResult:
        """get_user_portfolio: 持仓 + 业绩 + 90 日权益曲线。

        ⚠️ **V0.120.3 修的真缺陷（线上 100% 报错）**：
        原实现调 ``self._position.equity_curve(...)`` / ``self._position.performance(...)``，
        但生产 wiring 注入的是 **PositionService** —— 它**根本没有这两个方法**
        （``PositionService`` 只有 ``summary`` / ``list_positions`` / 持仓生命周期方法；
        ``equity_curve`` / ``performance`` 在 **PortfolioAnalyticsService** 上）。
        ⇒ 结果是 ``{"error": "AttributeError: 'PositionService' object has no attribute
        'equity_curve'"}`` ⇒ 模型拿到错误就反复重试工具 ⇒ 工具轮次耗尽 ⇒
        **最终正文为空**（用户看到的是空白回复，不是格式问题）。

        ⚠ 这正是「桩藏住被替换的调用方」：测试里的 ``_FakePosition`` **自己实现了**
        那两个方法 ⇒ 5 条 tool 测试全绿，线上却是坏的。
        """
        summary = await self._position.summary(account_id=None)
        positions = await self._position.list_positions(account_id=None)
        perf = await self._portfolio.performance(account_id=None)
        equity = await self._portfolio.equity_curve(days=90, account_id=None)
        payload = {
            "position_summary": {
                "has_position": summary.has_position,
                "quantity": summary.quantity,
                "avg_cost": summary.avg_cost,
                "pnl": summary.pnl,
                "pnl_pct": summary.pnl_pct,
                "position_ratio": summary.position_ratio,
                "grams_held": summary.grams_held,
            },
            "positions": [
                {
                    "symbol": p.symbol,
                    "name": p.name,
                    "quantity": p.quantity,
                    "avg_cost": p.avg_cost,
                    "market_price": p.market_price,
                    "market_value": p.market_value,
                    "pnl": p.pnl,
                    "pnl_pct": p.pnl_pct,
                }
                for p in positions
            ],
            "performance": {
                "open_positions": perf.open_positions,
                "closed_positions": perf.closed_positions,
                "total_cost": perf.total_cost,
                "total_invested": perf.total_invested,
                "unrealized_pnl": perf.unrealized_pnl,
                "realized_pnl": perf.realized_pnl,
                "total_pnl": perf.total_pnl,
                "total_return_pct": perf.total_return_pct,
                "win_rate": perf.win_rate,
                "avg_holding_days": perf.avg_holding_days,
                "best_trade_pnl": perf.best_trade_pnl,
                "worst_trade_pnl": perf.worst_trade_pnl,
            },
            "equity_curve": [
                {
                    "date": p.date if isinstance(p.date, str) else p.date.isoformat(),
                    "market_value": p.market_value,
                    "total_pnl": p.total_pnl,
                }
                for p in equity.points[-30:]
            ],
            "equity_summary": {
                "latest_market_value": equity.summary.latest_market_value,
                "latest_return_pct": equity.summary.latest_return_pct,
                "max_drawdown_pct": equity.summary.max_drawdown_pct,
                "total_invested": equity.summary.total_invested,
                "total_pnl": equity.summary.total_pnl,
            },
            "summary_text": perf.summary,
        }
        return ToolResult(call.id, call.name, _truncate(payload))

    async def _exec_warnings(self, call: ToolCall) -> ToolResult:
        """get_warning_summary: 数据健康 stale 状态。

        V0.97.1 修复：原先调 ``self._freshness.snapshot()`` —— 该方法在
        ``FreshnessService`` 上不存在（实际接口是 ``report()``），且字段名
        ``overall_status / last_update / label / stale_minutes`` 也与
        ``FreshnessOut / DataFreshnessOut`` schema 不一致（实际是
        ``markets[*].status / fetched_at / freshness_label / age_minutes``）。
        现直接调 ``report()`` 并按真实字段映射，输出保持 LLM 友好的扁平结构。
        """
        rep = await self._freshness.report()
        payload = {
            "overall_status": "degraded" if rep.degraded else "ok",
            "degraded": rep.degraded,
            "summary": rep.summary,
            "server_time": rep.server_time,
            "markets": {
                name: {
                    "status": mf.status,
                    "label": mf.freshness_label,
                    "last_update": mf.fetched_at or None,
                    "stale_minutes": mf.age_minutes if mf.age_minutes >= 0 else None,
                }
                for name, mf in (rep.markets or {}).items()
            },
        }
        return ToolResult(call.id, call.name, _truncate(payload))

    async def _exec_etf_flows(self, call: ToolCall) -> ToolResult:
        """get_etf_recent_flows: 沪金 ETF 最近 N 天。"""
        days = int(call.input.get("days", 30))
        days = max(1, min(days, 90))
        history = await self._market.get_gold_history(days=days)
        payload = {
            "days": days,
            "bars": [
                {
                    "date": k.date.isoformat() if hasattr(k, "date") else None,
                    "close": k.close,
                    "volume": getattr(k, "volume", 0),
                }
                for k in (history[-30:] if history else [])
            ],
        }
        return ToolResult(call.id, call.name, _truncate(payload))
