from __future__ import annotations

import io

from rich.cells import cell_len
from rich.console import Console
from rich.text import Text

from klaude_code.protocol import model
from klaude_code.tui.components.rich.status import ThreeLineStatusText, truncate_left, truncate_status
from klaude_code.tui.components.rich.theme import ThemeKey, get_theme
from klaude_code.tui.machine import SpinnerStatusState


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
        "Explore model definitions (Usage, TaskMetadata) to understand existing fields | Exploring esc to interrupt"
    )
    result = truncate_status(text, 50, console=console)
    # The right part is " | Exploring esc to interrupt" which is 29 chars
    # max width is 50. left_budget is 21. ellipsis takes 1. prefix takes 19.
    # prefix is "Explore model defini". Result: "Explore model defini… | Exploring esc to interrupt"
    assert result.plain == "Explore model defini… | Exploring esc to interrupt"


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


def test_shimmer_status_with_right_text_renders_three_lines() -> None:
    console = Console(file=io.StringIO(), force_terminal=True, width=120, theme=get_theme().app_theme)
    status = ThreeLineStatusText(
        "Thinking",
        Text("95.1%", style=ThemeKey.METADATA_DIM),
        Text("Loading …", style=ThemeKey.STATUS_TEXT),
    )
    lines = console.render_lines(status, console.options.update(no_wrap=True, overflow="ellipsis"), pad=False)
    assert len(lines) == 3

    first_line = "".join(segment.text for segment in lines[0] if segment.text)
    second_line = "".join(segment.text for segment in lines[1] if segment.text)
    third_line = "".join(segment.text for segment in lines[2] if segment.text)

    assert "Thinking" in first_line
    assert "Loading …" in second_line
    assert "esc to interrupt · 95.1%" in third_line


def test_shimmer_status_without_primary_line_renders_only_second_and_third() -> None:
    console = Console(file=io.StringIO(), force_terminal=True, width=120, theme=get_theme().app_theme)
    status = ThreeLineStatusText("", Text("95.1%", style=ThemeKey.METADATA_DIM), Text("Typing …", style=ThemeKey.STATUS_TEXT))
    lines = console.render_lines(status, console.options.update(no_wrap=True, overflow="ellipsis"), pad=False)

    assert len(lines) == 2
    first_line = "".join(segment.text for segment in lines[0] if segment.text)
    second_line = "".join(segment.text for segment in lines[1] if segment.text)
    assert "Typing …" in first_line
    assert "esc to interrupt · 95.1%" in second_line


def test_third_line_drops_hint_when_width_is_tight() -> None:
    state = SpinnerStatusState()
    state.set_context_usage(
        model.Usage(
            input_tokens=30_000,
            cached_tokens=20_000,
            output_tokens=12_000,
            reasoning_tokens=2_000,
        )
    )
    right_text = state.get_right_text()
    assert right_text is not None

    width = cell_len(right_text.plain)
    console = Console(file=io.StringIO(), force_terminal=True, width=width, theme=get_theme().app_theme)
    status = ThreeLineStatusText("", right_text, Text("Loading …", style=ThemeKey.STATUS_TEXT))
    lines = console.render_lines(
        status,
        console.options.update(no_wrap=True, overflow="ellipsis", max_width=width),
        pad=False,
    )

    third_line = "".join(segment.text for segment in lines[-1] if segment.text)
    assert third_line == right_text.plain
    assert "esc to interrupt" not in third_line


def test_third_line_compacts_tokens_after_dropping_hint() -> None:
    state = SpinnerStatusState()
    state.set_context_usage(
        model.Usage(
            input_tokens=300_000,
            cached_tokens=200_000,
            output_tokens=120_000,
            reasoning_tokens=20_000,
            image_tokens=3_000,
            context_size=460_000,
            context_limit=900_000,
            max_tokens=100_000,
        )
    )
    right_text = state.get_right_text()
    assert right_text is not None

    compact_plain = right_text.render(compact=True).plain
    full_plain = right_text.plain
    assert cell_len(compact_plain) < cell_len(full_plain)

    width = cell_len(compact_plain)
    console = Console(file=io.StringIO(), force_terminal=True, width=width, theme=get_theme().app_theme)
    status = ThreeLineStatusText("", right_text, Text("Loading …", style=ThemeKey.STATUS_TEXT))
    lines = console.render_lines(
        status,
        console.options.update(no_wrap=True, overflow="ellipsis", max_width=width),
        pad=False,
    )

    third_line = "".join(segment.text for segment in lines[-1] if segment.text)
    assert third_line == compact_plain
    assert "esc to interrupt" not in third_line
    assert "↑" in third_line
