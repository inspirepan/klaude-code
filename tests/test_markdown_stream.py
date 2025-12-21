from __future__ import annotations

import io

from rich.console import Console
from rich.theme import Theme

from klaude_code.ui.rich.markdown import MarkdownStream


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
