from __future__ import annotations

from rich.console import Console
from rich.text import Text

from klaude_code.tui.components.rich.status import truncate_left, truncate_status


def test_truncate_left_noop_when_fits() -> None:
    console = Console()
    text = Text("abc")
    result = truncate_left(text, 3, console=console)
    assert result.plain == "abc"


def test_truncate_left_keeps_suffix_with_ellipsis() -> None:
    console = Console()
    text = Text("abcdef")
    result = truncate_left(text, 4, console=console)
    assert result.plain == "… ef"


def test_truncate_left_uses_cell_width_for_wide_chars() -> None:
    console = Console()
    text = Text("你好世界")
    result = truncate_left(text, 5, console=console)
    assert result.plain == "… 界"


def test_truncate_left_tiny_width_returns_ellipsis_only() -> None:
    console = Console()
    text = Text("abcdef")
    result = truncate_left(text, 1, console=console)
    assert result.plain == "…"


def test_truncate_status_with_pipe_truncates_left_side() -> None:
    console = Console()
    text = Text(
        "Explore model definitions (Usage, TaskMetadata) to understand existing fields | Exploring (esc to interrupt)"
    )
    result = truncate_status(text, 50, console=console)
    # The right part is " | Exploring (esc to interrupt)" which is 31 chars
    # max width is 50. left_budget is 19. ellipsis takes 1. prefix takes 18.
    # prefix is "Explore model defi". Result: "Explore model defi… | Exploring (esc to interrupt)"
    assert result.plain == "Explore model defi… | Exploring (esc to interrupt)"


def test_truncate_status_without_pipe_falls_back() -> None:
    console = Console()
    text = Text("very long status description")
    result = truncate_status(text, 15, console=console)
    # Falls back to truncate_left. ellipsis+space = 2. suffix budget = 13.
    # suffix is "s description".
    assert result.plain == "… s description"


def test_truncate_status_when_pipe_right_part_too_long() -> None:
    console = Console()
    text = Text("todo | super long tool right hand activity")
    result = truncate_status(text, 20, console=console)
    # right part " | super long tool right hand activity" is 38 chars
    # It does not fit. So it falls back to truncate_left(text).
    # Ellipsis takes 2 chars. suffix budget 18.
    # "ht hand activity" = 16. "ght hand activity" = 17.
    assert result.plain == "… ight hand activity"
