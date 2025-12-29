import asyncio

from prompt_toolkit.styles import Style

from klaude_code.command.command_abc import Agent, CommandABC, CommandResult
from klaude_code.command.model_select import select_model_interactive
from klaude_code.protocol import commands, events, model, op
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


def _confirm_change_default_model_sync(selected_model: str) -> bool:
    items: list[SelectItem[bool]] = [
        SelectItem(title=[("class:text", "No  (session only)\n")], value=False, search_text="No"),
        SelectItem(
            title=[("class:text", "Yes (save as default main_model in ~/.klaude/klaude-config.yaml)\n")],
            value=True,
            search_text="Yes",
        ),
    ]

    try:
        result = select_one(
            message=f"Save '{selected_model}' as default model?",
            items=items,
            pointer="→",
            style=SELECT_STYLE,
            use_search_filter=False,
        )
    except KeyboardInterrupt:
        return False

    return bool(result)


class ModelCommand(CommandABC):
    """Display or change the model configuration."""

    @property
    def name(self) -> commands.CommandName:
        return commands.CommandName.MODEL

    @property
    def summary(self) -> str:
        return "Select and switch LLM"

    @property
    def is_interactive(self) -> bool:
        return True

    @property
    def support_addition_params(self) -> bool:
        return True

    @property
    def placeholder(self) -> str:
        return "model name"

    async def run(self, agent: Agent, user_input: model.UserInputPayload) -> CommandResult:
        selected_model = await asyncio.to_thread(select_model_interactive, preferred=user_input.text)

        current_model = agent.profile.llm_client.model_name if agent.profile else None
        if selected_model is None or selected_model == current_model:
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
        save_as_default = await asyncio.to_thread(_confirm_change_default_model_sync, selected_model)
        return CommandResult(
            operations=[
                op.ChangeModelOperation(
                    session_id=agent.session.id,
                    model_name=selected_model,
                    save_as_default=save_as_default,
                )
            ]
        )
