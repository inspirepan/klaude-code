# pyright: reportPrivateUsage=false

import io

import pytest
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


def test_display_image_prints_caption_then_image(monkeypatch: pytest.MonkeyPatch) -> None:
    from klaude_code.tui import renderer as renderer_module
    from klaude_code.tui.renderer import TUICommandRenderer

    renderer = TUICommandRenderer()
    output = io.StringIO()
    renderer.console = Console(file=output, theme=renderer.themes.app_theme, width=100, force_terminal=False)
    renderer.console.push_theme(renderer.themes.markdown_theme)

    called: list[str] = []

    def _fake_print_kitty_image(file_path: str, *, file: io.StringIO | None = None) -> None:
        called.append(file_path)
        (file or output).write("<image>\n")

    monkeypatch.setattr(renderer_module, "print_kitty_image", _fake_print_kitty_image)

    renderer.display_image("/tmp/demo.png", "Demo")

    assert called == ["/tmp/demo.png"]
    rendered = output.getvalue()
    assert "\n↓ Demo\n" in rendered
    assert "<image>\n" in rendered
    assert rendered.index("↓ Demo") < rendered.index("<image>\n")
