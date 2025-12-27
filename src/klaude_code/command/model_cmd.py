import asyncio

import questionary

from klaude_code.command.command_abc import Agent, CommandABC, CommandResult
from klaude_code.config.select_model import select_model_from_config
from klaude_code.protocol import commands, events, model, op

SELECT_STYLE = questionary.Style(
    [
        ("instruction", "ansibrightblack"),
        ("pointer", "ansicyan"),
        ("highlighted", "ansicyan"),
        ("text", "ansibrightblack"),
    ]
)


def _confirm_change_default_model_sync(selected_model: str) -> bool:
    choices: list[questionary.Choice] = [
        questionary.Choice(title="No  (session only)", value=False),
        questionary.Choice(title="Yes (save as default main_model in ~/.klaude/klaude-config.yaml)", value=True),
    ]

    try:
        # Add a blank line between the model selector and this confirmation prompt.
        questionary.print("")
        result = questionary.select(
            message=f"Save '{selected_model}' as default model?",
            choices=choices,
            pointer="→",
            instruction="Use arrow keys to move, Enter to select",
            use_jk_keys=False,
            style=SELECT_STYLE,
        ).ask()
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
        selected_model = await asyncio.to_thread(select_model_from_config, preferred=user_input.text)

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
