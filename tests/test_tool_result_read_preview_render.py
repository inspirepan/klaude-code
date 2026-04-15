from rich.console import Console

from klaude_code.protocol import model
from klaude_code.tui.components.tools import render_read_preview


def test_render_read_preview_uses_unified_more_lines_indicator() -> None:
    rendered = render_read_preview(
        model.ReadPreviewUIExtra(
            lines=[
                model.ReadPreviewLine(line_no=10, content="alpha"),
                model.ReadPreviewLine(line_no=11, content="beta"),
            ],
            remaining_lines=3,
        )
    )

    console = Console(width=80, force_terminal=False)
    lines = console.render_lines(rendered, console.options, pad=False)
    plain = ["".join(segment.text for segment in line if not segment.control).rstrip() for line in lines]

    assert plain == ["  10  alpha", "  11  beta", "   …  (more 3 lines)"]