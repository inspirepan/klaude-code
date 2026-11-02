import pytest
from prompt_toolkit.input.vt100_parser import Vt100Parser
from prompt_toolkit.key_binding.key_processor import KeyPress
from prompt_toolkit.keys import Keys

from klaude_code.tui.input.program_status import ProgramStatusParser


@pytest.mark.parametrize("ending", ["\x1b\\", "\x07"])
@pytest.mark.parametrize(
    "body", ["?", " ? : states = idle, working,done,blocked,error : kinds = question:extension=value"]
)
def test_split_replies_never_reach_editor(ending: str, body: str) -> None:
    keys: list[KeyPress] = []
    replies: list[str] = []
    parser = ProgramStatusParser(Vt100Parser(keys.append), replies.append)
    reply = f"\x1b]7501;{body}{ending}"
    parser.feed("hello")
    for char in reply:
        parser.feed(char)
        # The full header can outlive the normal escape timeout.
        if len(replies) == 0 and char in ("?", "=", ","):
            parser.flush()
    parser.feed("world\x1b[A")
    parser.flush()
    assert replies == [reply]
    assert "".join(key.data for key in keys) == "helloworld\x1b[A"
    assert keys[-1].key == Keys.Up


def test_normal_escape_and_bracketed_paste_are_unchanged() -> None:
    keys: list[KeyPress] = []
    replies: list[str] = []
    parser = ProgramStatusParser(Vt100Parser(keys.append), replies.append)
    parser.feed("\x1b")
    parser.flush()
    assert keys.pop().key == Keys.Escape
    text = "\x1b]7501;?\x07"
    parser.feed(f"\x1b[200~{text}\x1b[201~")
    assert replies == []
    assert keys == [KeyPress(Keys.BracketedPaste, text)]


@pytest.mark.parametrize("data", ["typing text", "\x1b]text", "\x1b[A\x1bx", "\x1b[12;34R", "\x1b]0;title\x07"])
def test_other_input_matches_original_parser(data: str) -> None:
    expected: list[KeyPress] = []
    actual: list[KeyPress] = []
    original = Vt100Parser(expected.append)
    parser = ProgramStatusParser(Vt100Parser(actual.append), lambda _: pytest.fail("Unexpected capability reply"))
    for char in data:
        original.feed(char)
        parser.feed(char)
    original.flush()
    parser.flush()
    assert actual == expected
