from __future__ import annotations

import re
from types import SimpleNamespace
from typing import cast

from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.keys import Keys

from klaude_code.tui.input.key_bindings import create_key_bindings


def test_ctrl_u_clears_entire_input_buffer() -> None:
    bindings = create_key_bindings(
        capture_clipboard_tag=lambda: None,
        at_token_pattern=re.compile(r"$^"),
        skill_token_pattern=re.compile(r"$^"),
    )
    buffer = Buffer(document=Document("first\nsecond", cursor_position=3))

    binding = bindings.get_bindings_for_keys((Keys.ControlU,))[-1]
    event = cast(KeyPressEvent, SimpleNamespace(current_buffer=buffer))
    binding.handler(event)

    assert buffer.text == ""
    assert buffer.cursor_position == 0
