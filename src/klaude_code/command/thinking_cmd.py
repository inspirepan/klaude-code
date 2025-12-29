import asyncio

from prompt_toolkit.styles import Style

from klaude_code.command.command_abc import Agent, CommandABC, CommandResult
from klaude_code.config.thinking import get_thinking_picker_data, parse_thinking_value
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


def _select_thinking_sync(config: llm_param.LLMConfigParameter) -> llm_param.Thinking | None:
    """Select thinking level (sync version)."""
    data = get_thinking_picker_data(config)
    if data is None:
        return None

    items: list[SelectItem[str]] = [
        SelectItem(title=[("class:text", opt.label + "\n")], value=opt.value, search_text=opt.label)
        for opt in data.options
    ]

    try:
        result = select_one(
            message=data.message,
            items=items,
            pointer="→",
            style=SELECT_STYLE,
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
