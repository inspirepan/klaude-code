from typing import TYPE_CHECKING, Generator

from rich.abc import RichRenderable

from ..config import GlobalConfigSource
from ..message import UserMessage
from ..tui import console, render_suffix
from ..user_input import Command, CommandHandleOutput, UserInput, user_select

if TYPE_CHECKING:
    from ..agent import Agent


class ThemeCommand(Command):
    def get_name(self) -> str:
        return 'theme'

    def get_command_desc(self) -> str:
        return 'Switch color theme between light and dark'

    async def handle(self, agent: 'Agent', user_input: UserInput) -> CommandHandleOutput:
        command_handle_output = await super().handle(agent, user_input)
        command_handle_output.user_msg.removed = True

        theme_options = ['light', 'dark']
        selected_idx = await user_select(theme_options, 'Select theme:')

        if selected_idx is not None:
            selected_theme = theme_options[selected_idx]

            config_path = GlobalConfigSource().get_config_path()

            config_data = {}
            if config_path.exists():
                import json

                try:
                    with open(config_path, 'r') as f:
                        config_data = json.load(f)
                except (json.JSONDecodeError, FileNotFoundError):
                    pass

            config_data['theme'] = selected_theme

            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, 'w') as f:
                import json

                json.dump(config_data, f, indent=2)

            console.set_theme(selected_theme)
            command_handle_output.user_msg.set_extra_data('theme_changed', selected_theme)

        return command_handle_output

    def render_user_msg_suffix(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        theme_changed = user_msg.get_extra_data('theme_changed')
        if theme_changed:
            yield render_suffix(f'Theme switched to {theme_changed}')
