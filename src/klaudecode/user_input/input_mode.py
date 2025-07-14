from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Generator

from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from rich.abc import RichRenderable
from rich.text import Text

from ..message import UserMessage, register_user_msg_content_func, register_user_msg_renderer, register_user_msg_suffix_renderer
from ..tui import ColorStyle, get_prompt_toolkit_color, get_prompt_toolkit_style, render_message
from ..user_input import Command, CommandHandleOutput, UserInput

if TYPE_CHECKING:
    from ..agent import AgentState


class InputModeCommand(Command, ABC):
    @classmethod
    def is_slash_command(cls) -> bool:
        return False

    @abstractmethod
    def _get_prompt(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def _get_color(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def _get_placeholder(self) -> str:
        raise NotImplementedError

    async def handle(self, agent_state: 'AgentState', user_input: UserInput) -> CommandHandleOutput:
        command_handle_output = await super().handle(agent_state, user_input)
        command_handle_output.need_agent_run = command_handle_output.user_msg.is_valid()
        return command_handle_output

    def get_command_desc(self) -> str:
        return f'Input mode: {self.get_name()}'

    def get_prompt(self):
        if self._get_color():
            return HTML(f'<style fg="{self._get_color()}">{self._get_prompt()} </style>')
        return self._get_prompt() + ' '

    def get_placeholder(self):
        color = self._get_color()
        if color:
            return HTML(f'<style fg="{color}">{self._get_placeholder()} </style>')
        return self._get_placeholder() + ' '

    def binding_key(self) -> str:
        raise NotImplementedError

    def get_style(self):
        style_dict = get_prompt_toolkit_style()
        if self._get_color():
            style_dict[''] = self._get_color()
        return Style.from_dict(style_dict)

    def render_user_msg(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        yield render_message(Text(user_msg.content, self._get_color()), mark=self._get_prompt(), style=self._get_color(), mark_style=self._get_color())


class NormalMode(InputModeCommand):
    def get_name(self) -> str:
        return NORMAL_MODE_NAME

    def _get_prompt(self) -> str:
        return '>'

    def _get_color(self) -> str:
        return get_prompt_toolkit_color(ColorStyle.USER_MESSAGE)

    def _get_placeholder(self) -> str:
        return 'Ask anything... (exit to quit)'

    def get_placeholder(self):
        return HTML(f'<style fg="{get_prompt_toolkit_color(ColorStyle.INPUT_PLACEHOLDER)}">{self._get_placeholder()} </style>')

    def binding_key(self) -> str:
        return ''

    async def handle(self, agent_state: 'AgentState', user_input: UserInput) -> CommandHandleOutput:
        return await super().handle(agent_state, user_input)


NORMAL_MODE_NAME = 'normal'
_INPUT_MODES = {
    NORMAL_MODE_NAME: NormalMode(),
}


def register_input_mode(input_mode: InputModeCommand):
    _INPUT_MODES[input_mode.get_name()] = input_mode
    register_user_msg_renderer(input_mode.get_name(), input_mode.render_user_msg)
    register_user_msg_suffix_renderer(input_mode.get_name(), input_mode.render_user_msg_suffix)
    register_user_msg_content_func(input_mode.get_name(), input_mode.get_content)
