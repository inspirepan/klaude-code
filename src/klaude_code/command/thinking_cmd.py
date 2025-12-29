import asyncio
from typing import cast

from prompt_toolkit.styles import Style

from klaude_code.command.command_abc import Agent, CommandABC, CommandResult
from klaude_code.config.thinking import (
    ANTHROPIC_LEVELS,
    ReasoningEffort,
    get_levels_for_responses,
    is_openrouter_model_with_reasoning_effort,
)
from klaude_code.protocol import commands, events, llm_param, model, op
from klaude_code.ui.terminal.selector import SelectItem, select_one

SELECT_STYLE = Style(
    [
        ("instruction", "ansibrightblack"),
        ("pointer", "ansigreen"),
        ("highlighted", "ansigreen"),
        ("text", "ansibrightblack"),
        ("question", "bold"),
    ]
)


def _select_responses_thinking_sync(model_name: str | None) -> llm_param.Thinking | None:
    """Select thinking level for responses/codex protocol (sync version)."""
    levels = get_levels_for_responses(model_name)
    items: list[SelectItem[str]] = [
        SelectItem(title=[("class:text", level + "\n")], value=level, search_text=level) for level in levels
    ]

    try:
        result = select_one(
            message="Select reasoning effort:",
            items=items,
            pointer="→",
            style=SELECT_STYLE,
            use_search_filter=False,
        )

        if result is None:
            return None
        return llm_param.Thinking(reasoning_effort=cast(ReasoningEffort, result))
    except KeyboardInterrupt:
        return None


def _select_anthropic_thinking_sync() -> llm_param.Thinking | None:
    """Select thinking level for anthropic/openai_compatible protocol (sync version)."""
    items: list[SelectItem[int]] = [
        SelectItem(title=[("class:text", label + "\n")], value=tokens or 0, search_text=label)
        for label, tokens in ANTHROPIC_LEVELS
    ]

    try:
        result = select_one(
            message="Select thinking level:",
            items=items,
            pointer="→",
            style=SELECT_STYLE,
            use_search_filter=False,
        )
        if result is None:
            return None
        if result == 0:
            return llm_param.Thinking(type="disabled", budget_tokens=0)
        return llm_param.Thinking(type="enabled", budget_tokens=result)
    except KeyboardInterrupt:
        return None


async def select_thinking_for_protocol(config: llm_param.LLMConfigParameter) -> llm_param.Thinking | None:
    """Select thinking configuration based on the LLM protocol.

    Returns the selected Thinking config, or None if user cancelled.
    """
    protocol = config.protocol
    model_name = config.model

    if protocol in (llm_param.LLMClientProtocol.RESPONSES, llm_param.LLMClientProtocol.CODEX):
        return await asyncio.to_thread(_select_responses_thinking_sync, model_name)

    if protocol == llm_param.LLMClientProtocol.ANTHROPIC:
        return await asyncio.to_thread(_select_anthropic_thinking_sync)

    if protocol == llm_param.LLMClientProtocol.OPENROUTER:
        if is_openrouter_model_with_reasoning_effort(model_name):
            return await asyncio.to_thread(_select_responses_thinking_sync, model_name)
        return await asyncio.to_thread(_select_anthropic_thinking_sync)

    if protocol == llm_param.LLMClientProtocol.OPENAI:
        return await asyncio.to_thread(_select_anthropic_thinking_sync)

    return None


class ThinkingCommand(CommandABC):
    """Configure model thinking/reasoning level."""

    @property
    def name(self) -> commands.CommandName:
        return commands.CommandName.THINKING

    @property
    def summary(self) -> str:
        return "Configure model thinking/reasoning level"

    @property
    def is_interactive(self) -> bool:
        return True

    async def run(self, agent: Agent, user_input: model.UserInputPayload) -> CommandResult:
        del user_input  # unused
        if agent.profile is None:
            return CommandResult(events=[])

        config = agent.profile.llm_client.get_llm_config()
        new_thinking = await select_thinking_for_protocol(config)

        if new_thinking is None:
            return CommandResult(
                events=[
                    events.DeveloperMessageEvent(
                        session_id=agent.session.id,
                        item=model.DeveloperMessageItem(
                            content="(no change)",
                            command_output=model.CommandOutput(command_name=self.name),
                        ),
                    )
                ]
            )

        return CommandResult(
            operations=[
                op.ChangeThinkingOperation(
                    session_id=agent.session.id,
                    thinking=new_thinking,
                )
            ]
        )
