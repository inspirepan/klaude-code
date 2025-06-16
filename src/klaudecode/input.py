from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from prompt_toolkit.history import FileHistory
from pydantic import BaseModel
from pathlib import Path
from enum import Enum


class InputModeEnum(Enum):
    NORMAL = "normal"
    PLAN = "plan"
    BASH = "bash"
    MEMORY = "memory"
    INTERRUPTED = "interrupted"


class InputMode(BaseModel):
    name: InputModeEnum
    prompt: str
    placeholder: str
    style: str
    next_mode: InputModeEnum

    def get_prompt(self):
        if self.style:
            return HTML(f'<style fg="{self.style}">{self.prompt} </style>')
        return self.prompt + " "

    def get_style(self):
        if self.style:
            return Style.from_dict({
                'placeholder': self.style,
                '': self.style,
            })
        return None


class UserInput(BaseModel):
    mode: InputModeEnum
    input: str


input_mode_dict = {
    InputModeEnum.NORMAL: InputMode(name=InputModeEnum.NORMAL, prompt=">", placeholder="", style="", next_mode=InputModeEnum.NORMAL),
    InputModeEnum.PLAN: InputMode(name=InputModeEnum.PLAN, prompt="*", placeholder="type plan...", style="#2a6465", next_mode=InputModeEnum.PLAN),
    InputModeEnum.BASH: InputMode(name=InputModeEnum.BASH, prompt="!", placeholder="type command...", style="#ea3386", next_mode=InputModeEnum.NORMAL),
    InputModeEnum.MEMORY: InputMode(name=InputModeEnum.MEMORY, prompt="#", placeholder="type memory...", style="#0000f5", next_mode=InputModeEnum.NORMAL),
}


class InputSession:
    def __init__(self, workdir: str = None):
        self.current_input_mode = input_mode_dict[InputModeEnum.NORMAL]
        self.workdir = Path(workdir) if workdir else Path.cwd()

        # Create history file path
        history_file = self.workdir / ".klaude" / "input_history"
        if not history_file.exists():
            history_file.parent.mkdir(parents=True, exist_ok=True)
            history_file.touch()
        self.history = FileHistory(str(history_file))

        # Create key bindings
        self.kb = KeyBindings()
        self._setup_key_bindings()

        # Create session
        self.session = PromptSession(
            self._dyn_prompt,
            key_bindings=self.kb,
            enable_history_search=True,
            history=self.history,
            placeholder=self._dyn_placeholder,
        )
        self.buf = self.session.default_buffer

    def _dyn_prompt(self):
        return self.current_input_mode.get_prompt()

    def _dyn_placeholder(self):
        return self.current_input_mode.placeholder

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
        if self.buf.text == "" and self.buf.cursor_position == 0:
            self._switch_mode(event, mode_name)
            return
        self.buf.insert_text(char)

    def _setup_key_bindings(self):
        @self.kb.add("!")
        def _(event):
            """
            Press '!' at line start: switch to bash mode; don't write to buffer.
            If cursor is not at line start or buffer is not empty, insert '!' normally
            """
            self._switch_mode_or_insert(event, InputModeEnum.BASH, "!")

        @self.kb.add("*")
        def _(event):
            self._switch_mode_or_insert(event, InputModeEnum.PLAN, "*")

        @self.kb.add("#")
        def _(event):
            self._switch_mode_or_insert(event, InputModeEnum.MEMORY, "#")

        @self.kb.add("backspace")
        def _(event):
            if self.buf.text == "" and self.buf.cursor_position == 0:
                self._switch_mode(event, InputModeEnum.NORMAL)
                return
            self.buf.delete_before_cursor()

        @self.kb.add("enter")
        def _(event):
            """
            Check if ends with backslash:
            - If yes, remove backslash and insert newline to continue editing
            - If no, submit input normally
            """
            text = self.buf.text
            if text.endswith("\\"):
                # Remove trailing backslash
                self.buf.delete_before_cursor()
                # Insert newline
                self.buf.insert_text("\n")
            else:
                # Normal submit
                event.app.exit(result=self.buf.text)

    def _switch_to_next_mode(self):
        self.current_input_mode = input_mode_dict[self.current_input_mode.next_mode]
        # Update session style for next prompt
        style = self.current_input_mode.get_style()
        if hasattr(self.session, 'app') and self.session.app:
            self.session.app.style = style or None

    def prompt(self) -> UserInput:
        input_text = self.session.prompt()
        user_input = UserInput(
            mode=self.current_input_mode.name,
            input=input_text,
        )
        self._switch_to_next_mode()
        return user_input

    async def prompt_async(self) -> UserInput:
        # TODO: return with mode name
        input_text = await self.session.prompt_async()
        user_input = UserInput(
            mode=self.current_input_mode.name,
            input=input_text,
        )
        self._switch_to_next_mode()
        return user_input
