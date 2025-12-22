from __future__ import annotations

import io

from rich.console import Console
from rich.text import Text
from rich.theme import Theme

from klaude_code.ui.rich.markdown import MarkdownStream, NoInsetMarkdown, SingleLine


def _make_stream(*, width: int = 80) -> MarkdownStream:
    theme = Theme(
        {
            "markdown.code.border": "dim",
            "markdown.code.block": "dim",
            "markdown.h1": "bold",
            "markdown.h2.border": "dim",
            "markdown.hr": "dim",
        }
    )
    console = Console(file=io.StringIO(), force_terminal=True, width=width, theme=theme)
    return MarkdownStream(console=console, theme=theme, left_margin=2, mark=">", mark_style="bold")


def _render(stream: MarkdownStream, text: str, *, apply_mark: bool) -> str:
    return stream.render_ansi(text, apply_mark=apply_mark)


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


def test_frame_equivalence_stream_split_vs_full_render() -> None:
    stream = _make_stream(width=100)

    chunks = [
        "Para 1",
        "\n\nPara 2",
        "\n\n```py\nprint(1)\n",
        "```\n\nPara 3",
    ]

    full = ""
    stable_rendered_prev = ""
    min_stable_line = 0

    for chunk in chunks:
        full += chunk
        stable_source, live_source, stable_line = stream.split_blocks(
            full, min_stable_line=min_stable_line, final=False
        )

        stable_rendered = stream.render_stable_ansi(
            stable_source,
            has_live_suffix=bool(live_source),
            final=False,
        )
        live_rendered = _render(stream, live_source, apply_mark=(stable_line == 0))

        combined = stable_rendered + live_rendered
        full_rendered = _render(stream, full, apply_mark=True)

        assert combined == full_rendered
        assert stable_rendered.startswith(stable_rendered_prev)

        stable_rendered_prev = stable_rendered
        min_stable_line = stable_line


def test_live_gap_lines_only_increases_within_block() -> None:
    stream = _make_stream(width=60)

    # Use hard line breaks (two trailing spaces) to force multiple rendered lines
    # within a single paragraph block.
    long_live = "A  \nB  \nC  \nD  \n"
    short_live = "A  \n"

    _stable_source, live_source, stable_line = stream.split_blocks(long_live, final=False)
    assert stable_line == 0
    live_lines_long = stream.render_ansi(live_source, apply_mark=True).splitlines(keepends=True)
    gap_long = stream.compute_live_gap_lines(len(live_lines_long), reset=False)
    assert gap_long == 1

    _stable_source, live_source, stable_line = stream.split_blocks(short_live, final=False)
    assert stable_line == 0
    live_lines_short = stream.render_ansi(live_source, apply_mark=True).splitlines(keepends=True)
    gap_short = stream.compute_live_gap_lines(len(live_lines_short), reset=False)
    assert gap_short >= gap_long
    assert gap_short > 1

    gap_reset = stream.compute_live_gap_lines(len(live_lines_short), reset=True)
    assert gap_reset == 1


def test_code_panel_border_grows_with_longer_code_line() -> None:
    theme = Theme(
        {
            "markdown.code.border": "dim",
            "markdown.code.block": "dim",
            "markdown.h1": "bold",
            "markdown.h2.border": "dim",
            "markdown.hr": "dim",
        }
    )
    console = Console(file=io.StringIO(), force_terminal=True, width=80, theme=theme)
    stream = MarkdownStream(console=console, theme=theme, markdown_class=NoInsetMarkdown)

    short = "```py\nprint(1)\n```\n"
    long = "```py\nprint(1)\nprint('this is a much much much longer line')\n```\n"

    short_ansi = stream.render_ansi(short, apply_mark=False)
    long_ansi = stream.render_ansi(long, apply_mark=False)

    short_lines = short_ansi.splitlines()
    long_lines = long_ansi.splitlines()

    assert len(long_lines[0]) > len(short_lines[0])
    assert len(long_lines[0]) == len(long_lines[-1])


def test_heading_list_boundary_does_not_double_blank_during_streaming() -> None:
    theme = Theme(
        {
            "markdown.code.border": "dim",
            "markdown.code.block": "dim",
            "markdown.h1": "bold",
            "markdown.h2.border": "dim",
            "markdown.hr": "dim",
        }
    )
    console = Console(file=io.StringIO(), force_terminal=True, width=80, theme=theme)
    stream = MarkdownStream(console=console, theme=theme, markdown_class=NoInsetMarkdown)

    chunks = [
        "## Title\n",
        "\n- ",
        "item1\n",
        "- ",
        "item2\n",
    ]

    full = ""
    min_stable_line = 0

    for chunk in chunks:
        full += chunk
        stable_source, live_source, stable_line = stream.split_blocks(
            full,
            min_stable_line=min_stable_line,
            final=False,
        )

        stable_ansi = stream.render_stable_ansi(stable_source, has_live_suffix=bool(live_source), final=False)
        live_ansi = stream.render_ansi(live_source, apply_mark=(stable_line == 0))
        live_ansi = stream.normalize_live_ansi_for_boundary(stable_ansi=stable_ansi, live_ansi=live_ansi)

        combined = stable_ansi + live_ansi
        full_ansi = stream.render_ansi(full, apply_mark=True)
        assert combined == full_ansi

        min_stable_line = stable_line


def test_single_line_wrapper_renders_first_line_only() -> None:
    console = Console(file=io.StringIO(), force_terminal=True, width=20)
    wrapped = SingleLine(Text("line1\nline2\nline3"))
    lines = console.render_lines(wrapped, console.options, pad=False)
    assert len(lines) == 1
