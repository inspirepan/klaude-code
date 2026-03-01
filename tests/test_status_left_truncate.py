from __future__ import annotations

import io

from rich.cells import cell_len
from rich.console import Console
from rich.text import Text

from klaude_code.protocol import model
from klaude_code.tui.components.rich.status import (
    StackedStatusText,
    current_hint_text,
    truncate_right,
    truncate_status,
)
from klaude_code.tui.components.rich.theme import ThemeKey, get_theme
from klaude_code.tui.machine import SpinnerStatusState


def test_truncate_right_noop_when_fits() -> None:
    console = Console()
    text = Text("abc")
    result = truncate_right(text, 3, console=console)
    assert result.plain == "abc"


def test_truncate_right_keeps_prefix_with_ellipsis() -> None:
    console = Console()
    text = Text("abcdef")
    result = truncate_right(text, 4, console=console)
    assert result.plain == "abc…"


def test_truncate_right_uses_cell_width_for_wide_chars() -> None:
    console = Console()
    text = Text("你好世界")
    result = truncate_right(text, 5, console=console)
    assert result.plain == "你好…"


def test_truncate_right_tiny_width_returns_ellipsis_only() -> None:
    console = Console()
    text = Text("abcdef")
    result = truncate_right(text, 1, console=console)
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
    assert result.plain == "very long stat…"


def test_truncate_status_when_pipe_right_part_too_long() -> None:
    console = Console()
    text = Text("todo | super long tool right hand activity")
    result = truncate_status(text, 20, console=console)
    assert result.plain == "todo | super long t…"


def test_shimmer_status_with_right_text_renders_three_lines() -> None:
    console = Console(file=io.StringIO(), force_terminal=True, width=120, theme=get_theme().app_theme)
    status = StackedStatusText(
        "Thinking",
        Text("95.1%", style=ThemeKey.METADATA_DIM),
        (Text("Loading …", style=ThemeKey.STATUS_TEXT),),
    )
    lines = console.render_lines(status, console.options.update(no_wrap=True, overflow="ellipsis"), pad=False)
    assert len(lines) == 3

    first_line = "".join(segment.text for segment in lines[0] if segment.text)
    second_line = "".join(segment.text for segment in lines[1] if segment.text)
    third_line = "".join(segment.text for segment in lines[2] if segment.text)

    assert "Loading …" in first_line
    assert "Thinking" in second_line
    assert "95.1% · esc to interrupt" in third_line


def test_shimmer_status_without_primary_line_renders_only_second_and_third() -> None:
    console = Console(file=io.StringIO(), force_terminal=True, width=120, theme=get_theme().app_theme)
    status = StackedStatusText(
        "", Text("95.1%", style=ThemeKey.METADATA_DIM), (Text("Typing …", style=ThemeKey.STATUS_TEXT),)
    )
    lines = console.render_lines(status, console.options.update(no_wrap=True, overflow="ellipsis"), pad=False)

    assert len(lines) == 2
    first_line = "".join(segment.text for segment in lines[0] if segment.text)
    second_line = "".join(segment.text for segment in lines[1] if segment.text)
    assert "Typing …" in first_line
    assert "95.1% · esc to interrupt" in second_line


def test_stacked_status_adds_leading_blank_line_when_enabled() -> None:
    console = Console(file=io.StringIO(), force_terminal=True, width=120, theme=get_theme().app_theme)
    status = StackedStatusText(
        "",
        Text("95.1%", style=ThemeKey.METADATA_DIM),
        (Text("Exploring searching", style=ThemeKey.STATUS_TEXT),),
        leading_blank_line=True,
    )
    lines = console.render_lines(status, console.options.update(no_wrap=True, overflow="ellipsis"), pad=False)

    assert len(lines) == 3
    first_line = "".join(segment.text for segment in lines[0] if segment.text)
    second_line = "".join(segment.text for segment in lines[1] if segment.text)
    third_line = "".join(segment.text for segment in lines[2] if segment.text)
    assert first_line == ""
    assert "Exploring searching" in second_line
    assert "95.1% · esc to interrupt" in third_line


def test_third_line_drops_hint_before_compact_when_full_metadata_fits() -> None:
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
    status = StackedStatusText("", right_text, (Text("Loading …", style=ThemeKey.STATUS_TEXT),))
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
    status = StackedStatusText("", right_text, (Text("Loading …", style=ThemeKey.STATUS_TEXT),))
    lines = console.render_lines(
        status,
        console.options.update(no_wrap=True, overflow="ellipsis", max_width=width),
        pad=False,
    )

    third_line = "".join(segment.text for segment in lines[-1] if segment.text)
    assert third_line == compact_plain
    assert "esc to interrupt" not in third_line
    assert "↑" in third_line


def test_third_line_shows_compact_with_hint_when_only_that_fits() -> None:
    state = SpinnerStatusState()
    state.set_context_usage(
        model.Usage(
            input_tokens=300_000,
            cached_tokens=200_000,
            output_tokens=120_000,
            reasoning_tokens=20_000,
            context_size=460_000,
            context_limit=900_000,
            max_tokens=100_000,
        )
    )
    right_text = state.get_right_text()
    assert right_text is not None

    compact_plain = right_text.render(compact=True).plain
    full_plain = right_text.plain
    hint = current_hint_text().strip()
    separator = " · "

    width = cell_len(compact_plain + separator + hint)
    assert cell_len(full_plain) > width

    console = Console(file=io.StringIO(), force_terminal=True, width=width, theme=get_theme().app_theme)
    status = StackedStatusText("", right_text, (Text("Loading …", style=ThemeKey.STATUS_TEXT),))
    lines = console.render_lines(
        status,
        console.options.update(no_wrap=True, overflow="ellipsis", max_width=width),
        pad=False,
    )

    third_line = "".join(segment.text for segment in lines[-1] if segment.text)
    assert third_line == compact_plain + separator + hint


def test_third_line_avoids_compact_when_full_metadata_still_fits() -> None:
    state = SpinnerStatusState()
    state.set_context_usage(
        model.Usage(
            input_tokens=10_000,
            cached_tokens=0,
            output_tokens=5_000,
            reasoning_tokens=0,
        )
    )
    right_text = state.get_right_text()
    assert right_text is not None

    full_plain = right_text.plain
    compact_plain = right_text.render(compact=True).plain
    assert cell_len(compact_plain) < cell_len(full_plain)

    width = cell_len(full_plain) + 1
    assert cell_len(full_plain) <= width
    assert cell_len(full_plain) > width - 4

    console = Console(file=io.StringIO(), force_terminal=True, width=width, theme=get_theme().app_theme)
    status = StackedStatusText("", right_text, (Text("Loading …", style=ThemeKey.STATUS_TEXT),))
    lines = console.render_lines(
        status,
        console.options.update(no_wrap=True, overflow="ellipsis", max_width=width),
        pad=False,
    )

    third_line = "".join(segment.text for segment in lines[-1] if segment.text)
    assert third_line == full_plain
    assert "esc to interrupt" not in third_line
