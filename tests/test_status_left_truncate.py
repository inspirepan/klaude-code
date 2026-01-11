from __future__ import annotations

from rich.console import Console
from rich.text import Text

from klaude_code.tui.components.rich.status import truncate_left


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
