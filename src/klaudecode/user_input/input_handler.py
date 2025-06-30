from typing import TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from ..agent import Agent

from ..message import UserMessage
from ..prompt.reminder import LANGUAGE_REMINDER
from ..tui import console
from .input_command import _SLASH_COMMANDS, UserInput
from .input_mode import _INPUT_MODES, NORMAL_MODE_NAME, NormalMode


class UserInputHandler:
    def __init__(self, agent: 'Agent'):
        self.agent = agent

    async def handle(self, user_input_text: str, print_msg: bool = True) -> bool:
        command_name, cleaned_input = self._parse_command(user_input_text)
        command = _INPUT_MODES.get(command_name, _SLASH_COMMANDS.get(command_name, NormalMode()))
        command_handle_output = await command.handle(
            self.agent,
            UserInput(
                command_name=command_name or NORMAL_MODE_NAME,
                cleaned_input=cleaned_input,
                raw_input=user_input_text,
            ),
        )
        user_msg = command_handle_output.user_msg

        if user_msg is not None:
            self._handle_language_reminder(user_msg)
            self.agent.session.append_message(user_msg)
            if print_msg:
                console.print(user_msg)
            elif command_handle_output.need_render_suffix:
                for item in user_msg.get_suffix_renderable():
                    console.print(item)

        return command_handle_output.need_agent_run

    def _parse_command(self, text: str) -> Tuple[str, str]:
        if not text.strip():
            return '', text

        stripped = text.strip()
        if stripped.startswith('/'):
            parts = stripped[1:].split(None, 1)
            if parts:
                command_part = parts[0]
                remaining_text = parts[1] if len(parts) > 1 else ''
                if command_part in _SLASH_COMMANDS:
                    return command_part, remaining_text
                if command_part in _INPUT_MODES:
                    return command_part, remaining_text
        return '', text

    def _handle_language_reminder(self, user_msg: UserMessage):
        if len(self.agent.session.messages) > 2:
            return
        user_msg.append_post_system_reminder(LANGUAGE_REMINDER)
