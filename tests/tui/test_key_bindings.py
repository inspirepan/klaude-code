from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.keys import Keys

from klaude_code.tui.input.key_bindings import create_key_bindings


def test_ctrl_u_clears_to_start_of_current_logical_line() -> None:
    bindings = create_key_bindings(
        capture_clipboard_tag=lambda: None,
        at_token_pattern=re.compile(r"$^"),
        skill_token_pattern=re.compile(r"$^"),
    )
    buffer = Buffer(document=Document("first line\nsecond line", cursor_position=18))

    binding = bindings.get_bindings_for_keys((Keys.ControlU,))[-1]
    event = cast(KeyPressEvent, SimpleNamespace(current_buffer=buffer))
    binding.handler(event)

    assert buffer.text == "first line\nline"
    assert buffer.cursor_position == 11


def test_ctrl_x_clears_entire_input_buffer() -> None:
    bindings = create_key_bindings(
        capture_clipboard_tag=lambda: None,
        at_token_pattern=re.compile(r"$^"),
        skill_token_pattern=re.compile(r"$^"),
    )
    buffer = Buffer(document=Document("first\nsecond", cursor_position=9))

    binding = bindings.get_bindings_for_keys((Keys.ControlX,))[-1]
    event = cast(KeyPressEvent, SimpleNamespace(current_buffer=buffer))
    binding.handler(event)

    assert buffer.text == ""
    assert buffer.cursor_position == 0


def test_large_bracketed_paste_saves_file_and_inserts_marker(tmp_path: Path) -> None:
    bindings = create_key_bindings(
        capture_clipboard_tag=lambda: None,
        at_token_pattern=re.compile(r"$^"),
        skill_token_pattern=re.compile(r"$^"),
        get_session_dir=lambda: tmp_path,
    )
    buffer = Buffer()
    text = "x" * 2000

    binding = bindings.get_bindings_for_keys((Keys.BracketedPaste,))[-1]
    event = cast(KeyPressEvent, SimpleNamespace(current_buffer=buffer, data=text))
    binding.handler(event)

    assert re.fullmatch(r"\[paste #\d+ 2000 chars\] ", buffer.text)
    paste_file = next((tmp_path / "paste-files").iterdir())
    assert paste_file.read_text(encoding="utf-8") == text


def test_small_bracketed_paste_stays_inline(tmp_path: Path) -> None:
    bindings = create_key_bindings(
        capture_clipboard_tag=lambda: None,
        at_token_pattern=re.compile(r"$^"),
        skill_token_pattern=re.compile(r"$^"),
        get_session_dir=lambda: tmp_path,
    )
    buffer = Buffer()

    binding = bindings.get_bindings_for_keys((Keys.BracketedPaste,))[-1]
    event = cast(KeyPressEvent, SimpleNamespace(current_buffer=buffer, data="alpha\nbeta"))
    binding.handler(event)

    assert buffer.text == "alpha\nbeta"
    assert not (tmp_path / "paste-files").exists()


def test_tab_toggles_btw_prefix_while_agent_runs() -> None:
    bindings = create_key_bindings(
        capture_clipboard_tag=lambda: None,
        at_token_pattern=re.compile(r"$^"),
        skill_token_pattern=re.compile(r"$^"),
        is_agent_running=lambda: True,
    )
    buffer = Buffer(document=Document("explain this", cursor_position=7))
    invalidations = SimpleNamespace(count=0)
    event = cast(
        KeyPressEvent,
        SimpleNamespace(
            current_buffer=buffer,
            app=SimpleNamespace(invalidate=lambda: setattr(invalidations, "count", invalidations.count + 1)),
        ),
    )
    binding = next(
        binding
        for binding in bindings.get_bindings_for_keys((Keys.ControlI,))
        if binding.handler.__doc__ and "queued follow-up" in binding.handler.__doc__
    )

    binding.handler(event)

    assert buffer.text == "/btw explain this"
    assert buffer.cursor_position == 12

    binding.handler(event)

    assert buffer.text == "explain this"
    assert buffer.cursor_position == 7
    assert invalidations.count == 2
