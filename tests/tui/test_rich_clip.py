import io

import pytest
from rich.console import Console
from rich.text import Text

from klaude_code.tui.components.rich.clip import MaxLines


@pytest.mark.parametrize("expand_hint", [None, "ctrl-t"])
def test_max_lines_preserves_preview_and_marks_hidden_wrapped_lines(expand_hint: str | None) -> None:
    output = io.StringIO()
    console = Console(file=output, width=10, force_terminal=False)
    console.print(MaxLines(Text("abcdefghij" * 3), 2, expand_hint=expand_hint))
    lines = output.getvalue().splitlines()
    if expand_hint is None:
        assert lines == ["abcdefghij", "abcdefghi…"]
    else:
        assert lines[:2] == ["abcdefghij", "abcdefghij"]
        assert " ".join(lines[2:]).split() == ["…", "1", "more", "lines", "·", "ctrl-t"]
        assert all(len(line) <= 10 for line in lines)
