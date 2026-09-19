from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
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
        paste_dir=tmp_path,
    )
    buffer = Buffer()
    text = "x" * 2000

    binding = bindings.get_bindings_for_keys((Keys.BracketedPaste,))[-1]
    event = cast(KeyPressEvent, SimpleNamespace(current_buffer=buffer, data=text))
    binding.handler(event)

    paste_file = next(tmp_path.iterdir())
    assert buffer.text == f"[paste #1 2000 chars: {paste_file.resolve()}] "
    assert paste_file.read_text(encoding="utf-8") == text


def test_small_bracketed_paste_stays_inline(tmp_path: Path) -> None:
    bindings = create_key_bindings(
        capture_clipboard_tag=lambda: None,
        at_token_pattern=re.compile(r"$^"),
        skill_token_pattern=re.compile(r"$^"),
        paste_dir=tmp_path,
    )
    buffer = Buffer()

    binding = bindings.get_bindings_for_keys((Keys.BracketedPaste,))[-1]
    event = cast(KeyPressEvent, SimpleNamespace(current_buffer=buffer, data="alpha\nbeta"))
    binding.handler(event)

    assert buffer.text == "alpha\nbeta"
    assert list(tmp_path.iterdir()) == []


def test_bracketed_paste_of_dropped_path_inserts_at_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Terminals that drop an escaped plain path (no file:// URI) still get an @ token."""

    dropped = tmp_path / "a.txt"
    dropped.write_text("hi", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    bindings = create_key_bindings(
        capture_clipboard_tag=lambda: None,
        at_token_pattern=re.compile(r"$^"),
        skill_token_pattern=re.compile(r"$^"),
        paste_dir=tmp_path,
    )
    buffer = Buffer()

    binding = bindings.get_bindings_for_keys((Keys.BracketedPaste,))[-1]
    event = cast(KeyPressEvent, SimpleNamespace(current_buffer=buffer, data=str(dropped)))
    binding.handler(event)

    assert buffer.text == "@a.txt "


def test_bracketed_paste_in_bash_mode_keeps_plain_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A path pasted into bash mode goes to the shell verbatim, not as an @ token."""

    dropped = tmp_path / "a.txt"
    dropped.write_text("hi", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    bindings = create_key_bindings(
        capture_clipboard_tag=lambda: None,
        at_token_pattern=re.compile(r"$^"),
        skill_token_pattern=re.compile(r"$^"),
        paste_dir=tmp_path,
    )
    buffer = Buffer(document=Document("!wc -l ", cursor_position=7))

    binding = bindings.get_bindings_for_keys((Keys.BracketedPaste,))[-1]
    event = cast(KeyPressEvent, SimpleNamespace(current_buffer=buffer, data=str(dropped)))
    binding.handler(event)

    assert buffer.text == f"!wc -l {dropped}"


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
