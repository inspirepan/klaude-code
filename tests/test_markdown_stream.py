from __future__ import annotations

import io

from rich.console import Console
from rich.text import Text
from rich.theme import Theme

from klaude_code.tui.components.rich.live import SingleLine
from klaude_code.tui.components.rich.markdown import MarkdownStream


def _make_stream(*, width: int = 80) -> MarkdownStream:
    theme = Theme(
        {
            "markdown.code.border": "dim",
            "markdown.code.block": "dim",
            "markdown.thinking": "dim",
            "markdown.thinking.tag": "dim",
            "markdown.h1": "bold",
            "markdown.h2.border": "dim",
            "markdown.hr": "dim",
        }
    )
    console = Console(file=io.StringIO(), force_terminal=True, width=width, theme=theme)
    return MarkdownStream(console=console, theme=theme, left_margin=2, mark=">", mark_style="bold")


def test_candidate_stable_line_incomplete_fence_is_zero() -> None:
    stream = _make_stream()
    assert stream.compute_candidate_stable_line("```py\nprint(1)\n") == 0


def test_split_source_stabilizes_only_before_last_block() -> None:
    stream = _make_stream()
    text = "hello\n\nworld"
    stable_source, live_source, stable_line = stream.split_blocks(text, final=False)

    assert stable_line > 0
    assert stable_source
    assert live_source
    assert stable_source + live_source == text


def test_single_line_wrapper_renders_first_line_only() -> None:
    console = Console(file=io.StringIO(), force_terminal=True, width=20)
    wrapped = SingleLine(Text("line1\nline2\nline3"))
    lines = console.render_lines(wrapped, console.options, pad=False)
    assert len(lines) == 1


def test_update_does_not_write_synchronized_output_sequences_when_not_tty() -> None:
    theme = Theme(
        {
            "markdown.code.border": "dim",
            "markdown.code.block": "dim",
            "markdown.h1": "bold",
            "markdown.h2.border": "dim",
            "markdown.hr": "dim",
        }
    )
    out = io.StringIO()
    console = Console(file=out, force_terminal=True, width=80, theme=theme)
    live_calls: list[object] = []

    def _sink(renderable: object) -> None:
        live_calls.append(renderable)

    stream = MarkdownStream(console=console, theme=theme, live_sink=_sink, left_margin=0)
    stream.min_delay = 0

    stream.update("Para 1\n\nPara 2", final=False)
    captured = out.getvalue()

    assert "\x1b[?2026h" not in captured
    assert "\x1b[?2026l" not in captured
    assert live_calls


def test_update_sets_live_renderable_without_stable_block() -> None:
    theme = Theme(
        {
            "markdown.code.border": "dim",
            "markdown.code.block": "dim",
            "markdown.h1": "bold",
            "markdown.h2.border": "dim",
            "markdown.hr": "dim",
        }
    )
    out = io.StringIO()
    console = Console(file=out, force_terminal=True, width=80, theme=theme)
    live_calls: list[object] = []

    def _sink(renderable: object) -> None:
        live_calls.append(renderable)

    stream = MarkdownStream(console=console, theme=theme, live_sink=_sink, left_margin=0)
    stream.min_delay = 0

    stream.update("Single block", final=False)

    assert out.getvalue() == ""
    # When there is no stable block yet, the stream does not update the live area.
    assert live_calls == []


def test_update_applies_mark_to_live_when_all_live() -> None:
    live_calls: list[object] = []

    def _sink(renderable: object) -> None:
        live_calls.append(renderable)

    theme = Theme(
        {
            "markdown.code.border": "dim",
            "markdown.code.block": "dim",
            "markdown.thinking": "dim",
            "markdown.thinking.tag": "dim",
            "markdown.h1": "bold",
            "markdown.h2.border": "dim",
            "markdown.hr": "dim",
        }
    )
    console = Console(file=io.StringIO(), force_terminal=True, width=80, theme=theme)
    stream = MarkdownStream(console=console, theme=theme, live_sink=_sink, left_margin=2, mark=">", mark_style="bold")
    stream.min_delay = 0

    stream.update("hello", final=False)

    # Same as above: without any stable block, we don't emit a live renderable.
    assert live_calls == []
