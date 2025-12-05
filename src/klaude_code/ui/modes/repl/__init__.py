from __future__ import annotations

from typing import TYPE_CHECKING

from klaude_code.protocol import model
from klaude_code.ui.modes.repl.input_prompt_toolkit import REPLStatusSnapshot

if TYPE_CHECKING:
    from klaude_code.core.agent import Agent


def build_repl_status_snapshot(agent: Agent | None, update_message: str | None) -> REPLStatusSnapshot:
    """Build a status snapshot for the REPL bottom toolbar.

    Aggregates model name, context usage, and basic call counts from the
    provided agent's session history.
    """

    model_name = ""
    context_usage_percent: float | None = None
    llm_calls = 0
    tool_calls = 0

    if agent is not None:
        model_name = agent.profile.llm_client.model_name or ""

        history = agent.session.conversation_history
        for item in history:
            if isinstance(item, model.AssistantMessageItem):
                llm_calls += 1
            elif isinstance(item, model.ToolCallItem):
                tool_calls += 1

        for item in reversed(history):
            if isinstance(item, model.ResponseMetadataItem):
                usage = item.usage
                if usage is not None and hasattr(usage, "context_usage_percent"):
                    context_usage_percent = usage.context_usage_percent
                break

    return REPLStatusSnapshot(
        model_name=model_name,
        context_usage_percent=context_usage_percent,
        llm_calls=llm_calls,
        tool_calls=tool_calls,
        update_message=update_message,
    )
