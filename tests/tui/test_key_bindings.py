from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from prompt_toolkit.buffer import Buffer, CompletionState
from prompt_toolkit.completion import Completion
from prompt_toolkit.document import Document
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.keys import Keys

from klaude_code.tui.input.key_bindings import create_key_bindings


def test_enter_with_legacy_alt_enter_data_submits_follow_up_and_resets_marker() -> None:
    follow_up = False
    submitted: list[tuple[str, bool]] = []

    def set_follow_up(value: bool) -> None:
        nonlocal follow_up
        follow_up = value

    def accept(buffer: Buffer) -> bool:
        submitted.append((buffer.text, follow_up))
        return False

    bindings = create_key_bindings(
        capture_clipboard_tag=lambda: None,
        at_token_pattern=re.compile(r"$^"),
        skill_token_pattern=re.compile(r"$^"),
        set_follow_up_submission=set_follow_up,
    )
    buffer = Buffer(document=Document("later"), accept_handler=accept)
    binding = bindings.get_bindings_for_keys((Keys.ControlM,))[-1]
    binding.handler(cast(KeyPressEvent, SimpleNamespace(current_buffer=buffer, data="\x1b\r")))
    assert submitted == [("later", True)]
    assert not follow_up
    buffer.text = "next"
    binding.handler(cast(KeyPressEvent, SimpleNamespace(current_buffer=buffer, data="\r")))
    assert submitted == [("later", True), ("next", False)]


def test_alt_enter_accepts_completion_before_submitting_without_marking_next_enter() -> None:
    markers: list[bool] = []
    submitted: list[str] = []
    bindings = create_key_bindings(
        capture_clipboard_tag=lambda: None,
        at_token_pattern=re.compile(r"$^"),
        skill_token_pattern=re.compile(r"$^"),
        set_follow_up_submission=markers.append,
    )

    def accept(buffer: Buffer) -> bool:
        submitted.append(buffer.text)
        return False

    buffer = Buffer(document=Document("va"), accept_handler=accept)
    buffer.complete_state = CompletionState(buffer.document, [Completion("value", start_position=-2)])
    event = cast(KeyPressEvent, SimpleNamespace(current_buffer=buffer, data="\x1b\r"))
    bindings.get_bindings_for_keys((Keys.Escape, Keys.ControlM))[-1].handler(event)
    assert buffer.text == "value" and not submitted and not markers
    bindings.get_bindings_for_keys((Keys.ControlM,))[-1].handler(
        cast(KeyPressEvent, SimpleNamespace(current_buffer=buffer, data="\r"))
    )
    assert submitted == ["value"] and markers == [False, False]


@pytest.mark.parametrize("alt_enter", [False, True])
def test_vscode_backslash_newline_applies_only_to_plain_enter(monkeypatch: pytest.MonkeyPatch, alt_enter: bool) -> None:
    monkeypatch.setenv("TERM_PROGRAM", "vscode")
    submitted: list[str] = []
    markers: list[bool] = []

    def accept(buffer: Buffer) -> bool:
        submitted.append(buffer.text)
        return False

    bindings = create_key_bindings(
        capture_clipboard_tag=lambda: None,
        at_token_pattern=re.compile(r"$^"),
        skill_token_pattern=re.compile(r"$^"),
        set_follow_up_submission=markers.append,
    )
    buffer = Buffer(document=Document("path\\"), accept_handler=accept)
    keys = (Keys.Escape, Keys.ControlM) if alt_enter else (Keys.ControlM,)
    event = cast(KeyPressEvent, SimpleNamespace(current_buffer=buffer, data="\r"))
    bindings.get_bindings_for_keys(keys)[-1].handler(event)
    if alt_enter:
        assert submitted == ["path\\"] and markers == [True, False]
    else:
        assert not submitted and not markers
        assert buffer.text == "path\n"


def test_clipboard_image_is_read_only_when_ctrl_v_is_pressed() -> None:
    captures: list[bool] = []

    def capture() -> str:
        captures.append(True)
        return "[image /tmp/clipboard.png]"

    bindings = create_key_bindings(
        capture_clipboard_tag=capture,
        at_token_pattern=re.compile(r"$^"),
        skill_token_pattern=re.compile(r"$^"),
    )
    assert not captures
    buffer = Buffer()
    event = cast(KeyPressEvent, SimpleNamespace(current_buffer=buffer))
    bindings.get_bindings_for_keys((Keys.ControlV,))[-1].handler(event)

    assert captures == [True]
    assert buffer.text == "[image /tmp/clipboard.png]"


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
        if binding.handler.__doc__ and "queued steering" in binding.handler.__doc__
    )

    binding.handler(event)

    assert buffer.text == "/btw explain this"
    assert buffer.cursor_position == 12

    binding.handler(event)

    assert buffer.text == "explain this"
    assert buffer.cursor_position == 7
    assert invalidations.count == 2
