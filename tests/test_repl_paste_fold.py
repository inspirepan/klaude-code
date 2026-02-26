from __future__ import annotations

from klaude_code.tui.input.paste import PasteBufferState


def test_store_uses_lines_marker_when_many_lines() -> None:
    state = PasteBufferState()
    text = "\n".join([f"line {i}" for i in range(11)])
    marker = state.store(text)
    assert marker == "[paste #1 +11 lines]"


def test_store_uses_chars_marker_when_very_long_single_line() -> None:
    state = PasteBufferState()
    text = "x" * 1001
    marker = state.store(text)
    assert marker == "[paste #1 1001 chars]"


def test_expand_replaces_marker_with_original_content() -> None:
    state = PasteBufferState()
    text = "hello\nworld\n"
    marker = state.store(text)
    expanded = state.expand_markers(f"prefix {marker} suffix")
    assert expanded == f"prefix \n{text}\n suffix"


def test_expand_keeps_unknown_marker_intact() -> None:
    state = PasteBufferState()
    out = state.expand_markers("[paste #999 +12 lines]")
    assert out == "[paste #999 +12 lines]"
