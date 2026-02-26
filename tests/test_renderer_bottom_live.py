# pyright: reportPrivateUsage=false

import io

from rich.console import Console
from rich.padding import Padding
from rich.text import Text


def test_bottom_height_shrink_padding_not_applied_with_live_stream() -> None:
    from klaude_code.tui.renderer import TUICommandRenderer

    renderer = TUICommandRenderer()
    output = io.StringIO()
    renderer.console = Console(file=output, theme=renderer.themes.app_theme, width=100, force_terminal=False)
    renderer.console.push_theme(renderer.themes.markdown_theme)

    renderer._spinner_visible = True
    renderer._stream_renderable = Text("live stream")
    renderer._stream_last_height = 1
    renderer._stream_last_width = renderer.console.size.width
    renderer._stream_max_height = 1
    renderer._bottom_last_height = 8

    renderable = renderer._bottom_renderable()

    assert not isinstance(renderable, Padding)
    assert renderer._bottom_last_height == len(
        renderer.console.render_lines(renderable, renderer.console.options, pad=False)
    )
