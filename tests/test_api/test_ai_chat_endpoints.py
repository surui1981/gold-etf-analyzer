"""AI 智能分析端点测试（V0.97.0 C2b）

覆盖：
1. /api/v1/ai/health —— 无 LLM client / 有 LLM client 两种情况
2. 鉴权：未登录 → 401
3. POST /conversations 建对话 + GET /conversations 列
4. POST /messages 端到端：mock LLM 返回纯文本
5. POST /messages 端到端：mock LLM 抛 LLMError → 503
6. POST /messages 端到端：mock LLM 触发 tool_use → tool 消息入库
7. V0.80.0 #159：user_id 隔离（其他用户不能访问本用户对话）
8. 422：title 字段缺失（不传时使用默认）

注：测试环境 ``AUTH_ENABLED=false``，所以默认都是 401。鉴权通过的 case
通过 ``app.dependency_overrides[get_current_user]`` 注入 fake user。
"""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_current_user
from app.main import app
from app.repositories.db import async_session_factory
from app.services.llm.claude import ClaudeResponse
from app.services.llm.tools import ToolCall, ToolResult

# ────────────── shared fixtures ──────────────


@pytest.fixture
async def fake_user(db_session):
    """写一个 member 用户到 DB，返回实例（被 dep override 当作当前用户）。"""
    from datetime import datetime

    from app.models.user import ROLE_MEMBER, User

    user = User(
        email="ai-tester@example.com",
        password_hash="unused",
        role=ROLE_MEMBER,
        is_active=True,
        display_name="AI Tester",
        created_at=datetime(2026, 1, 1),
        last_login_at=datetime(2026, 1, 1),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def as_ai_user(fake_user):
    """override get_current_user → fake_user。"""
    app.dependency_overrides[get_current_user] = lambda: fake_user
    try:
        yield fake_user
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def mock_llm_text():
    """LLM 返纯文本（无 tool_use）。"""
    fake = MagicMock()
    fake.ask = AsyncMock(
        return_value=ClaudeResponse(
            text="现在 NY 金 2400 美元，综合指数 65（偏多）。",
            tool_calls=[],
            input_tokens=120,
            output_tokens=48,
            stop_reason="end_turn",
        )
    )
    return fake


@pytest.fixture
def mock_llm_tool_use():
    """LLM 触发 1 轮 tool_use → 续答纯文本。"""
    fake = MagicMock()
    # 第 1 轮：要求 tool_use
    tool_call = ToolCall(id="tc-001", name="get_market_overview", input={})
    # 第 2 轮：纯文本
    fake.ask = AsyncMock(
        side_effect=[
            ClaudeResponse(
                text="",
                tool_calls=[tool_call],
                input_tokens=100,
                output_tokens=30,
                stop_reason="tool_use",
            ),
            ClaudeResponse(
                text="现在 NY 金 2400，综合偏多（65）。",
                tool_calls=[],
                input_tokens=200,
                output_tokens=60,
                stop_reason="end_turn",
            ),
        ]
    )
    return fake


@pytest.fixture
def mock_tool_dispatcher():
    """假 tool dispatcher：get_market_overview 返固定 JSON。"""
    fake = MagicMock()
    fake.schemas = MagicMock(return_value=[])

    async def fake_execute(call: ToolCall, *, user_id: int) -> ToolResult:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content='{"name": "NY", "last_close": 2400.0, "index_score": 65}',
            is_error=False,
        )

    fake.execute = fake_execute
    return fake


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.llm_user_message_max_chars = 8000
    s.llm_max_tool_rounds = 3
    s.llm_api_key = "sk-test"
    s.llm_model = "claude-sonnet-4-5"
    s.llm_per_user_per_minute = 30
    s.llm_daily_token_quota = 100000
    return s


# ────────────── health ──────────────


