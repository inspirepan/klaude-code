from __future__ import annotations

import io
import re
from pathlib import Path

from rich.console import Console
from rich.text import Text
from rich.theme import Theme

from klaude_code.tui.components.rich.live import SingleLine
from klaude_code.tui.components.rich.markdown import MarkdownStream

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


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


def test_update_invokes_image_callback_for_local_svg(tmp_path: Path) -> None:
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
    displayed: list[str] = []
    captions: list[str | None] = []

    def _on_image(path: str, caption: str | None) -> None:
        displayed.append(path)
        captions.append(caption)

    stream = MarkdownStream(console=console, theme=theme, left_margin=0, image_callback=_on_image)

    svg_path = tmp_path / "render-mermaid-arch.svg"
    svg_path.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')

    stream.update(f"![Mermaid 架构图]({svg_path})", final=True)

    assert displayed == [str(svg_path)]
    assert captions == ["Mermaid 架构图"]


def test_update_renders_local_image_markdown_placeholder_with_name(tmp_path: Path) -> None:
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
    displayed: list[str] = []
    captions: list[str | None] = []

    def _on_image(path: str, caption: str | None) -> None:
        displayed.append(path)
        captions.append(caption)

    stream = MarkdownStream(console=console, theme=theme, left_margin=0, image_callback=_on_image)

    svg_path = tmp_path / "render-mermaid-test-flow.png"
    svg_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    alt = "FlowCaption"
    stream.update(f"![{alt}]({svg_path})", final=True)

    rendered_compact = "".join(out.getvalue().split())
    expected_compact = "".join(f"![{alt}]({svg_path})".split())
    assert expected_compact in rendered_compact
    assert displayed == [str(svg_path)]
    assert captions == [alt]


def test_render_stable_ansi_preserves_ordered_item_before_local_image(tmp_path: Path) -> None:
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
    console = Console(file=out, force_terminal=True, width=120, theme=theme)
    stream = MarkdownStream(console=console, theme=theme, left_margin=0)

    flow = tmp_path / "flow.png"
    seq = tmp_path / "seq.png"
    flow.write_bytes(b"\x89PNG\r\n\x1a\n")
    seq.write_bytes(b"\x89PNG\r\n\x1a\n")

    source = f"1) Flowchart\n![Flow]({flow})\n2) Sequence Diagram\n![Sequence]({seq})\n"

    ansi, _ = stream.render_stable_ansi(source, has_live_suffix=False, final=True)
    compact = "".join(_ANSI_ESCAPE_RE.sub("", ansi).split())
    flow_text_idx = compact.index("Flowchart")
    flow_image_idx = compact.index("".join(f"![Flow]({flow})".split()))
    seq_text_idx = compact.index("SequenceDiagram")
    seq_image_idx = compact.index("".join(f"![Sequence]({seq})".split()))

    assert flow_text_idx < flow_image_idx < seq_text_idx < seq_image_idx


def test_update_does_not_invoke_image_callback_for_live_only_image_block(tmp_path: Path) -> None:
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
    displayed: list[str] = []
    captions: list[str | None] = []

    def _sink(renderable: object) -> None:
        live_calls.append(renderable)

    def _on_image(path: str, caption: str | None) -> None:
        displayed.append(path)
        captions.append(caption)

    stream = MarkdownStream(console=console, theme=theme, live_sink=_sink, left_margin=0, image_callback=_on_image)
    stream.min_delay = 0

    svg_path = tmp_path / "live-image.svg"
    svg_path.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')

    stream.update(f"![Live 图]({svg_path})", final=False)

    assert displayed == []
    assert captions == []
    assert live_calls == []


def test_update_does_not_drop_ordered_list_item_after_incomplete_marker_prefix() -> None:
    theme = Theme(
        {
            "markdown.code.border": "dim",
            "markdown.code.block": "dim",
            "markdown.h1": "bold",
            "markdown.h2.border": "dim",
            "markdown.hr": "dim",
        }
    )

    text = "9. a\n\n4. b\n\n---"

    streamed_out = io.StringIO()
    streamed_console = Console(file=streamed_out, force_terminal=True, width=80, theme=theme)
    streamed = MarkdownStream(console=streamed_console, theme=theme, left_margin=0, live_sink=lambda _: None)
    streamed.min_delay = 0
    streamed.update("9. a\n\n4", final=False)
    streamed.update(text, final=True)

    direct_out = io.StringIO()
    direct_console = Console(file=direct_out, force_terminal=True, width=80, theme=theme)
    direct = MarkdownStream(console=direct_console, theme=theme, left_margin=0, live_sink=lambda _: None)
    direct.min_delay = 0
    direct.update(text, final=True)

    streamed_plain = _ANSI_ESCAPE_RE.sub("", streamed_out.getvalue())
    direct_plain = _ANSI_ESCAPE_RE.sub("", direct_out.getvalue())
    assert streamed_plain == direct_plain
    assert "10 b" in streamed_plain


def test_update_preserves_numbered_heading_after_prefix_frame() -> None:
    theme = Theme(
        {
            "markdown.code.border": "dim",
            "markdown.code.block": "dim",
            "markdown.h1": "bold",
            "markdown.h2.border": "dim",
            "markdown.hr": "dim",
        }
    )

    text = (
        "1. **开启 Gateway 代理 + TCP**\n"
        "\n"
        "2. **创建 Network Allow 规则（放行你的 SSH）**\n"
        "\n"
        "3. **检查 WARP Device Profile 的 Split Tunnel**\n"
    )
    cut = text.index("\n\n2") + 3  # stream frame ends at an incomplete list marker prefix: "...\n\n2"

    streamed_out = io.StringIO()
    streamed_console = Console(file=streamed_out, force_terminal=True, width=100, theme=theme)
    streamed = MarkdownStream(console=streamed_console, theme=theme, left_margin=0, live_sink=lambda _: None)
    streamed.min_delay = 0
    streamed.update(text[:cut], final=False)
    streamed.update(text, final=True)

    direct_out = io.StringIO()
    direct_console = Console(file=direct_out, force_terminal=True, width=100, theme=theme)
    direct = MarkdownStream(console=direct_console, theme=theme, left_margin=0, live_sink=lambda _: None)
    direct.min_delay = 0
    direct.update(text, final=True)

    streamed_plain = _ANSI_ESCAPE_RE.sub("", streamed_out.getvalue())
    direct_plain = _ANSI_ESCAPE_RE.sub("", direct_out.getvalue())
    assert streamed_plain == direct_plain
    assert "创建 Network Allow 规则（放行你的 SSH）" in streamed_plain
