from typing import Generator

from rich.abc import RichRenderable

from ..agent import AgentState
from ..config import FileConfigSource
from ..message import UserMessage
from ..tui import console, get_all_themes, render_suffix
from ..tui.theme_preview import show_all_theme_previews
from ..user_input import Command, CommandHandleOutput, UserInput, user_select


class ThemeCommand(Command):
    def get_name(self) -> str:
        return 'theme'

    def get_command_desc(self) -> str:
        return 'Switch color theme between {}'.format(', '.join(get_all_themes()))

    async def handle(self, agent_state: 'AgentState', user_input: UserInput) -> CommandHandleOutput:
        command_handle_output = await super().handle(agent_state, user_input)
        command_handle_output.user_msg.removed = True

        # Show all theme previews
        theme_previews = show_all_theme_previews()
        console.print(theme_previews)

        theme_options = get_all_themes()
        selected_idx = await user_select(theme_options, 'Select theme:')

        if selected_idx is not None:
            selected_theme = theme_options[selected_idx]

            config_path = FileConfigSource().get_config_path()

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
