"""Tests for kitty keyboard protocol (CSI u) input tolerance."""

from prompt_toolkit.input.vt100_parser import Vt100Parser
from prompt_toolkit.key_binding.key_processor import KeyPress
from prompt_toolkit.keys import Keys

from klaude_code.tui.input.csi_u import KITTY_KEYBOARD_RESET, install_csi_u_sequences


def _parse(data: str) -> list[KeyPress]:
    install_csi_u_sequences()
    keys: list[KeyPress] = []
    parser = Vt100Parser(keys.append)
    parser.feed(data)
    parser.flush()
    return keys


def test_ctrl_w_csi_u_maps_to_control_w() -> None:
    """Regression: a leaked kitty keyboard mode encodes Ctrl+W as CSI 119;5u.

    Without the mapping this parsed as Escape (interrupting the running task)
    plus the literal text ``[119;5u``.
    """
    keys = _parse("\x1b[119;5u")
    assert [k.key for k in keys] == [Keys.ControlW]


def test_csi_u_escape_and_enter_map_to_their_keys() -> None:
    assert [k.key for k in _parse("\x1b[27u")] == [Keys.Escape]
    assert [k.key for k in _parse("\x1b[13u")] == [Keys.ControlM]
    assert [k.key for k in _parse("\x1b[9;2u")] == [Keys.BackTab]


def test_csi_u_key_release_is_ignored() -> None:
    keys = _parse("\x1b[119;5:3u")
    assert [k.key for k in keys] == [Keys.Ignore]


def test_csi_u_repeat_event_maps_like_press() -> None:
    keys = _parse("\x1b[119;5:2u")
    assert [k.key for k in keys] == [Keys.ControlW]


def test_csi_u_does_not_leak_literal_text() -> None:
    """No fragment of the sequence may reach the buffer as typed characters."""
    keys = _parse("\x1b[119;5u\x1b[97;3u")
    datas = "".join(k.data for k in keys if len(k.data) == 1 and k.data.isprintable())
    assert "[" not in datas
    assert "1" not in datas


def test_plain_keys_still_parse_normally() -> None:
    keys = _parse("hi\r")
    assert [k.key for k in keys] == ["h", "i", Keys.ControlM]


def test_kitty_reset_sequence_shape() -> None:
    assert KITTY_KEYBOARD_RESET == "\x1b[=0;1u"
