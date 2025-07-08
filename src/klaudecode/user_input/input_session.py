import base64
import threading
from pathlib import Path
from typing import Dict

import pyperclip
from prompt_toolkit import PromptSession
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.cursor_shapes import CursorShape
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings

from ..tui import console
from ..utils.file_utils import is_image_path
from ..utils.str_utils import get_inserted_text
from .input_completer import UserInputCompleter
from .input_mode import _INPUT_MODES, NORMAL_MODE_NAME, InputModeCommand


class PasteItem:
    def __init__(self, type: str, path: str = None, content: str = None):
        self.type = type
        self.path = path
        self.content = content


class InputSession:
    def __init__(self, workdir: str = None):
        self.current_input_mode: InputModeCommand = _INPUT_MODES[NORMAL_MODE_NAME]
        self.workdir = Path(workdir) if workdir else Path.cwd()
        self.paste_dict: Dict[str, PasteItem] = {}
        self.paste_counter = 0

        history_file = self.workdir / '.klaude' / 'input_history.txt'
        if not history_file.exists():
            history_file.parent.mkdir(parents=True, exist_ok=True)
            history_file.touch()
        self.history = FileHistory(str(history_file))

    def _get_next_image_id(self) -> str:
        self.paste_counter += 1
        return str(self.paste_counter)

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

    def _setup_buffer_handlers(self, buf: Buffer):
        """Setup buffer event handlers including text change detection."""
        previous_text = ''
        timer = None

        def handle_inserted_text():
            nonlocal previous_text
            current_text = buf.text

            # Check if text was inserted (not deleted)
            if len(current_text) > len(previous_text):
                # Get the newly inserted text
                inserted_text = get_inserted_text(previous_text, current_text)
                # Check if inserted text is an image path
                if inserted_text and is_image_path(inserted_text):
                    # Generate next image ID and store in paste dict
                    image_id = self._get_next_image_id()
                    self.paste_dict[image_id] = PasteItem(type='file', path=inserted_text.strip())

                    # Replace the inserted text with [Image #N] format
                    new_text = f'[Image #{image_id}]'
                    buf.text = current_text.replace(inserted_text, new_text)
                    buf.cursor_position = len(buf.text)

            previous_text = buf.text

        def on_text_changed(_):
            nonlocal timer
            # Cancel any pending timer
            if timer:
                timer.cancel()

            # Schedule a new check after a short delay (50ms)
            timer = threading.Timer(0.05, handle_inserted_text)
            timer.start()

        # Attach the handler
        buf.on_text_changed += on_text_changed

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

        @kb.add('c-v')
        def _(event):
            """Handle Ctrl+V paste with image detection"""
            try:
                # Try to get image from clipboard first
                from PIL import ImageGrab

                clipboard_image = ImageGrab.grabclipboard()

                if clipboard_image is not None:
                    # Convert image to base64
                    import io

                    img_buffer = io.BytesIO()
                    clipboard_image.save(img_buffer, format='PNG')
                    img_base64 = base64.b64encode(img_buffer.getvalue()).decode('utf-8')

                    # Generate next image ID and store in paste dict
                    image_id = self._get_next_image_id()
                    self.paste_dict[image_id] = PasteItem(type='clipboard', content=img_base64)

                    # Insert the image reference
                    image_text = f'[Image #{image_id}]'
                    buf.insert_text(image_text)
                else:
                    # Fall back to regular text paste
                    try:
                        text = pyperclip.paste()
                        if text:
                            buf.insert_text(text)
                    except Exception:
                        pass
            except Exception:
                # If image grabbing fails, try regular text paste
                try:
                    text = pyperclip.paste()
                    if text:
                        buf.insert_text(text)
                except Exception:
                    pass

        @kb.add('enter')
        def _(event):
            buffer = event.current_buffer
            cursor_pos = buffer.cursor_position
            # Check if there's a backslash immediately before cursor
            if cursor_pos > 0 and buffer.text[cursor_pos - 1] == '\\':
                # Delete the backslash
                buffer.delete_before_cursor()
                # Insert newline
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
            cursor=CursorShape.BEAM,
            completer=UserInputCompleter(
                enable_file_completion_callabck=lambda: self.current_input_mode.get_name() in [NORMAL_MODE_NAME, 'plan'],
                enable_command_callabck=lambda: self.current_input_mode.get_name() == NORMAL_MODE_NAME,
            ),
            style=self.current_input_mode.get_style(),
        )
        self._setup_key_bindings(session.default_buffer, kb)
        self._setup_buffer_handlers(session.default_buffer)
        return session

    def reset_normal_mode(self):
        self.current_input_mode = _INPUT_MODES[NORMAL_MODE_NAME]

    def prompt(self):
        console.print()
        input_text = self._get_session().prompt()
        if self.current_input_mode.get_name() != NORMAL_MODE_NAME:
            input_text = f'/{self.current_input_mode.get_name()} {input_text}'
        return input_text

    async def prompt_async(self):
        console.print()
        input_text = await self._get_session().prompt_async()
        if self.current_input_mode.get_name() != NORMAL_MODE_NAME:
            input_text = f'/{self.current_input_mode.get_name()} {input_text}'
        return input_text
