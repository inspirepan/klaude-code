# pyright: reportPrivateUsage=false

import io

from rich.console import Console
from rich.text import Text

from klaude_code.protocol import events


def _renderer_console(renderer: object) -> Console:
    from klaude_code.tui.renderer import TUICommandRenderer

    assert isinstance(renderer, TUICommandRenderer)
    output = io.StringIO()
    console = Console(file=output, theme=renderer.themes.app_theme, width=100, force_terminal=False)
    console.push_theme(renderer.themes.markdown_theme)
    renderer.console = console
    return console


def _make_stream_recorder():
    lines_only: list[tuple[str, ...]] = []
    full: list[tuple[tuple[str, ...], bool]] = []

    def _sink(lines: tuple[str, ...], end_of_stream: bool) -> None:
        lines_only.append(lines)
        full.append((lines, end_of_stream))

    return lines_only, full, _sink


def test_stream_renderable_updates_prompt_stream_sink() -> None:
    from klaude_code.tui.renderer import TUICommandRenderer

    stream_updates, full_updates, sink = _make_stream_recorder()
    renderer = TUICommandRenderer(stream_sink=sink)
    _renderer_console(renderer)

    renderer.set_stream_renderable(Text("live stream"))

    assert renderer._stream_renderable is not None
    assert stream_updates[-1] == ("live stream",)
    assert full_updates[-1] == (("live stream",), False)


def test_stream_renderable_clear_updates_prompt_stream_sink() -> None:
    from klaude_code.tui.renderer import TUICommandRenderer

    stream_updates, full_updates, sink = _make_stream_recorder()
    renderer = TUICommandRenderer(stream_sink=sink)
    _renderer_console(renderer)

    renderer.set_stream_renderable(Text("live stream"))
    renderer.set_stream_renderable(None)

    assert renderer._stream_renderable is None
    assert stream_updates[-1] == ()
    assert full_updates[-1] == ((), True)


def test_prompt_separator_text_does_not_depend_on_status_lines() -> None:
    from klaude_code.tui.renderer import TUICommandRenderer

    status_updates: list[tuple[tuple[object, ...], str | None]] = []

    def _record_status(lines: tuple[object, ...], separator_text: str | None) -> None:
        status_updates.append((lines, separator_text))

    renderer = TUICommandRenderer(status_sink=_record_status)

    renderer._emit_prompt_status((), "12s · esc to interrupt")

    assert status_updates[-1] == ((), "12s · esc to interrupt")


def test_display_image_prints_caption_then_image(monkeypatch) -> None:
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


def test_display_bash_command_delta_shows_hidden_lines_indicator_and_latest_tail_lines() -> None:
    from klaude_code.tui.components.tools import BASH_OUTPUT_LEFT_PADDING
    from klaude_code.tui.renderer import BASH_LIVE_TAIL_MAX_LINES, TUICommandRenderer

    stream_updates, _full_updates, _sink = _make_stream_recorder()
    renderer = TUICommandRenderer(stream_sink=_sink)
    console = _renderer_console(renderer)

    renderer.display_bash_command_delta(
        events.BashCommandOutputDeltaEvent(
            session_id="s",
            content="".join(f"line-{i}\n" for i in range(12)),
        )
    )

    assert renderer._stream_renderable is not None
    lines = [
        "".join(segment.text for segment in line if not segment.control).rstrip()
        for line in console.render_lines(renderer._stream_renderable, console.options, pad=False)
    ]
    hidden = 12 - BASH_LIVE_TAIL_MAX_LINES
    assert lines[0] == f"{' ' * BASH_OUTPUT_LEFT_PADDING}… (more {hidden} lines)"
    assert lines[1:] == [f"{' ' * BASH_OUTPUT_LEFT_PADDING}line-{i}" for i in range(hidden, 12)]
    assert stream_updates[-1] == tuple(lines)


def test_display_bash_command_end_clears_live_tail() -> None:
    from klaude_code.tui.renderer import TUICommandRenderer

    stream_updates, _full_updates, _sink = _make_stream_recorder()
    renderer = TUICommandRenderer(stream_sink=_sink)
    _renderer_console(renderer)

    renderer.display_bash_command_delta(events.BashCommandOutputDeltaEvent(session_id="s", content="hello"))
    assert renderer._stream_renderable is not None

    renderer.display_bash_command_end(events.BashCommandEndEvent(session_id="s"))

    assert renderer._stream_renderable is None
    assert renderer._bash_stream_active is False
    assert stream_updates[-1] == ()


def test_bash_mode_delta_uses_live_tail_renderable() -> None:
    from klaude_code.tui.components.tools import BASH_OUTPUT_LEFT_PADDING
    from klaude_code.tui.renderer import TUICommandRenderer

    stream_updates, _full_updates, _sink = _make_stream_recorder()
    renderer = TUICommandRenderer(stream_sink=_sink)
    console = _renderer_console(renderer)

    renderer.display_bash_command_start(events.BashCommandStartEvent(session_id="s", command="echo hi"))
    renderer.display_bash_command_delta(events.BashCommandOutputDeltaEvent(session_id="s", content="hello\n"))

    assert renderer._stream_renderable is not None
    lines = [
        "".join(segment.text for segment in line if not segment.control).rstrip()
        for line in console.render_lines(renderer._stream_renderable, console.options, pad=False)
    ]
    assert lines == [f"{' ' * BASH_OUTPUT_LEFT_PADDING}hello"]
    assert stream_updates[-1] == tuple(lines)
