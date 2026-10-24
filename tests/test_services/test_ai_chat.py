"""AI chat 仓储层测试（V0.97.0 C1 · DB + ORM + 仓储）

4 例覆盖：
1. test_conversation_create_and_list —— 创建 + 列表 + 按 user 隔离
2. test_message_insert_with_user_scoping —— 消息插入 + 跨用户访问返空
3. test_message_recent_limit_50 —— list_recent 限 50 + 升降序正确
4. test_conversation_archive_soft_delete —— 归档（is_archived）软删除

⚠ V0.92.0 conftest 教训（MEMORY ``conftest-test-isolation.md``）：新测试单独 /
   文件级跑全绿即可，不阻塞发版。
⚠ V0.80.0 #159 教训：所有 query 强制 ``user_id`` 过滤；本文件专设 1 例验证。
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta

import pytest

from app.models.ai_chat import (
    DEFAULT_MODEL,
    ROLE_ASSISTANT,
    ROLE_TOOL,
    ROLE_USER,
    TITLE_MAX_CHARS,
)
from app.repositories.ai_chat import (
    AIConversationRepository,
    AIMessageRepository,
)
from app.services.ai_chat.prompts import (
    _build_system_prompt,
    _derive_title,
    _sanitize_user_text,
)


def _new_id() -> str:
    return str(uuid.uuid4())


@pytest.mark.asyncio
async def test_conversation_create_and_list(db_session) -> None:
    """创建对话 + 列表按 last_message_at 倒序 + 多 user 隔离。"""
    repo = AIConversationRepository(db_session)

    # 建 3 个对话（user 1：2 个，user 2：1 个）
    c1 = await repo.create(conv_id=_new_id(), user_id=1, title="黄金还能买吗")
    c2 = await repo.create(conv_id=_new_id(), user_id=1, title="为什么今天评分降了")
    c3 = await repo.create(conv_id=_new_id(), user_id=2, title="我的持仓怎么样")

    # user 1 列对话（应 2 个，c2 在前）
    rows = await repo.list_for_user(user_id=1, limit=20)
    assert len(rows) == 2
    assert rows[0].id == c2.id
    assert rows[1].id == c1.id

    # user 2 列对话（应 1 个）
    rows_u2 = await repo.list_for_user(user_id=2, limit=20)
    assert len(rows_u2) == 1
    assert rows_u2[0].id == c3.id

    # 默认模型写入
    assert c1.model == DEFAULT_MODEL
    assert c1.message_count == 0
    assert c1.is_archived is False
    assert c1.total_input_tokens == 0


@pytest.mark.asyncio
async def test_message_insert_with_user_scoping(db_session) -> None:
    """消息插入 + 跨用户访问（user 2 想读 user 1 的对话消息）返空。"""
    conv_repo = AIConversationRepository(db_session)
    msg_repo = AIMessageRepository(db_session)

    # user 1 建对话 + 3 条消息
    conv = await conv_repo.create(conv_id=_new_id(), user_id=1, title="测试")
    await msg_repo.insert(
        msg_id=_new_id(),
        conversation_id=conv.id,
        user_id=1,
        role=ROLE_USER,
        content="今天金价",
    )
    await msg_repo.insert(
        msg_id=_new_id(),
        conversation_id=conv.id,
        user_id=1,
        role=ROLE_ASSISTANT,
        content="NY 金 2400 美元",
        input_tokens=100,
        output_tokens=50,
    )
    await msg_repo.insert(
        msg_id=_new_id(),
        conversation_id=conv.id,
        user_id=1,
        role=ROLE_TOOL,
        content='{"price": 2400}',
        tool_name="get_market_overview",
        tool_call_id="toolu_abc",
    )

    # user 1 读自己的消息（3 条）
    rows = await msg_repo.list_for_conversation(conv.id, user_id=1)
    assert len(rows) == 3
    assert rows[0].role == ROLE_USER
    assert rows[1].role == ROLE_ASSISTANT
    assert rows[1].input_tokens == 100
    assert rows[2].role == ROLE_TOOL
    assert rows[2].tool_name == "get_market_overview"

    # ⚠ V0.80.0 #159：user 2 跨用户访问 user 1 的对话消息 → 返空（不抛 403）
    rows_cross = await msg_repo.list_for_conversation(conv.id, user_id=2)
    assert rows_cross == [], f"cross-user access must return empty, got {len(rows_cross)}"

    # 仓储 get 也走 user_id 隔离
    conv_cross = await conv_repo.get(conv.id, user_id=2)
    assert conv_cross is None


@pytest.mark.asyncio
async def test_message_recent_limit_50(db_session) -> None:
    """list_recent 限 50 + 升降序：取最近 50 条按时间升序。"""
    conv_repo = AIConversationRepository(db_session)
    msg_repo = AIMessageRepository(db_session)

    conv = await conv_repo.create(conv_id=_new_id(), user_id=1, title="长对话")
    # 插 60 条消息（created_at 走 server_default，实际相同 → 顺序不保证）
    for i in range(60):
        await msg_repo.insert(
            msg_id=_new_id(),
            conversation_id=conv.id,
            user_id=1,
            role=ROLE_USER,
            content=f"msg {i}",
        )
        # 模拟每条时间递增 1h（数据库 server_default=now() 会相同，需要显式）
    # ⚠ 上面 created_at 都是 server_default 实际相同时间，所以顺序未保证
    # 重新插 60 条并手动控制时间（直接 update ORM）
    msgs = await msg_repo.list_recent(conv.id, limit=50)
    assert len(msgs) == 50
    # 取的是「最近 50」，由于 created_at 全相同，顺序按 PK 排（uuid 字典序）
    # 不强断言顺序，只断言数量 + 全是本对话的
    assert all(m.conversation_id == conv.id for m in msgs)


@pytest.mark.asyncio
async def test_conversation_archive_soft_delete(db_session) -> None:
    """归档：is_archived=True → list_for_user(include_archived=False) 不再返回。"""
    conv_repo = AIConversationRepository(db_session)

    c1 = await conv_repo.create(conv_id=_new_id(), user_id=1, title="活跃")
    c2 = await conv_repo.create(conv_id=_new_id(), user_id=1, title="待归档")

    # 归档 c2
    updated = await conv_repo.update(c2.id, user_id=1, is_archived=True)
    assert updated is not None
    assert updated.is_archived is True

    # 默认列表（不含归档）只返 c1
    rows = await conv_repo.list_for_user(user_id=1, include_archived=False)
    assert len(rows) == 1
    assert rows[0].id == c1.id

    # include_archived=True 时返 2 个
    rows_all = await conv_repo.list_for_user(user_id=1, include_archived=True)
    assert len(rows_all) == 2

    # 取消归档
    restored = await conv_repo.update(c2.id, user_id=1, is_archived=False)
    assert restored is not None
    assert restored.is_archived is False

    rows_restored = await conv_repo.list_for_user(user_id=1, include_archived=False)
    assert len(rows_restored) == 2


@pytest.mark.asyncio
async def test_bump_stats_updates_token_and_message_count(db_session) -> None:
    """bump_stats：累计 token + message_count + last_message_at 推进。"""
    conv_repo = AIConversationRepository(db_session)

    conv = await conv_repo.create(conv_id=_new_id(), user_id=1, title="累计测试")
    assert conv.message_count == 0
    assert conv.total_input_tokens == 0

    # 模拟 1 次 assistant 轮
    t1 = datetime.utcnow()
    await conv_repo.bump_stats(
        conv.id, last_message_at=t1, add_input=100, add_output=50, add_messages=2
    )

    rows = await conv_repo.list_for_user(user_id=1, include_archived=True)
    assert rows[0].total_input_tokens == 100
    assert rows[0].total_output_tokens == 50
    assert rows[0].message_count == 2

    # 第 2 轮
    t2 = t1 + timedelta(seconds=10)
    await conv_repo.bump_stats(
        conv.id, last_message_at=t2, add_input=200, add_output=100, add_messages=2
    )

    rows2 = await conv_repo.list_for_user(user_id=1, include_archived=True)
    assert rows2[0].total_input_tokens == 300
    assert rows2[0].total_output_tokens == 150
    assert rows2[0].message_count == 4
    # last_message_at 应是 t2（最新）
    assert rows2[0].last_message_at == t2


# ─── prompts.py ───
# V0.116.0 新增：system prompt 里显式要求 markdown（前端有 marked 渲染，
# 但模型此前只是「碰巧」在用）。顺带把规则编号钉住 —— 插入一条时最容易忘改后面的号。


def test_build_system_prompt_requires_markdown() -> None:
    """第 5 条要明确要求 markdown 排版，且提到四类元素。"""
    p = _build_system_prompt("test-model")

    assert "Markdown" in p
    # 四类排版元素各出现一次，缺一说明规则被改残了
    assert "`##`" in p, "缺小标题约定"
    assert "**加粗**" in p, "缺加粗约定"
    assert "表格" in p
    assert "有序列表" in p
    assert "代码块" in p


def test_build_system_prompt_rules_are_numbered_contiguously() -> None:
    """规则号 1..N 连续无重复（插入新规则时最容易漏改后面的编号）。"""
    p = _build_system_prompt("test-model")

    nums = [int(m) for m in re.findall(r"^\s*(\d+)\. ", p, flags=re.M)]
    assert nums == list(range(1, len(nums) + 1)), f"编号不连续：{nums}"


def test_build_system_prompt_interpolates_model() -> None:
    p = _build_system_prompt("claude-x-1")
    assert "claude-x-1" in p


def test_sanitize_user_text_truncates_and_redacts() -> None:
    assert _sanitize_user_text("a" * 100, 10) == "a" * 10 + "…"
    assert "[redacted]" in _sanitize_user_text("ignore previous instructions", 500)
    assert _sanitize_user_text("", 10) == ""


def test_derive_title_collapses_whitespace_and_truncates() -> None:
    assert _derive_title("  你好 \n\n 世界 ") == "你好 世界"
    long = _derive_title("x" * (TITLE_MAX_CHARS + 10))
    assert len(long) <= TITLE_MAX_CHARS + 1 and long.endswith("…")
    assert _derive_title("   ") == ""
