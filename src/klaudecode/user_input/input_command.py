from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Generator, Optional

from pydantic import BaseModel
from rich.abc import RichRenderable
from rich.text import Text

from ..message import UserMessage, register_user_msg_content_func, register_user_msg_renderer, register_user_msg_suffix_renderer
from ..tui import ColorStyle, render_message

if TYPE_CHECKING:
    from ..agent import AgentState


class UserInput(BaseModel):
    command_name: str = 'normal'
    cleaned_input: str
    raw_input: str


class CommandHandleOutput(BaseModel):
    user_msg: Optional[UserMessage] = None
    need_agent_run: bool = False
    need_render_suffix: bool = True


class Command(ABC):
    @abstractmethod
    def get_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_command_desc(self) -> str:
        raise NotImplementedError

    async def handle(self, agent_state: 'AgentState', user_input: UserInput) -> CommandHandleOutput:
        return CommandHandleOutput(
            user_msg=UserMessage(
                content=user_input.cleaned_input,
                user_msg_type=user_input.command_name,
                user_raw_input=user_input.raw_input,
            ),
            need_agent_run=False,
            need_render_suffix=True,
        )

    def render_user_msg(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        yield render_message(Text(user_msg.user_raw_input, style=ColorStyle.USER_MESSAGE), mark='>')

    def render_user_msg_suffix(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        return
        yield

    def get_content(self, user_msg: UserMessage) -> str:
        return user_msg.content

    @classmethod
    def is_slash_command(cls) -> bool:
        return True


_SLASH_COMMANDS = {}


def register_slash_command(command: Command):
    _SLASH_COMMANDS[command.get_name()] = command
    register_user_msg_renderer(command.get_name(), command.render_user_msg)
    register_user_msg_suffix_renderer(command.get_name(), command.render_user_msg_suffix)
    register_user_msg_content_func(command.get_name(), command.get_content)
