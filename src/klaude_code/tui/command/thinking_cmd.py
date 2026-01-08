import asyncio

from klaude_code.config.thinking import get_thinking_picker_data, parse_thinking_value
from klaude_code.protocol import commands, events, llm_param, message, op
from klaude_code.tui.terminal.selector import DEFAULT_PICKER_STYLE, SelectItem, select_one

from .command_abc import Agent, CommandABC, CommandResult


def _select_thinking_sync(config: llm_param.LLMConfigParameter) -> llm_param.Thinking | None:
    """Select thinking level (sync version)."""
    data = get_thinking_picker_data(config)
    if data is None:
        return None

    items: list[SelectItem[str]] = [
        SelectItem(title=[("class:msg", opt.label + "\n")], value=opt.value, search_text=opt.label)
        for opt in data.options
    ]

    try:
        result = select_one(
            message=data.message,
            items=items,
            pointer="→",
            style=DEFAULT_PICKER_STYLE,
            use_search_filter=False,
        )
        if result is None:
            return None
        return parse_thinking_value(result)
    except KeyboardInterrupt:
        return None


async def select_thinking_for_protocol(config: llm_param.LLMConfigParameter) -> llm_param.Thinking | None:
    """Select thinking configuration based on the LLM protocol.

    Returns the selected Thinking config, or None if user cancelled.
    """
    return await asyncio.to_thread(_select_thinking_sync, config)


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

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        del user_input  # unused
        if agent.profile is None:
            return CommandResult(events=[])

        config = agent.profile.llm_client.get_llm_config()
        new_thinking = await select_thinking_for_protocol(config)

        if new_thinking is None:
            return CommandResult(
                events=[
                    events.CommandOutputEvent(
                        session_id=agent.session.id,
                        command_name=self.name,
                        content="(no change)",
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
