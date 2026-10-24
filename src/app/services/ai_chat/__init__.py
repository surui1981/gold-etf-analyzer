"""AI chat 服务编排（V0.98 · 4 文件拆分）

历史：V0.97.0 起 1 个文件 428 行；V0.98 拆为 service/prompts/serializers/proxy_fallbacks。
向后兼容：``from app.services.ai_chat import AIChatService`` 仍可工作。
"""

from app.services.ai_chat.prompts import _build_system_prompt, _derive_title, _sanitize_user_text
from app.services.ai_chat.proxy_fallbacks import (
    _has_tool_result_block,
    _inline_tool_results_as_text,
    _is_tool_result_id_mismatch,
)
from app.services.ai_chat.serializers import _to_claude_messages
from app.services.ai_chat.service import AIChatService

__all__ = [
    "AIChatService",
    "_build_system_prompt",
    "_derive_title",
    "_has_tool_result_block",
    "_inline_tool_results_as_text",
    "_is_tool_result_id_mismatch",
    "_sanitize_user_text",
    "_to_claude_messages",
]
