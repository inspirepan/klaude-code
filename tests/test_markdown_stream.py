from __future__ import annotations

import io
import itertools

from hypothesis import given, settings
from hypothesis import strategies as st
from rich.console import Console
from rich.text import Text
from rich.theme import Theme

from klaude_code.tui.components.rich.live import SingleLine
from klaude_code.tui.components.rich.markdown import MarkdownStream, NoInsetMarkdown


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


def _mk_markdown_document(blocks: list[tuple[str, str]]) -> str:
    """Build a markdown document from typed blocks.

    This keeps generation constrained to markdown patterns that Rich+markdown-it
    can render reliably, while still producing a wide variety of boundary cases.
    """

    out: list[str] = []
    for kind, payload in blocks:
        if kind == "para":
            out.append(payload)
            out.append("\n\n")
        elif kind == "heading":
            title = payload.strip() or "Title"
            out.append(f"## {title}\n\n")
        elif kind == "hr":
            out.append("---\n\n")
        elif kind == "list":
            items = [line.strip() or "item" for line in payload.split("\n") if line.strip()]
            if not items:
                items = ["item"]
            out.extend([f"- {it}\n" for it in items[:5]])
            out.append("\n")
        elif kind == "code":
            lang, _, body = payload.partition("\n")
            lang = lang.strip()
            body = body.rstrip("\n")
            out.append(f"```{lang}\n{body}\n```\n\n")
        else:
            raise AssertionError(f"Unknown block kind: {kind}")

    doc = "".join(out)
    # Avoid trailing whitespace-only lines; keep end-of-doc behavior stable.
    return doc.rstrip() + "\n"


def _chunk_text(text: str, cuts: list[int]) -> list[str]:
    """Split text into chunks at cut positions (0..len), preserving order."""

    if not text:
        return [""]

    norm = sorted({c for c in cuts if 0 <= c <= len(text)})
    if not norm or norm[0] != 0:
        norm = [0, *norm]
    if norm[-1] != len(text):
        norm.append(len(text))

    chunks: list[str] = []
    for a, b in itertools.pairwise(norm):
        chunks.append(text[a:b])
    return chunks


_SAFE_TEXT_ALPHABET = st.sampled_from(
    [
        *"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-./:()[]{}'\"\\",
        "\t",
        "\n",
        "\r",
        # Some common CJK characters to exercise width/wrapping behavior.
        *"中文测试你好世界",
    ]
)


@st.composite
def _markdown_blocks(draw: st.DrawFn, *, max_blocks: int = 10) -> list[tuple[str, str]]:
    n = draw(st.integers(min_value=1, max_value=max_blocks))
    blocks: list[tuple[str, str]] = []

    for _ in range(n):
        kind = draw(st.sampled_from(["para", "heading", "hr", "list", "code"]))
        if kind in {"para", "heading"}:
            payload = draw(st.text(_SAFE_TEXT_ALPHABET, min_size=0, max_size=40))
            payload = payload.replace("\r", "")
            blocks.append((kind, payload))
        elif kind == "hr":
            blocks.append(("hr", ""))
        elif kind == "list":
            # 1-5 list items separated by newlines.
            item_count = draw(st.integers(min_value=1, max_value=5))
            items = draw(
                st.lists(
                    st.text(_SAFE_TEXT_ALPHABET, min_size=0, max_size=25), min_size=item_count, max_size=item_count
                )
            )
            items = [it.replace("\n", " ").replace("\r", "").strip() for it in items]
            blocks.append(("list", "\n".join(items)))
        elif kind == "code":
            lang = draw(st.sampled_from(["", "py", "bash", "json", "txt"]))
            line_count = draw(st.integers(min_value=0, max_value=6))
            lines = draw(
                st.lists(
                    st.text(_SAFE_TEXT_ALPHABET, min_size=0, max_size=60),
                    min_size=line_count,
                    max_size=line_count,
                )
            )
            # Keep code free of fence terminators to avoid generating invalid nested fences.
            lines = [ln.replace("```", "``\u200b`").replace("\r", "") for ln in lines]
            payload = f"{lang}\n" + "\n".join(lines)
            blocks.append(("code", payload))
        else:
            raise AssertionError(f"Unknown block kind: {kind}")

    return blocks


@st.composite
def _markdown_with_cuts(draw: st.DrawFn) -> tuple[str, list[int]]:
    blocks = draw(_markdown_blocks())
    doc = _mk_markdown_document(blocks)

    # Choose 1..min(30, len(doc)) cut points; they intentionally can land mid-token.
    cut_count = draw(st.integers(min_value=1, max_value=min(30, max(1, len(doc)))))
    cuts = draw(st.lists(st.integers(min_value=0, max_value=len(doc)), min_size=cut_count, max_size=cut_count))
    return doc, cuts


@given(_markdown_with_cuts())
@settings(max_examples=25, deadline=None)
def test_markdown_stream_property_frame_equivalence(payload: tuple[str, list[int]]) -> None:
    """Property: streaming split renders identically to full render at every prefix."""

    doc, cuts = payload
    chunks = _chunk_text(doc, cuts)

    stream = _make_stream(width=100)

    full = ""
    stable_rendered_prev = ""
    min_stable_line = 0

    for chunk in chunks:
        full += chunk

        stable_source, live_source, stable_line = stream.split_blocks(
            full,
            min_stable_line=min_stable_line,
            final=False,
        )

        assert stable_source + live_source == full
        assert stable_line >= min_stable_line

        stable_ansi = stream.render_stable_ansi(
            stable_source,
            has_live_suffix=bool(live_source),
            final=False,
        )
        live_ansi = stream.render_ansi(live_source, apply_mark=(stable_line == 0))
        live_ansi = stream.normalize_live_ansi_for_boundary(stable_ansi=stable_ansi, live_ansi=live_ansi)

        combined = stable_ansi + live_ansi
        full_ansi = stream.render_ansi(full, apply_mark=True)
        assert combined == full_ansi

        assert stable_ansi.startswith(stable_rendered_prev)
        stable_rendered_prev = stable_ansi
        min_stable_line = stable_line
