from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Generator, Optional, Tuple

if TYPE_CHECKING:
    from .agent import Agent

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from pydantic import BaseModel
from rich.abc import RichRenderable

from .message import UserMessage, register_user_msg_renderer, register_user_msg_suffix_renderer
from .prompt.reminder import LANGUAGE_REMINDER
from .tui import console, render_message

"""
Command: When users press /, it prompts slash command completion
InputModeCommand: When users press special characters like #, !, etc., they enter special input modes (memory mode, bash mode, etc.)
"""


class UserInput(BaseModel):
    command_name: str = 'normal'  # Input mode or slash command
    cleaned_input: str  # User input without slash command
    raw_input: str


# Command ABC
# ---------------------


class Command(ABC):
    @abstractmethod
    def get_name(self) -> str:
        """
        The name of the command.
        /{name}
        """
        raise NotImplementedError

    @abstractmethod
    def get_command_desc(self) -> str:
        """
        The description of the command.
        /{name} {desc}
        """
        raise NotImplementedError

    async def handle(self, agent: 'Agent', user_input: UserInput) -> Tuple[Optional[UserMessage], bool]:
        """
        Handle slash command.
        Return True to indicate that the agent should run.
        """
        return UserMessage(
            content=user_input.cleaned_input,
            user_msg_type=user_input.command_name,
            user_raw_input=user_input.raw_input,
        ), True

    def render_user_msg(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        yield render_message(user_msg.user_raw_input, mark='>')

    def render_user_msg_suffix(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        return
        yield  # Make sure to return a generator

    @classmethod
    def is_slash_command(cls) -> bool:
        return True


class InputModeCommand(Command, ABC):
    @classmethod
    def is_slash_command(cls) -> bool:
        return False

    @abstractmethod
    def _get_prompt(self) -> str:
        """
        The mark of input line, default is '>'
        """
        raise NotImplementedError

    @abstractmethod
    def _get_color(self) -> str:
        """
        The color of the input.
        """
        raise NotImplementedError

    @abstractmethod
    def get_placeholder(self) -> str:
        """
        The placeholder of the input hint.
        """
        raise NotImplementedError


    def get_next_mode_name(self) -> str:
        """
        The name of the next input mode.
        """
        return NORMAL_MODE_NAME

    async def handle(self, agent: 'Agent', user_input: UserInput) -> Tuple[Optional[UserMessage], bool]:
        return await super().handle(agent, user_input)

    def get_command_desc(self) -> str:
        return f'Input mode: {self.get_name()}'

    def get_prompt(self):
        if self._get_color():
            return HTML(f'<style fg="{self._get_color()}">{self._get_prompt()} </style>')
        return self._get_prompt() + ' '

    def binding_key(self) -> str:
        # ! DO NOT BIND `/` `enter` `backspace`
        raise NotImplementedError

    def get_style(self):
        style_dict = {
            'completion-menu': 'bg:default',
            'completion-menu.border': 'bg:default',
            'completion-menu.completion': 'bg:default fg:#9a9a9a',
            'completion-menu.completion.current': 'bg:#4a4a4a fg:#aaddff',
            'scrollbar.background': 'bg:default',
            'scrollbar.button': 'bg:default',
            'completion-menu.meta.completion': 'bg:default fg:#9a9a9a',
            'completion-menu.meta.completion.current': 'bg:#aaddff fg:#4a4a4a',
        }
        if self._get_color():
            style_dict.update(
                {
                    'placeholder': self._get_color(),
                    '': self._get_color(),
                }
            )
        return Style.from_dict(style_dict)


class NormalMode(InputModeCommand):
    def get_name(self) -> str:
        return NORMAL_MODE_NAME

    def _get_prompt(self) -> str:
        return '>'

    def _get_color(self) -> str:
        return ''

    def get_placeholder(self) -> str:
        return 'type you query... type exit to quit.'

    def get_next_mode_name(self) -> str:
        return NORMAL_MODE_NAME

    def binding_key(self) -> str:
        return ''


# All Command Registry
# ---------------------

NORMAL_MODE_NAME = 'normal'
_INPUT_MODES = {
    NORMAL_MODE_NAME: NormalMode(),
}
_SLASH_COMMANDS = {}


def register_input_mode(input_mode: InputModeCommand):
    _INPUT_MODES[input_mode.get_name()] = input_mode
    register_user_msg_renderer(input_mode.get_name(), input_mode.render_user_msg)
    register_user_msg_suffix_renderer(input_mode.get_name(), input_mode.render_user_msg_suffix)


def register_slash_command(command: Command):
    _SLASH_COMMANDS[command.get_name()] = command
    register_user_msg_renderer(command.get_name(), command.render_user_msg)
    register_user_msg_suffix_renderer(command.get_name(), command.render_user_msg_suffix)


# User Input Handler
# ---------------------


class UserInputHandler:
    def __init__(self, agent: 'Agent'):
        self.agent = agent

    async def handle(self, user_input_text: str) -> bool:
        """
        Handle special mode and command input.
        """

        command_name, cleaned_input = self._parse_command(user_input_text)
        command = _INPUT_MODES.get(command_name, _SLASH_COMMANDS.get(command_name, None))
        if command:
            user_msg, need_agent_run = await command.handle(
                self.agent,
                UserInput(
                    command_name=command_name or self.current_input_mode.get_name(),
                    cleaned_input=cleaned_input,
                    raw_input=user_input_text,
                ),
            )
        else:
            user_msg = UserMessage(
                content=cleaned_input,
                user_msg_type=command_name,
                user_raw_input=user_input_text,
            )
            need_agent_run = True

        if user_msg is not None:
            self._handle_language_reminder(user_msg)
            self.agent.append_message(user_msg, print_msg=False)
            # Render command result
            for item in user_msg.get_suffix_renderable():
                console.print(item)

        return need_agent_run

    def _parse_command(self, text: str) -> Tuple[str, str]:
        """Parse command from input text. Returns tuple of (command_enum, remaining_text)"""
        if not text.strip():
            return '', text

        stripped = text.strip()
        if stripped.startswith('/'):
            # Extract command and remaining text
            parts = stripped[1:].split(None, 1)  # Split into at most 2 parts
            if parts:
                command_part = parts[0]
                remaining_text = parts[1] if len(parts) > 1 else ''
                # Find matching enum
                if command_part in _SLASH_COMMANDS:
                    return _SLASH_COMMANDS[command_part].get_name(), remaining_text
        return '', text

    def _handle_language_reminder(self, user_msg: UserMessage):
        if len(self.agent.session.messages) > 2:
            return
        user_msg.append_post_system_reminder(LANGUAGE_REMINDER)


# Prompt toolkit completer & key bindings
# ----------------------------------------


class CommandCompleter(Completer):
    """Custom command completer"""

    def __init__(self, input_session):
        self.commands: Dict[str, Command] = _SLASH_COMMANDS
        self.input_session = input_session

    def get_completions(self, document, _complete_event):
        # Only provide completion in normal mode
        if self.input_session.current_input_mode.get_name() != NORMAL_MODE_NAME:
            return
        text = document.text
        # Only provide completion when input starts with /
        if not text.startswith('/'):
            return
        # Get command part (content after /)
        command_part = text[1:]
        # If no space, we are still completing command name
        if ' ' not in command_part:
            for command_name, command in self.commands.items():
                if command_name.startswith(command_part):
                    yield Completion(
                        command_name,
                        start_position=-len(command_part),
                        display=f'/{command_name}',
                        display_meta=command.get_command_desc(),
                    )


class InputSession:
    def __init__(self, workdir: str = None):
        self.current_input_mode: InputModeCommand = _INPUT_MODES[NORMAL_MODE_NAME]
        self.workdir = Path(workdir) if workdir else Path.cwd()

        # Create history file path
        history_file = self.workdir / '.klaude' / 'input_history.txt'
        if not history_file.exists():
            history_file.parent.mkdir(parents=True, exist_ok=True)
            history_file.touch()
        self.history = FileHistory(str(history_file))

        # Create command completer
        self.command_completer = CommandCompleter(self)

        # Create key bindings
        self.kb = KeyBindings()
        self._setup_key_bindings()

        # Create session
        self.session = PromptSession(
            message=self._dyn_prompt,
            key_bindings=self.kb,
            history=self.history,
            placeholder=self._dyn_placeholder,
            completer=self.command_completer,
            style=self.current_input_mode.get_style(),
        )
        self.buf = self.session.default_buffer

    def _dyn_prompt(self):
        return self.current_input_mode.get_prompt()

    def _dyn_placeholder(self):
        return self.current_input_mode.get_placeholder()

    def _switch_mode(self, event, mode_name: str):
        self.current_input_mode = _INPUT_MODES[mode_name]
        style = self.current_input_mode.get_style()
        if style:
            event.app.style = style
        else:
            event.app.style = None
        event.app.invalidate()

    def _switch_mode_or_insert(self, event, mode_name: str, char: str):
        """Switch to mode if at line start, otherwise insert character"""
        if self.buf.text == '' and self.buf.cursor_position == 0:
            self._switch_mode(event, mode_name)
            return
        self.buf.insert_text(char)

    def _setup_key_bindings(self):
        # 动态注册输入模式的键绑定
        for mode in _INPUT_MODES.values():
            if mode.binding_key():

                def make_binding(current_mode):
                    @self.kb.add(current_mode.binding_key())
                    def _(event):
                        self._switch_mode_or_insert(event, current_mode.get_name(), current_mode.binding_key())

                    return _

                make_binding(mode)

        @self.kb.add('backspace')
        def _(event):
            if self.buf.text == '' and self.buf.cursor_position == 0:
                self._switch_mode(event, NORMAL_MODE_NAME)
                return
            self.buf.delete_before_cursor()

        @self.kb.add('c-u')
        def _(event):
            """Clear the entire buffer with ctrl+u (Unix standard)"""
            self.buf.text = ''
            self.buf.cursor_position = 0

        @self.kb.add('enter')
        def _(event):
            """
            Check if the current line ends with a backslash.
            - If yes, remove the backslash and insert a newline to continue editing.
            - If no, accept the line via `validate_and_handle()`, which triggers
              PromptToolkit's default accept‑line logic and persists the input
              into `FileHistory`.
            """
            buffer = event.current_buffer
            if buffer.text.endswith('\\'):
                # Remove trailing backslash (do **not** include it in history)
                buffer.delete_before_cursor()
                # Insert a real newline so the user can keep typing
                buffer.insert_text('\n')
            else:
                # Accept the line normally – this calls the buffer's
                # accept_action, which records the entry in FileHistory.
                buffer.validate_and_handle()

    def _switch_to_next_mode(self):
        next_mode_name = self.current_input_mode.get_next_mode_name()
        if next_mode_name not in _INPUT_MODES:
            return
        self.current_input_mode = _INPUT_MODES[next_mode_name]
        # Update session style for next prompt
        style = self.current_input_mode.get_style()
        if hasattr(self.session, 'app') and self.session.app:
            self.session.app.style = style or None

    def prompt(self) -> UserInput:
        input_text = self.session.prompt()
        self._switch_to_next_mode()
        return input_text

    async def prompt_async(self) -> UserInput:
        input_text = await self.session.prompt_async()
        self._switch_to_next_mode()
        return input_text
