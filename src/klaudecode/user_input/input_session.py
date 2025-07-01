from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings

from ..tui import console
from .input_completer import UserInputCompleter
from .input_mode import _INPUT_MODES, NORMAL_MODE_NAME, InputModeCommand


class InputSession:
    def __init__(self, workdir: str = None):
        self.current_input_mode: InputModeCommand = _INPUT_MODES[NORMAL_MODE_NAME]
        self.workdir = Path(workdir) if workdir else Path.cwd()

        history_file = self.workdir / '.klaude' / 'input_history.txt'
        if not history_file.exists():
            history_file.parent.mkdir(parents=True, exist_ok=True)
            history_file.touch()
        self.history = FileHistory(str(history_file))
        self.user_input_completer = UserInputCompleter(self)

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

    def _setup_key_bindings(self, buf: Buffer, kb: KeyBindings):
        for mode in _INPUT_MODES.values():
            binding_keys = []
            if hasattr(mode, 'binding_keys'):
                binding_keys = mode.binding_keys()
            elif mode.binding_key():
                binding_keys = [mode.binding_key()]

            for key in binding_keys:
                if not key:
                    continue

                def make_binding(current_mode=mode, bind_key=key):
                    @kb.add(bind_key)
                    def _(event):
                        document = buf.document
                        current_line_start_pos = document.cursor_position + document.get_start_of_line_position()
                        if buf.cursor_position == current_line_start_pos:
                            self._switch_mode(event, current_mode.get_name())
                            return
                        buf.insert_text(bind_key)

                    return _

                make_binding()

        @kb.add('backspace')
        def _(event):
            document = buf.document
            current_line_start_pos = document.cursor_position + document.get_start_of_line_position()
            if buf.cursor_position == current_line_start_pos:
                self._switch_mode(event, NORMAL_MODE_NAME)
                return
            buf.delete_before_cursor()

        @kb.add('c-u')
        def _(event):
            """Clear the entire buffer with ctrl+u (Unix standard)"""
            buf.text = ''
            buf.cursor_position = 0

        @kb.add('enter')
        def _(event):
            buffer = event.current_buffer
            if buffer.text.endswith('\\'):
                buffer.delete_before_cursor()
                buffer.insert_text('\n')
            else:
                buffer.validate_and_handle()

    def _get_session(self):
        kb = KeyBindings()
        session = PromptSession(
            message=self._dyn_prompt,
            key_bindings=kb,
            history=self.history,
            placeholder=self._dyn_placeholder,
            completer=self.user_input_completer,
            style=self.current_input_mode.get_style(),
        )
        self._setup_key_bindings(session.default_buffer, kb)
        return session

    def _switch_to_next_input_mode(self):
        next_mode_name = self.current_input_mode.get_next_mode_name()
        if next_mode_name not in _INPUT_MODES:
            return
        self.current_input_mode = _INPUT_MODES[next_mode_name]

    def prompt(self):
        console.print()
        input_text = self._get_session().prompt()
        if self.current_input_mode.get_name() != NORMAL_MODE_NAME:
            input_text = f'/{self.current_input_mode.get_name()} {input_text}'
        self._switch_to_next_input_mode()
        return input_text

    async def prompt_async(self):
        console.print()
        input_text = await self._get_session().prompt_async()
        if self.current_input_mode.get_name() != NORMAL_MODE_NAME:
            input_text = f'/{self.current_input_mode.get_name()} {input_text}'
        self._switch_to_next_input_mode()
        return input_text
