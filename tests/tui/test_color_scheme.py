"""Tests for terminal color-scheme change reporting (DEC mode 2031)."""

from prompt_toolkit.input.vt100_parser import Vt100Parser
from prompt_toolkit.key_binding.key_processor import KeyPress
from prompt_toolkit.keys import Keys

from klaude_code.tui.input.color_scheme import (
    COLOR_SCHEME_REPORT_DISABLE,
    COLOR_SCHEME_REPORT_ENABLE,
    install_color_scheme_sequences,
    theme_from_key_data,
)


def _parse(data: str) -> list[KeyPress]:
    install_color_scheme_sequences()
    keys: list[KeyPress] = []
    parser = Vt100Parser(keys.append)
    parser.feed(data)
    parser.flush()
    return keys


def test_dark_report_parses_to_single_ignore_key() -> None:
    """Without the mapping this parsed as Escape (interrupting the running
    task) plus the literal text ``[?997;1n``."""
    keys = _parse("\x1b[?997;1n")
    assert [k.key for k in keys] == [Keys.Ignore]
    assert keys[0].data == "\x1b[?997;1n"


def test_light_report_parses_to_single_ignore_key() -> None:
    keys = _parse("\x1b[?997;2n")
    assert [k.key for k in keys] == [Keys.Ignore]
    assert keys[0].data == "\x1b[?997;2n"


def test_report_does_not_leak_literal_text() -> None:
    keys = _parse("\x1b[?997;1nhi")
    printable = "".join(k.data for k in keys if len(k.data) == 1 and k.data.isprintable())
    assert printable == "hi"


def test_theme_from_key_data_mapping() -> None:
    assert theme_from_key_data("\x1b[?997;1n") == "dark"
    assert theme_from_key_data("\x1b[?997;2n") == "light"
    # Any other Ignore press (e.g. a CSI-u key release) must stay a no-op.
    assert theme_from_key_data("\x1b[119;5:3u") is None
    assert theme_from_key_data("") is None


def test_mode_2031_sequence_shapes() -> None:
    assert COLOR_SCHEME_REPORT_ENABLE == "\x1b[?2031h"
    assert COLOR_SCHEME_REPORT_DISABLE == "\x1b[?2031l"
