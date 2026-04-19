from rich.console import Console

from klaude_code.protocol.models import ReadPreviewLine, ReadPreviewUIExtra
from klaude_code.tui.components.tools import render_read_preview


def test_render_read_preview_uses_unified_more_lines_indicator() -> None:
    rendered = render_read_preview(
        ReadPreviewUIExtra(
            lines=[
                ReadPreviewLine(line_no=10, content="alpha"),
                ReadPreviewLine(line_no=11, content="beta"),
            ],
            remaining_lines=3,
        )
    )

    console = Console(width=80, force_terminal=False)
    lines = console.render_lines(rendered, console.options, pad=False)
    plain = ["".join(segment.text for segment in line if not segment.control).rstrip() for line in lines]

    assert plain == ["  10 alpha", "  11 beta", "   … (more 3 lines)"]

def test_render_read_preview_truncates_long_line_with_ellipsis() -> None:
    rendered = render_read_preview(
        ReadPreviewUIExtra(
            lines=[ReadPreviewLine(line_no=1, content="x" * 40)],
            remaining_lines=0,
        )
    )

    console = Console(width=20, force_terminal=False)
    lines = console.render_lines(rendered, console.options, pad=False)
    plain = ["".join(segment.text for segment in line if not segment.control).rstrip() for line in lines]

    assert plain == ["   1 xxxxxxxxxxxxxx…"]

def test_render_read_preview_keeps_more_lines_indicator_on_one_line() -> None:
    rendered = render_read_preview(
        ReadPreviewUIExtra(
            lines=[ReadPreviewLine(line_no=1, content="abcdefghij")],
            remaining_lines=123,
        )
    )

    console = Console(width=10, force_terminal=False)
    lines = console.render_lines(rendered, console.options, pad=False)
    plain = ["".join(segment.text for segment in line if not segment.control).rstrip() for line in lines]

    assert len(plain) == 2
    assert plain[1].startswith("   …")
    assert plain[1].endswith("…")
