from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Dict, Generator, Optional, Tuple, Type

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from pydantic import BaseModel
from rich.abc import RichRenderable

from .message import UserMessage, register_user_msg_renderer, register_user_msg_suffix_renderer
from .tui import console, render_suffix, render_message
from .config import ConfigModel


class InputModeEnum(Enum):
    NORMAL = 'normal'
    PLAN = 'plan'
    BASH = 'bash'
    MEMORY = 'memory'


# class CommandEnum(Enum):
# COMPACT = 'compact'
# INIT = 'init'
# COST = 'cost'
# CLEAR = 'clear'
# STATUS = 'status'
# CONTINUE = 'continue'


class UserInput(BaseModel):
    user_msg_type: str = 'normal'
    cleaned_input: str  # User input without slash and command
    raw_input: str  # User input with mode and command


# AVAILABLE_COMMANDS = [cmd.value for cmd in CommandEnum]


class Command(ABC):
    @abstractmethod
    def get_command_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_command_desc(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def handle(self, agent, user_input: UserInput) -> Tuple[UserMessage, bool]:
        raise NotImplementedError

    def render_user_msg(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        yield render_message(user_msg.user_raw_input)

    def render_user_msg_suffix(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        yield ''


# Detailed descriptions for each command
# COMMAND_DESCRIPTIONS = {
#     CommandEnum.COMPACT.value: 'Clear conversation history but keep a summary in context. Optional: /compact [instructions for summarization]',
#     CommandEnum.INIT.value: 'Initialize a new CLAUDE.md file with codebase documentation',
#     CommandEnum.COST.value: 'Show the total cost and duration of the current session',
#     CommandEnum.CLEAR.value: 'Clear conversation history and free up context',
#     CommandEnum.STATUS.value: 'Show the current setup',
#     CommandEnum.CONTINUE.value: 'Request LLM without a new user message. WARNING: This may cause an error for a new conversation',
# }


# Commands
# --------------------------------------


class StatusCommand(Command):
    def get_command_name(self) -> str:
        return 'status'

    def get_command_desc(self) -> str:
        return 'Show the current setup'

    def handle(self, agent, user_input: UserInput) -> Tuple[UserMessage, bool]:
        user_msg = UserMessage(
            content=user_input.cleaned_input,
            user_msg_type=user_input.user_msg_type,
            user_raw_input=user_input.raw_input,
        )
        user_msg.set_extra_data('status', agent.config.model_dump_json())
        return user_msg, False

    def render_user_msg_suffix(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        config = user_msg.get_extra_data('status')
        if config:
            config_model = ConfigModel.model_validate_json(config)
            print(config_model)
            yield render_suffix(config_model)


ALL_COMMANDS = [StatusCommand()]
ALL_COMMANDS_DICT = {cmd.get_command_name(): cmd for cmd in ALL_COMMANDS}

for cmd in ALL_COMMANDS:
    register_user_msg_renderer(cmd.get_command_name(), cmd.render_user_msg)
    register_user_msg_suffix_renderer(cmd.get_command_name(), cmd.render_user_msg_suffix)


# INPUT_PROMPT
# -------


class InputMode(BaseModel):
    name: InputModeEnum
    prompt: str
    placeholder: str
    style: str
    next_mode: InputModeEnum

    def get_prompt(self):
        if self.style:
            return HTML(f'<style fg="{self.style}">{self.prompt} </style>')
        return self.prompt + ' '

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

        if self.style:
            style_dict.update(
                {
                    'placeholder': self.style,
                    '': self.style,
                }
            )

        return Style.from_dict(style_dict)


input_mode_dict = {
    InputModeEnum.NORMAL: InputMode(
        name=InputModeEnum.NORMAL,
        prompt='>',
        placeholder='type you query... type exit to quit.',
        style='',
        next_mode=InputModeEnum.NORMAL,
    ),
    InputModeEnum.PLAN: InputMode(
        name=InputModeEnum.PLAN,
        prompt='*',
        placeholder='type plan...',
        style='#6aa4a5',
        next_mode=InputModeEnum.PLAN,
    ),
    InputModeEnum.BASH: InputMode(
        name=InputModeEnum.BASH,
        prompt='!',
        placeholder='type command...',
        style='#ea3386',
        next_mode=InputModeEnum.NORMAL,
    ),
    InputModeEnum.MEMORY: InputMode(
        name=InputModeEnum.MEMORY,
        prompt='#',
        placeholder='type memory...',
        style='#b3b9f4',
        next_mode=InputModeEnum.NORMAL,
    ),
}


class CommandCompleter(Completer):
    """Custom command completer"""

    def __init__(self, input_session):
        self.commands = ALL_COMMANDS_DICT
        self.input_session = input_session

    def get_completions(self, document, _complete_event):
        # Only provide completion in normal mode
        if self.input_session.current_input_mode.name != InputModeEnum.NORMAL:
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
        self.current_input_mode = input_mode_dict[InputModeEnum.NORMAL]
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

        # Create sessio
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
        return self.current_input_mode.placeholder

    def _parse_command(self, text: str) -> Tuple[str, str]:
        """Parse command from input text. Returns tuple of (command_enum, remaining_text)"""
        if not text.strip():
            return '', text

        # Only parse commands in normal mode
        if self.current_input_mode.name != InputModeEnum.NORMAL:
            return '', text

        stripped = text.strip()
        if stripped.startswith('/'):
            # Extract command and remaining text
            parts = stripped[1:].split(None, 1)  # Split into at most 2 parts
            if parts:
                command_part = parts[0]
                remaining_text = parts[1] if len(parts) > 1 else ''
                # Find matching enum
                if command_part in ALL_COMMANDS_DICT:
                    return ALL_COMMANDS_DICT[command_part].get_command_name(), remaining_text
        return '', text

    def _switch_mode(self, event, mode_name: str):
        self.current_input_mode = input_mode_dict[mode_name]
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
        @self.kb.add('!')
        def _(event):
            """
            Press '!' at line start: switch to bash mode; don't write to buffer.
            If cursor is not at line start or buffer is not empty, insert '!' normally
            """
            self._switch_mode_or_insert(event, InputModeEnum.BASH, '!')

        @self.kb.add('*')
        def _(event):
            self._switch_mode_or_insert(event, InputModeEnum.PLAN, '*')

        @self.kb.add('#')
        def _(event):
            self._switch_mode_or_insert(event, InputModeEnum.MEMORY, '#')

        @self.kb.add('backspace')
        def _(event):
            if self.buf.text == '' and self.buf.cursor_position == 0:
                self._switch_mode(event, InputModeEnum.NORMAL)
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
        self.current_input_mode = input_mode_dict[self.current_input_mode.next_mode]
        # Update session style for next prompt
        style = self.current_input_mode.get_style()
        if hasattr(self.session, 'app') and self.session.app:
            self.session.app.style = style or None

    def prompt(self) -> UserInput:
        input_text = self.session.prompt()
        command_name, cleaned_input = self._parse_command(input_text)
        user_input = UserInput(
            user_msg_type=command_name or self.current_input_mode.name.value,
            cleaned_input=cleaned_input,
            raw_input=input_text,
        )
        self._switch_to_next_mode()
        return user_input

    async def prompt_async(self) -> UserInput:
        input_text = await self.session.prompt_async()
        command_name, cleaned_input = self._parse_command(input_text)
        user_input = UserInput(
            user_msg_type=command_name or self.current_input_mode.name.value,
            cleaned_input=cleaned_input,
            raw_input=input_text,
        )
        self._switch_to_next_mode()
        return user_input


class UserInputHandler:
    def __init__(self, agent):
        self.agent = agent

    def handle(self, user_input: UserInput) -> bool:
        """
        Handle special mode and command input.
        """
        if user_input.user_msg_type in ALL_COMMANDS_DICT:
            command = ALL_COMMANDS_DICT[user_input.user_msg_type]
            user_msg, need_agent_run = command.handle(self.agent, user_input)
        else:
            user_msg = UserMessage(
                content=user_input.cleaned_input,
                user_msg_type=user_input.user_msg_type,
                user_raw_input=user_input.raw_input,
            )
            need_agent_run = True
        self.agent.append_message(user_msg, print_msg=False)
        for item in user_msg.get_suffix_renderable():
            console.print(item)
        return need_agent_run
