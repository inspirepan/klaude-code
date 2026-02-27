from __future__ import annotations

from klaude_code.core.tool.context import TodoContext, ToolContext
from klaude_code.protocol import user_interaction


def test_tool_context_can_attach_user_interaction_callback() -> None:
    todo_context = TodoContext(get_todos=lambda: [], set_todos=lambda todos: None)
    context = ToolContext(file_tracker={}, todo_context=todo_context, session_id="s1")

    async def _callback(
        _request_id: str,
        _source: user_interaction.UserInteractionSource,
        _payload: user_interaction.UserInteractionRequestPayload,
        _tool_call_id: str | None,
    ) -> user_interaction.UserInteractionResponse:
        raise RuntimeError("not called")

    replaced = context.with_request_user_interaction(_callback)

    assert context.request_user_interaction is None
    assert replaced.request_user_interaction is _callback
