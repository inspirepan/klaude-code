import json

from rich.console import Console

from klaude_code.tui.components.rich.theme import get_theme
from klaude_code.tui.components.tools import render_read_tool_call


def _render_to_text(arguments: str) -> str:
    console = Console(width=120, record=True, force_terminal=False, theme=get_theme().app_theme)
    console.print(render_read_tool_call(arguments))
    return console.export_text()


def test_render_read_tool_call_with_numeric_range() -> None:
    output = _render_to_text(
        json.dumps(
            {
                "file_path": "/tmp/a.txt",
                "offset": 10,
                "limit": 5,
            }
        )
    )

    assert "10:14" in output


def test_render_read_tool_call_with_list_offset_does_not_crash() -> None:
    output = _render_to_text(
        json.dumps(
            {
                "file_path": "/tmp/a.txt",
                "offset": [335],
                "limit": 200,
            }
        )
    )

    assert "Read" in output
    assert "offset=[335]" in output
