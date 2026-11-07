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
def mock_llm_tool_use_with_args():
    """LLM 触发 1 轮 tool_use，**入参非空**（V0.120.2 回归用例）。

    ⚠️ **为什么必须非空**：``AIMessageRepository.insert`` 落库时写的是
    ``json.dumps(tool_input) if tool_input else None`` —— **空 dict ``{}`` 是 falsy
    ⇒ 落库 NULL ⇒ schema 校验不炸 ⇒ 真缺陷被空入参藏住**（见
    ``stub-hides-replaced-caller``）。真实 LLM 传的是非空入参
    （实测 ``get_scoring_summary({"from": ..., "to": ...})``），只有那种情况才会炸。
    """
    fake = MagicMock()
    tool_call = ToolCall(
        id="tc-002",
        name="get_scoring_summary",
        input={"from": "2025-09-01", "to": "2026-03-29"},
    )
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
                text="命中分析已生成。",
                tool_calls=[],
                input_tokens=200,
                output_tokens=60,
                stop_reason="end_turn",
            ),
        ]
    )
    return fake


@pytest.fixture
def mock_llm_never_text():
    """LLM 每一轮都只返 tool_use、**从不给正文**（V0.120.3 安全网用例）。

    ⚠️ 这正是线上「空白回复」的成因：模型拿到工具错误就反复重试同一个工具，
    ``max_tool_rounds`` 耗尽后正文为空 —— 用户只看到空白。
    前 3 次 = 3 轮 tool_use（max_tool_rounds=3），第 4 次 = 安全网的「直接作答」调用。
    """
    fake = MagicMock()
    tool_call = ToolCall(id="tc-loop", name="get_market_overview", input={})
    fake.ask = AsyncMock(
        side_effect=[
            ClaudeResponse(
                text="",
                tool_calls=[tool_call],
                input_tokens=100,
                output_tokens=30,
                stop_reason="tool_use",
            )
        ]
        * 3
        + [
            ClaudeResponse(
                text="综合结论：当前 NY 金 2400 美元，综合指数 65（偏多）。",
                tool_calls=[],
                input_tokens=200,
                output_tokens=60,
                stop_reason="end_turn",
            )
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
async def test_final_answer_safety_net_when_model_never_speaks(
    as_ai_user,
    mock_llm_never_text,
    mock_tool_dispatcher,
    mock_settings,
) -> None:
    """模型全程不给正文 ⇒ 「安全网」补一段结论（V0.120.3）。

    ⚠️ 没有这条，用户看到的是**空白回复**（线上实测：工具连续报错 ⇒ 模型反复
    重试 ⇒ max_tool_rounds 耗尽 ⇒ 正文为空）。
    """
    app.state.llm_client = mock_llm_never_text
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
            responses = r2.json()["responses"]
            # 3 轮 tool_use（assistant+tool 各 3 条）+ 安全网的 1 条 assistant 正文
            assert len(responses) == 7, [x["role"] for x in responses]
            last = responses[-1]
            assert last["role"] == "assistant"
            assert "综合结论" in last["content"]
            # 安全网调用必须**不带工具**（否则模型又去调工具）
            assert mock_llm_never_text.ask.await_args.kwargs["tools"] is None
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


def _parse_sse(text: str) -> list[dict]:
    """把 SSE 响应文本拆成 event payload 列表（``data: {...}`` 行）。"""
    import contextlib
    import json

    events: list[dict] = []
    for chunk in text.split("\n\n"):
        for line in chunk.strip().split("\n"):
            if not line.startswith("data:"):
                continue
            with contextlib.suppress(json.JSONDecodeError):
                events.append(json.loads(line[5:].strip()))
    return events


async def test_stream_usage_is_reported_and_persisted(
    as_ai_user,
    mock_settings,
) -> None:
    """⚠️ **V0.121.2（P0-5）**：流式的 token 用量必须**既上报又落库**。

    契约：
    1. ``message_stop`` 事件里带 ``usage``（客户端就是靠它显示 token 的）
    2. 落库的 assistant 消息带同样的数字（刷新页面后仍在）

    原缺陷：服务端 ``message_stop`` 确实发了 usage，但客户端从不读
    （``case 'message_stop'`` 里没有 ``payload.usage``）⇒ 页面上 token 一栏
    永远不显示。
    """
    from app.services.llm.claude import (
        StreamMessageDelta,
        StreamMessageStart,
        StreamMessageStop,
        StreamTextDelta,
    )

    async def mock_ask_stream(*, system, messages, tools=None, **kwargs):
        yield StreamMessageStart(input_tokens=10, model="claude-test")
        yield StreamTextDelta(index=0, text="你好，")
        yield StreamMessageDelta(stop_reason="end_turn", output_tokens=42)
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

            events = _parse_sse(r2.text)
            stop = [e for e in events if e.get("event") == "message_stop"]
            assert stop, f"missing message_stop: {events}"
            usage = stop[-1].get("usage") or {}
            assert usage.get("input_tokens") == 10, f"input_tokens 没上报: {usage}"
            assert usage.get("output_tokens") == 42, f"output_tokens 没上报: {usage}"

            # 落库：刷新页面后 token 仍在
            r3 = await ac.get(f"/api/v1/ai/conversations/{cid}")
            asst = [m for m in r3.json()["messages"] if m["role"] == "assistant"]
            assert asst, "assistant 消息没落库"
            assert asst[0]["input_tokens"] == 10, asst[0]
            assert asst[0]["output_tokens"] == 42, asst[0]
    finally:
        app.state.llm_client = None
        app.state.tool_dispatcher = None
        app.state.settings = None


async def test_stream_without_usage_events_reports_unknown_not_zero(
    as_ai_user,
    mock_settings,
) -> None:
    """⚠️ **V0.121.2（P0-5）**：上游**没真数** token ⇒ 报「未知（NULL）」，不报 0。

    实测成因（2026-11-07 线上 SSE 抓包）：miniMax 代理**照发** ``message_start``，
    但 ``usage.input_tokens`` 要么**缺失**、要么**报 0** ——
    而请求必带 system prompt + tools + 历史 ⇒ 真实输入 token **不可能为 0**
    ⇒ 代理的 0 其实是「没数」，真相是「未知」。
    写 0 等于谎称「这次用了 0 个 token」——这是 V0.78.0 Step D 的老规矩
    （数据不足 ≠ 中性/零）。

    反向验证：把服务端的 ``... if saw_input_usage else None`` 改回 ``total_in_tok``
    ⇒ 本测试必须变红（拿到 0 而不是 None）。
    """
    from app.services.llm.claude import StreamMessageStart, StreamMessageStop, StreamTextDelta

    async def mock_ask_stream(*, system, messages, tools=None, **kwargs):
        # ⚠️ 复刻线上真实形态：message_start **发了**，但 input_tokens **报 0**
        #   （代理没真数）⇒ 一律当「未知」
        yield StreamMessageStart(input_tokens=0, model="claude-test")
        # ⚠️ 也不发 StreamMessageDelta ⇒ 输出 token 同样未知
        yield StreamTextDelta(index=0, text="你好。")
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

            events = _parse_sse(r2.text)
            stop = [e for e in events if e.get("event") == "message_stop"]
            assert stop, f"missing message_stop: {events}"
            usage = stop[-1].get("usage")
            assert usage is not None, f"message_stop 必须带 usage 字段: {stop[-1]}"
            assert usage.get("input_tokens") is None, f"未知必须是 None 而不是 0: {usage}"
            assert usage.get("output_tokens") is None, f"未知必须是 None 而不是 0: {usage}"

            # 落库同理：未知 ⇒ NULL（不是 0）
            r3 = await ac.get(f"/api/v1/ai/conversations/{cid}")
            asst = [m for m in r3.json()["messages"] if m["role"] == "assistant"]
            assert asst, "assistant 消息没落库"
            assert asst[0]["input_tokens"] is None, f"落库值应是 NULL 而不是 0: {asst[0]}"
            assert asst[0]["output_tokens"] is None, f"落库值应是 NULL 而不是 0: {asst[0]}"
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
    calls = {"n": 0}

    async def counting_ask_stream(*args, **kwargs):
        calls["n"] += 1
        async for ev in mock_ask_stream(*args, **kwargs):
            yield ev

    mock_llm.ask_stream = counting_ask_stream

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
            # ⚠️ V0.120.3：上游已报错时**不该**再调一次「安全网」——
            #   白等一轮（实测 429 配额耗尽时多等 15 秒还是同一个错）。
            assert calls["n"] == 1, f"上游报错后不该再调上游，实际调了 {calls['n']} 次"
    finally:
        app.state.llm_client = None
        app.state.tool_dispatcher = None
        app.state.settings = None


# ────────────── V0.120.2 回归：tool_input 落库是 JSON 字符串 ──────────────


@pytest.mark.asyncio
async def test_tool_input_nonempty_roundtrips_as_dict(
    as_ai_user,
    mock_llm_tool_use_with_args,
    mock_tool_dispatcher,
    mock_settings,
) -> None:
    """V0.120.2 回归：tool_use 入参**非空**时，接口必须把落库的 JSON 字符串解码回 dict。

    缺陷链：``repositories/ai_chat.py`` 存 ``json.dumps(tool_input)``（字符串）
    ⇒ ``AIMessageOut.tool_input`` 声明是 ``dict[str, Any] | None``
    ⇒ ``from_attributes=True`` 把字符串直接喂给 dict 校验 ⇒ ValidationError
    ⇒ **整个对话 500**（前端只见「加载对话失败：Internal Server Error」）。

    契约来源：前端 ``static/ask.js::summarizeInput`` 按 ``input.from`` /
    ``input.days`` 取值 ⇒ 对外必须是**对象**，不是 JSON 字符串。
    """
    app.state.llm_client = mock_llm_tool_use_with_args
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
                json={"content": "帮我看看命中分析"},
            )
            assert r2.status_code == 200, r2.text
            tool_use_msg = next(m for m in r2.json()["responses"] if m.get("tool_name"))
            assert isinstance(tool_use_msg["tool_input"], dict), tool_use_msg["tool_input"]
            assert tool_use_msg["tool_input"] == {"from": "2025-09-01", "to": "2026-03-29"}

            # 用户报的症状：重新打开该对话（GET 详情）⇒ 此前 500
            r3 = await ac.get(f"/api/v1/ai/conversations/{cid}")
            assert r3.status_code == 200, r3.text
            stored = next(m for m in r3.json()["messages"] if m.get("tool_name"))
            assert stored["tool_input"] == {"from": "2025-09-01", "to": "2026-03-29"}
    finally:
        app.state.llm_client = None
        app.state.tool_dispatcher = None
        app.state.settings = None


@pytest.mark.asyncio
async def test_get_conversation_survives_corrupt_tool_input(
    as_ai_user,
    mock_llm_text,
    mock_tool_dispatcher,
    mock_settings,
    db_session,
) -> None:
    """脏数据（tool_input 存的不是合法 JSON）⇒ 该字段置 None，**对话仍能打开**。

    纪律同 ``SnapshotOut.macro_detail``：数据不足 ≠ 中性，**不兜底为 ``{}``**
    （空对象会被前端当成「工具没带参数」来渲染，是另一种假数据）；
    但**一个坏字段不该让整个对话打不开**。
    """
    from app.models.ai_chat import AIMessage

    app.state.llm_client = mock_llm_text
    app.state.tool_dispatcher = mock_tool_dispatcher
    app.state.settings = mock_settings
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            r = await ac.post("/api/v1/ai/conversations", json={})
            cid = r.json()["id"]

            db_session.add(
                AIMessage(
                    id="msg-corrupt-tool-input",
                    conversation_id=cid,
                    user_id=as_ai_user.id,
                    role="assistant",
                    content="",
                    tool_name="get_scoring_summary",
                    tool_input="{not-json",
                )
            )
            await db_session.commit()

            r2 = await ac.get(f"/api/v1/ai/conversations/{cid}")
            assert r2.status_code == 200, r2.text
            corrupt = next(m for m in r2.json()["messages"] if m["id"] == "msg-corrupt-tool-input")
            assert corrupt["tool_input"] is None
    finally:
        app.state.llm_client = None
        app.state.tool_dispatcher = None
        app.state.settings = None


# ────────────── V0.120.3 回归：对话格式可读性 ──────────────

# 哨兵（生产库实测形态，纯 ASCII 12 字符）
_SENTINEL = "]<]minimax[>["
# miniMax 有时在标记中间插零宽字符
_ZW = "​"


@pytest.fixture
def mock_llm_two_turns():
    """LLM：第 1 轮 tool_use → 第 2 轮文本 → 第 3 轮（第 2 次提问）文本。"""
    fake = MagicMock()
    fake.ask = AsyncMock(
        side_effect=[
            ClaudeResponse(
                text="",
                tool_calls=[ToolCall(id="tc-101", name="get_market_overview", input={})],
                input_tokens=100,
                output_tokens=30,
                stop_reason="tool_use",
            ),
            ClaudeResponse(
                text="第一轮答案：2400。",
                tool_calls=[],
                input_tokens=200,
                output_tokens=60,
                stop_reason="end_turn",
            ),
            ClaudeResponse(
                text="第二轮答案。",
                tool_calls=[],
                input_tokens=200,
                output_tokens=60,
                stop_reason="end_turn",
            ),
        ]
    )
    return fake


@pytest.mark.asyncio
async def test_tool_use_turn_is_echoed_back_to_llm(
    as_ai_user,
    mock_llm_tool_use,
    mock_tool_dispatcher,
    mock_settings,
) -> None:
    """⚠️ **V0.120.3 回归**：第 2 轮请求必须带 **assistant 的 tool_use 回合**。

    Anthropic 协议要求 ``assistant(tool_use) → user(tool_result)`` **配对**。
    原实现只回传了 ``user(tool_result)`` ⇒ 上游收到畸形会话
    ⇒ miniMax 退化成把自己的本地 tool-call 协议当正文吐出
    （用户报「对话给出的格式 不方便阅读」）。

    断三件事：
    1. 第 2 轮 messages 里有 assistant 回合，且含 ``tool_use`` 块
    2. 该 tool_use 的 id 与紧邻的 tool_result 的 tool_use_id **一致**
    3. **没有两条连续的 user 消息**（那正是畸形形状）
    """
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
            assert r2.status_code == 200, r2.text

            assert mock_llm_tool_use.ask.call_count == 2, "应该调了 2 轮 LLM"
            round2 = mock_llm_tool_use.ask.call_args_list[1].kwargs["messages"]

            tool_use_ids = [
                b["id"]
                for m in round2
                if m["role"] == "assistant" and isinstance(m.get("content"), list)
                for b in m["content"]
                if isinstance(b, dict) and b.get("type") == "tool_use"
            ]
            assert tool_use_ids == ["tc-001"], f"第 2 轮没回传 assistant 的 tool_use 回合: {round2}"

            result_ids = [
                b["tool_use_id"]
                for m in round2
                if m["role"] == "user" and isinstance(m.get("content"), list)
                for b in m["content"]
                if isinstance(b, dict) and b.get("type") == "tool_result"
            ]
            assert result_ids == ["tc-001"], f"tool_result 的 id 与 tool_use 不配对: {round2}"

            roles = [m["role"] for m in round2]
            assert not any(roles[i] == roles[i + 1] == "user" for i in range(len(roles) - 1)), (
                f"出现连续两条 user 消息（畸形会话）: {roles}"
            )
    finally:
        app.state.llm_client = None
        app.state.tool_dispatcher = None
        app.state.settings = None


@pytest.mark.asyncio
async def test_second_turn_history_carries_tool_data(
    as_ai_user,
    mock_llm_two_turns,
    mock_tool_dispatcher,
    mock_settings,
) -> None:
    """第 2 次提问时，历史里必须带上第 1 轮的**工具数据**。

    ⚠️ 原实现的两个漏洞叠在一起：
    - assistant 的 ``tool_use`` 块**从未重建**
    - tool 消息**整条被跳过**
    ⇒ 模型从第 2 轮起**看不到任何工具返回的数字**（只看到"我调用了工具"这句话）。
    """
    app.state.llm_client = mock_llm_two_turns
    app.state.tool_dispatcher = mock_tool_dispatcher
    app.state.settings = mock_settings
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            r = await ac.post("/api/v1/ai/conversations", json={})
            cid = r.json()["id"]
            await ac.post(
                f"/api/v1/ai/conversations/{cid}/messages",
                json={"content": "现在金价多少？"},
            )
            await ac.post(
                f"/api/v1/ai/conversations/{cid}/messages",
                json={"content": "那昨天呢？"},
            )

            assert mock_llm_two_turns.ask.call_count == 3
            round3 = mock_llm_two_turns.ask.call_args_list[2].kwargs["messages"]

            tool_results = [
                b
                for m in round3
                if isinstance(m.get("content"), list)
                for b in m["content"]
                if isinstance(b, dict) and b.get("type") == "tool_result"
            ]
            assert tool_results, f"历史里没有 tool_result ⇒ 模型看不到工具数据: {round3}"
            assert "2400" in tool_results[0]["content"], "工具数据内容丢了"

            tool_uses = [
                b
                for m in round3
                if m["role"] == "assistant" and isinstance(m.get("content"), list)
                for b in m["content"]
                if isinstance(b, dict) and b.get("type") == "tool_use"
            ]
            assert tool_uses, f"历史里没有 tool_use ⇒ 协议不配对: {round3}"
            assert tool_uses[0]["id"] == tool_results[0]["tool_use_id"], (
                "历史里 tool_use/tool_result 没配对"
            )
    finally:
        app.state.llm_client = None
        app.state.tool_dispatcher = None
        app.state.settings = None


@pytest.mark.asyncio
async def test_protocol_markup_is_cleaned_on_read(
    as_ai_user,
    mock_llm_text,
    mock_tool_dispatcher,
    mock_settings,
    db_session,
) -> None:
    """读对话时 ⇒ assistant 正文里的协议残留被清洗；**tool 消息的 JSON 不受影响**。

    ⚠️ tool 消息正文**本身就是** JSON（含 ``name`` 键）——
    清洗规则里有一条是「整行是 ``{"name": …}`` 就丢」，
    若不加「只清洗 assistant」这道闸，**工具数据会被整段毁掉**。
    """
    from app.models.ai_chat import AIMessage

    polluted = (
        "我先查询今天的黄金行情。"
        + _SENTINEL
        + "<tool_call>\n"
        + _SENTINEL
        + "<tool_call>\n"
        + '{"name":"get_market_data","arguments":{"query":"金价"}}\n'
        + "</tool_call>"
    )
    # 带零宽字符的变体（miniMax 有时这么插）
    polluted_zw = (
        "先看结论。"
        + _SENTINEL.replace("]<]", "]<]" + _ZW).replace("minimax", "minimax" + _ZW)
        + "[>"
        + "<tool_call>\n"
        + '{"name":"x","arguments":{}}'
    )
    tool_payload = '{"name": "NY", "last_close": 2400.0, "index_score": 65}'

    app.state.llm_client = mock_llm_text
    app.state.tool_dispatcher = mock_tool_dispatcher
    app.state.settings = mock_settings
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            r = await ac.post("/api/v1/ai/conversations", json={})
            cid = r.json()["id"]

            db_session.add(
                AIMessage(
                    id="msg-polluted-1",
                    conversation_id=cid,
                    user_id=as_ai_user.id,
                    role="assistant",
                    content=polluted,
                )
            )
            db_session.add(
                AIMessage(
                    id="msg-polluted-2",
                    conversation_id=cid,
                    user_id=as_ai_user.id,
                    role="assistant",
                    content=polluted_zw,
                )
            )
            db_session.add(
                AIMessage(
                    id="msg-tool-payload",
                    conversation_id=cid,
                    user_id=as_ai_user.id,
                    role="tool",
                    content=tool_payload,
                    tool_name="get_market_overview",
                    tool_call_id="tc-001",
                )
            )
            await db_session.commit()

            r2 = await ac.get(f"/api/v1/ai/conversations/{cid}")
            assert r2.status_code == 200, r2.text
            msgs = {m["id"]: m for m in r2.json()["messages"]}

            c1 = msgs["msg-polluted-1"]["content"]
            assert "minimax" not in c1, f"协议残留没清掉: {c1!r}"
            assert "tool_call" not in c1, f"协议标签没清掉: {c1!r}"
            assert "我先查询今天的黄金行情。" in c1, "散文被误删了"

            c2 = msgs["msg-polluted-2"]["content"]
            assert "minimax" not in c2, f"零宽变体没清掉: {c2!r}"

            # ⚠️ tool 消息的 JSON 必须**原样保留**
            assert msgs["msg-tool-payload"]["content"] == tool_payload, "工具数据被清洗器毁掉了"
    finally:
        app.state.llm_client = None
        app.state.tool_dispatcher = None
        app.state.settings = None