@pytest.mark.asyncio
async def test_health_returns_disabled_when_no_llm() -> None:
    """无 LLM client → enabled=False（feature flag 关）。"""
    app.state.llm_client = None
    app.state.tool_dispatcher = None
    settings = MagicMock(
        llm_api_key="",
        llm_model="claude-sonnet-4-5",
        llm_per_user_per_minute=30,
        llm_daily_token_quota=100000,
    )
    app.state.settings = settings
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            r = await ac.get("/api/v1/ai/health")
        assert r.status_code == 200
        data = r.json()
        assert data["enabled"] is False
        assert "get_market_overview" in data["tools"]
    finally:
        app.state.llm_client = None
        app.state.tool_dispatcher = None
        app.state.settings = None


@pytest.mark.asyncio
async def test_health_returns_enabled_when_configured() -> None:
    """装上 mock LLM + api_key → enabled=True。"""
    app.state.llm_client = MagicMock()
    app.state.tool_dispatcher = MagicMock()
    app.state.settings = MagicMock(
        llm_api_key="sk-test",
        llm_model="claude-sonnet-4-5",
        llm_per_user_per_minute=30,
        llm_daily_token_quota=100000,
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            r = await ac.get("/api/v1/ai/health")
        assert r.status_code == 200
        data = r.json()
        assert data["enabled"] is True
        assert data["model"] == "claude-sonnet-4-5"
        assert data["per_user_per_minute"] == 30
        assert "get_scoring_summary" in data["tools"]
    finally:
        app.state.llm_client = None
        app.state.tool_dispatcher = None
        app.state.settings = None


# ────────────── 鉴权（401）──────────────


@pytest.mark.asyncio
async def test_create_conversation_requires_auth() -> None:
    """匿名 → 401（require_user）。"""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        r = await ac.post("/api/v1/ai/conversations", json={})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_list_conversations_requires_auth() -> None:
    """匿名 → 401。"""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        r = await ac.get("/api/v1/ai/conversations")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_send_message_requires_auth() -> None:
    """匿名 → 401。"""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        r = await ac.post(
            "/api/v1/ai/conversations/conv-x/messages",
            json={"content": "test"},
        )
    assert r.status_code == 401


# ────────────── 503：未启用 ──────────────


@pytest.mark.asyncio
async def test_create_conversation_returns_503_when_llm_missing(
    as_ai_user,
) -> None:
    """已登录但 LLM 未配置 → 503。"""
    app.state.llm_client = None
    app.state.tool_dispatcher = None
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            r = await ac.post("/api/v1/ai/conversations", json={})
        assert r.status_code == 503
    finally:
        app.state.llm_client = None
        app.state.tool_dispatcher = None


# ────────────── 端到端 ──────────────


@pytest.mark.asyncio
async def test_create_and_list_conversations(
    as_ai_user,
    mock_llm_text,
    mock_tool_dispatcher,
    mock_settings,
) -> None:
    """POST 建对话 → GET 列出来。"""
    app.state.llm_client = mock_llm_text
    app.state.tool_dispatcher = mock_tool_dispatcher
    app.state.settings = mock_settings
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            r = await ac.post("/api/v1/ai/conversations", json={"title": "test"})
            assert r.status_code == 201
            conv = r.json()
            assert conv["title"] == "test"
            assert conv["message_count"] == 0

            r2 = await ac.get("/api/v1/ai/conversations")
            assert r2.status_code == 200
            rows = r2.json()
            assert isinstance(rows, list)
            assert len(rows) == 1
            assert rows[0]["id"] == conv["id"]
    finally:
        app.state.llm_client = None
        app.state.tool_dispatcher = None
        app.state.settings = None


@pytest.mark.asyncio
async def test_send_message_pure_text(
    as_ai_user,
    mock_llm_text,
    mock_tool_dispatcher,
    mock_settings,
) -> None:
    """发 1 条 user → 1 条 assistant（mock 返纯文本）。"""
    app.state.llm_client = mock_llm_text
    app.state.tool_dispatcher = mock_tool_dispatcher
    app.state.settings = mock_settings
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            r = await ac.post("/api/v1/ai/conversations", json={})
            assert r.status_code == 201
            cid = r.json()["id"]

            r2 = await ac.post(
                f"/api/v1/ai/conversations/{cid}/messages",
                json={"content": "今天金价多少？"},
            )
            assert r2.status_code == 200
            data = r2.json()
            assert data["user"]["role"] == "user"
            assert data["user"]["content"] == "今天金价多少？"
            assert len(data["responses"]) == 1
            asst = data["responses"][0]
            assert asst["role"] == "assistant"
            assert "2400" in asst["content"]
            assert asst["input_tokens"] == 120

            # message_count 应 bump 到 2（user + assistant）
            r3 = await ac.get(f"/api/v1/ai/conversations/{cid}")
            assert r3.status_code == 200
            detail = r3.json()
            assert detail["conversation"]["message_count"] == 2
            assert len(detail["messages"]) == 2
    finally:
        app.state.llm_client = None
        app.state.tool_dispatcher = None
        app.state.settings = None


@pytest.mark.asyncio
async def test_send_message_with_tool_use(
    as_ai_user,
    mock_llm_tool_use,
    mock_tool_dispatcher,
    mock_settings,
) -> None:
    """发 1 条 user → assistant tool_use → tool → assistant text。"""
    app.state.llm_client = mock_llm_tool_use
    app.state.tool_dispatcher = mock_tool_dispatcher
    app.state.settings = mock_settings
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            r = await ac.post("/api/v1/ai/conversations", json={})
            cid = r.json()["id"]

            r2 = await ac.post(
                f"/api/v1/ai/conversations/{cid}/messages",
                json={"content": "现在金价多少？"},
            )
            assert r2.status_code == 200
            data = r2.json()
            # 1 user + 1 assistant(tool_use) + 1 tool + 1 assistant(text) = 3 responses
            assert len(data["responses"]) == 3
            assert data["responses"][0]["role"] == "assistant"
            assert data["responses"][0]["tool_name"] == "get_market_overview"
            assert data["responses"][1]["role"] == "tool"
            assert data["responses"][1]["tool_call_id"] == "tc-001"
            assert data["responses"][2]["role"] == "assistant"
            assert "2400" in data["responses"][2]["content"]
    finally:
        app.state.llm_client = None
        app.state.tool_dispatcher = None
        app.state.settings = None


@pytest.mark.asyncio
async def test_send_message_returns_503_on_llm_error(
    as_ai_user,
    mock_settings,
) -> None:
    """mock LLM 抛 LLMError → 503 + user_msg 回滚（不入库）。"""
    from app.services.llm.claude import LLMError

    mock_llm = MagicMock()
    mock_llm.ask = AsyncMock(side_effect=LLMError("400 bad request"))
    mock_tool = MagicMock()
    mock_tool.schemas = MagicMock(return_value=[])

    app.state.llm_client = mock_llm
    app.state.tool_dispatcher = mock_tool
    app.state.settings = mock_settings
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            r = await ac.post("/api/v1/ai/conversations", json={})
            cid = r.json()["id"]

            r2 = await ac.post(
                f"/api/v1/ai/conversations/{cid}/messages",
                json={"content": "test"},
            )
            assert r2.status_code == 503
            assert "模型服务异常" in r2.json()["detail"]

            # user_msg 应被回滚（messages 应空）
            r3 = await ac.get(f"/api/v1/ai/conversations/{cid}")
            assert r3.status_code == 200
            assert r3.json()["messages"] == []
    finally:
        app.state.llm_client = None
        app.state.tool_dispatcher = None
        app.state.settings = None


@pytest.mark.asyncio
async def test_user_isolation_returns_404(
    as_ai_user,
    mock_llm_text,
    mock_tool_dispatcher,
    mock_settings,
) -> None:
    """V0.80.0 #159：其他用户的对话 → 404。"""

    app.state.llm_client = mock_llm_text
    app.state.tool_dispatcher = mock_tool_dispatcher
    app.state.settings = mock_settings
    try:
        # 用 fake_user 创建对话
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            r = await ac.post("/api/v1/ai/conversations", json={})
            assert r.status_code == 201
            other_cid = r.json()["id"]

        # 切换到另一个 fake user
        from datetime import datetime as _dt

        from app.models.user import ROLE_MEMBER, User

        async with async_session_factory() as s:
            other_user = User(
                email="other@example.com",
                password_hash="x",
                role=ROLE_MEMBER,
                is_active=True,
                display_name="Other",
                created_at=_dt(2026, 1, 1),
                last_login_at=_dt(2026, 1, 1),
            )
            s.add(other_user)
            await s.commit()
            await s.refresh(other_user)

        app.dependency_overrides[get_current_user] = lambda: other_user
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                r = await ac.get(f"/api/v1/ai/conversations/{other_cid}")
                assert r.status_code == 404, "V0.80.0 #159 失效：其他用户看到了本用户的对话"

                r2 = await ac.post(
                    f"/api/v1/ai/conversations/{other_cid}/messages",
                    json={"content": "hack"},
                )
                assert r2.status_code == 404
        finally:
            app.dependency_overrides.pop(get_current_user, None)
    finally:
        app.state.llm_client = None
        app.state.tool_dispatcher = None
        app.state.settings = None


@pytest.mark.asyncio
async def test_tool_result_fallback_when_proxy_rejects_id(
    as_ai_user,
    mock_settings,
) -> None:
    """V0.97.0 hotfix：miniMax 代理在第 2 轮拒收 ``tool_result``（报
    "tool result's tool id not found" 2013）时，service 应自动降级为
    纯文本 user 消息重试，不让用户看到 500。

    链路：
    1. mock LLM 第 1 次返 tool_use（id="call-xxx"）
    2. mock LLM 第 2 次抛 LLMError（"tool result...not found"）→ 触发 fallback
    3. mock LLM 第 3 次（fallback, tools=None）返纯文本
    4. user_msg + final assistant_msg 都应入库
    """
    from app.services.llm.claude import ClaudeResponse, LLMError, ToolUseBlock

    call_count = 0

    async def mock_ask(*, system, messages, tools=None, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Round 1: 返 tool_use
            return ClaudeResponse(
                text="",
                tool_calls=[
                    ToolUseBlock(
                        id="call-9e6da495-6800-4cc4-8e08-26c4b0887035",
                        name="get_market_overview",
                        input={},
                    )
                ],
                input_tokens=100,
                output_tokens=20,
                stop_reason="tool_use",
            )
        if call_count == 2:
            # Round 2: 代理拒收 tool_result（模拟 miniMax 2013 错）
            raise LLMError(
                'client error 400: {"type":"error","error":{"type":"invalid_request_error",'
                '"message":"invalid params, tool result\'s tool id(call-9e6da495-...) '
                'not found (2013)"}}'
            )
        # Round 3: fallback 文本重试成功
        return ClaudeResponse(
            text="当前 NY 金 2400 美元，综合指数 65（偏多）。",
            tool_calls=[],
            input_tokens=200,
            output_tokens=50,
            stop_reason="end_turn",
        )

    mock_llm = MagicMock()
    mock_llm.ask = mock_ask

    # tool dispatcher：tool_use 时被调一次
    async def mock_execute(tool_call, user_id):
        return ToolResult(
            tool_call_id=tool_call.id,
            name=tool_call.name,
            content='{"index_score": 65}',
            is_error=False,
        )

    mock_tool = MagicMock()
    mock_tool.schemas = MagicMock(return_value=[])
    mock_tool.execute = mock_execute

    app.state.llm_client = mock_llm
    app.state.tool_dispatcher = mock_tool
    app.state.settings = mock_settings
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            r = await ac.post("/api/v1/ai/conversations", json={})
            cid = r.json()["id"]

            r2 = await ac.post(
                f"/api/v1/ai/conversations/{cid}/messages",
                json={"content": "今天金价？"},
            )
            assert r2.status_code == 200, r2.text
            data = r2.json()
            # 应有 3 条响应：assistant(tool_use) + tool + assistant(text)
            assert len(data["responses"]) == 3
            assert data["responses"][0]["role"] == "assistant"
            assert data["responses"][0]["tool_name"] == "get_market_overview"
            assert data["responses"][1]["role"] == "tool"
            assert data["responses"][2]["role"] == "assistant"
            assert "2400" in data["responses"][2]["content"]
            # mock LLM 调了 3 次（tool_use + 失败 + fallback 文本）
            assert call_count == 3
    finally:
        app.state.llm_client = None
        app.state.tool_dispatcher = None
        app.state.settings = None


async def test_tool_result_fallback_l1_also_2013_falls_to_l3_fresh_only(
    as_ai_user,
    mock_settings,
) -> None:
    """V0.97.1 增强：L1（内联 tool_result 重试）也返回 2013 时，L3 用「只发 user 原问题」兜底。

    链路：
    1. mock LLM 第 1 次返 tool_use
    2. mock LLM 第 2 次抛 2013 → 触发 L1
    3. mock LLM 第 3 次（L1，inlined）再抛 2013 → 触发 L3
    4. mock LLM 第 4 次（L3，fresh-only user_q）返纯文本
    5. user 仍能看到 assistant 的回答（不是 503）
    """
    from app.services.llm.claude import ClaudeResponse, LLMError, ToolUseBlock

    call_count = 0

    async def mock_ask(*, system, messages, tools=None, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ClaudeResponse(
                text="",
                tool_calls=[
                    ToolUseBlock(
                        id="call-L1L3-test-id",
                        name="get_market_overview",
                        input={},
                    )
                ],
                input_tokens=100,
                output_tokens=20,
                stop_reason="tool_use",
            )
        # Round 2 / 3: 一直 2013（miniMax 代理深 bug）
        if call_count in (2, 3):
            raise LLMError(
                'client error 400: {"type":"error","error":{"type":"invalid_request_error",'
                '"message":"invalid params, tool result\'s tool id(call-...) not found (2013)"}}'
            )
        # Round 4: L3 fresh-only user_q 成功
        assert tools is None, "L3 必须 tools=None"
        assert len(messages) == 1, f"L3 只发 user 原问题，got {len(messages)} messages"
        assert messages[0]["role"] == "user"
        return ClaudeResponse(
            text="（无工具数据）基于系统知识，金价近月高位震荡。",
            tool_calls=[],
            input_tokens=50,
            output_tokens=30,
            stop_reason="end_turn",
        )

    mock_llm = MagicMock()
    mock_llm.ask = mock_ask

    async def mock_execute(tool_call, user_id):
        return ToolResult(
            tool_call_id=tool_call.id,
            name=tool_call.name,
            content='{"index_score": 65}',
            is_error=False,
        )

    mock_tool = MagicMock()
    mock_tool.schemas = MagicMock(return_value=[])
    mock_tool.execute = mock_execute

    app.state.llm_client = mock_llm
    app.state.tool_dispatcher = mock_tool
    app.state.settings = mock_settings
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            r = await ac.post("/api/v1/ai/conversations", json={})
            cid = r.json()["id"]
            r2 = await ac.post(
                f"/api/v1/ai/conversations/{cid}/messages",
                json={"content": "今天金价？"},
            )
            assert r2.status_code == 200, r2.text
            data = r2.json()
            # responses 至少 3 条：assistant(tool_use) + tool + assistant(text 兜底)
            assert len(data["responses"]) == 3
            assert data["responses"][0]["role"] == "assistant"
            assert data["responses"][0]["tool_name"] == "get_market_overview"
            assert data["responses"][1]["role"] == "tool"
            assert data["responses"][2]["role"] == "assistant"
            # L3 回答应包含「无工具数据」兜底文案
            assert "无工具数据" in data["responses"][2]["content"]
            # 4 次 LLM 调用：tool_use / round2-2013 / L1-2013 / L3-ok
            assert call_count == 4
    finally:
        app.state.llm_client = None
        app.state.tool_dispatcher = None
        app.state.settings = None


# ────────────── V0.98 C5 SSE 流式测试 ──────────────


async def test_send_message_stream_happy_path(
    as_ai_user,
    mock_settings,
) -> None:
    """V0.98 C5：SSE 流式端点 happy path —— text_delta 流式追加 + message_stop 终态。

    验证：
    1. HTTP 200 + content-type 含 text/event-stream
    2. 收到至少 1 个 text_delta 事件
    3. 最后 1 个事件是 message_stop
    4. user message 已入库
    """
    from app.services.llm.claude import (
        StreamMessageStart,
        StreamMessageStop,
        StreamTextDelta,
    )

    async def mock_ask_stream(*, system, messages, tools=None, **kwargs):
        yield StreamMessageStart(input_tokens=10, model="claude-test")
        yield StreamTextDelta(index=0, text="你好，")
        yield StreamTextDelta(index=0, text="这是流式")
        yield StreamTextDelta(index=0, text="回复。")
        yield StreamMessageStop()

    mock_llm = MagicMock()
    mock_llm.ask_stream = mock_ask_stream

    mock_tool = MagicMock()
    mock_tool.schemas = MagicMock(return_value=[])

    app.state.llm_client = mock_llm
    app.state.tool_dispatcher = mock_tool
    app.state.settings = mock_settings
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            r = await ac.post("/api/v1/ai/conversations", json={})
            cid = r.json()["id"]
            r2 = await ac.post(
                f"/api/v1/ai/conversations/{cid}/messages/stream",
                json={"content": "hi"},
            )
            assert r2.status_code == 200, r2.text
            assert "text/event-stream" in r2.headers.get("content-type", "")

            # 解析 SSE 流：每行 'data: {...}\n\n' 分隔
            events: list[dict] = []
            text = r2.text
            for chunk in text.split("\n\n"):
                chunk = chunk.strip()
                if not chunk:
                    continue
                for line in chunk.split("\n"):
                    if line.startswith("data:"):
                        import json

                        try:
                            payload = json.loads(line[5:].strip())
                            events.append(payload)
                        except json.JSONDecodeError:
                            pass

            # 必有 user_saved → text_delta* → message_stop
            event_types = [e.get("event") for e in events]
            assert "user_saved" in event_types, f"missing user_saved: {event_types}"
            assert "message_stop" in event_types, f"missing message_stop: {event_types}"
            text_deltas = [e for e in events if e.get("event") == "text_delta"]
            assert len(text_deltas) >= 1, f"no text_delta events: {events}"
            # 拼接所有 delta
            full_text = "".join(e.get("delta", "") for e in text_deltas)
            assert "你好" in full_text
            assert "流式" in full_text
    finally:
        app.state.llm_client = None
        app.state.tool_dispatcher = None
        app.state.settings = None


async def test_send_message_stream_error_event_yields_error(
    as_ai_user,
    mock_settings,
) -> None:
    """V0.98 C5：SSE 流式端点遇 LLM StreamError → service 捕获 → yield error 事件。

    验证 LLM 抛 / yield 错误时，前端拿到 ``{"event": "error", ...}`` 终态，
    SSE 仍然 200（不是 5xx），前端可正常显示兜底 UI。
    """
    from app.services.llm.claude import StreamError, StreamMessageStart

    async def mock_ask_stream(*, system, messages, tools=None, **kwargs):
        yield StreamMessageStart(input_tokens=5, model="claude-test")
        yield StreamError(err_type="invalid_request_error", message="upstream 502")

    mock_llm = MagicMock()
    mock_llm.ask_stream = mock_ask_stream

    mock_tool = MagicMock()
    mock_tool.schemas = MagicMock(return_value=[])

    app.state.llm_client = mock_llm
    app.state.tool_dispatcher = mock_tool
    app.state.settings = mock_settings
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            r = await ac.post("/api/v1/ai/conversations", json={})
            cid = r.json()["id"]
            r2 = await ac.post(
                f"/api/v1/ai/conversations/{cid}/messages/stream",
                json={"content": "hi"},
            )
            # 200 OK（SSE 即使内部出错也返 200）
            assert r2.status_code == 200, r2.text

            import json

            events: list[dict] = []
            for chunk in r2.text.split("\n\n"):
                for line in chunk.split("\n"):
                    if line.startswith("data:"):
                        with contextlib.suppress(json.JSONDecodeError):
                            events.append(json.loads(line[5:].strip()))

            event_types = [e.get("event") for e in events]
            assert "user_saved" in event_types
            assert "error" in event_types, f"missing error event: {event_types}"
            # error 事件的 msg 应含 "upstream 502"
            err_ev = next(e for e in events if e.get("event") == "error")
            assert "upstream 502" in err_ev.get("msg", "") or "upstream 502" in err_ev.get(
                "data", ""
            )
    finally:
        app.state.llm_client = None
        app.state.tool_dispatcher = None
        app.state.settings = None
