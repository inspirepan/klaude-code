# pyright: reportPrivateUsage=false

import io
from pathlib import Path

from rich.console import Console, RenderableType
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


def test_prompt_separator_text_can_be_sent_without_status_lines() -> None:
    from klaude_code.tui.renderer import TUICommandRenderer

    status_updates: list[tuple[tuple[object, ...], str | None]] = []

    def _record_status(lines: tuple[object, ...], separator_text: str | None, _reset_reserved_height: bool) -> None:
        status_updates.append((lines, separator_text))

    renderer = TUICommandRenderer(status_sink=_record_status)

    renderer._emit_prompt_status((), "12s · esc to interrupt")

    assert status_updates[-1] == ((), "12s · esc to interrupt")


def test_spinner_update_forwards_reserved_height_reset() -> None:
    from klaude_code.tui.renderer import TUICommandRenderer

    status_updates: list[tuple[tuple[object, ...], str | None, bool]] = []

    def _record_status(lines: tuple[object, ...], separator_text: str | None, reset_reserved_height: bool) -> None:
        status_updates.append((lines, separator_text, reset_reserved_height))

    renderer = TUICommandRenderer(status_sink=_record_status)

    renderer.spinner_update(reset_bottom_height=True)

    assert status_updates[-1] == ((), None, True)


def test_spinner_stop_clears_prompt_separator_text() -> None:
    from klaude_code.tui.renderer import TUICommandRenderer

    status_updates: list[tuple[tuple[object, ...], str | None]] = []

    def _record_status(lines: tuple[object, ...], separator_text: str | None, _reset_reserved_height: bool) -> None:
        status_updates.append((lines, separator_text))

    renderer = TUICommandRenderer(status_sink=_record_status)

    renderer.spinner_update(separator_text="12s · esc to interrupt")
    renderer.spinner_stop()

    assert status_updates[-1] == ((), None)


def test_spinner_stop_keeps_prompt_metadata_footer() -> None:
    from rich.text import Text

    from klaude_code.tui.commands import PromptStatusLine
    from klaude_code.tui.renderer import TUICommandRenderer

    status_updates: list[tuple[tuple[PromptStatusLine, ...], str | None]] = []

    def _record_status(
        lines: tuple[PromptStatusLine, ...], separator_text: str | None, _reset_reserved_height: bool
    ) -> None:
        status_updates.append((lines, separator_text))

    renderer = TUICommandRenderer(status_sink=_record_status)
    _renderer_console(renderer)

    renderer.spinner_update(metadata_text=Text("in 82.3k · cache 633.3k (99%) · cost $0.7971"))
    renderer.spinner_stop()

    lines, separator_text = status_updates[-1]
    assert [(line.text, line.kind) for line in lines] == [("in 82.3k · cache 633.3k (99%) · cost $0.7971", "metadata")]
    assert separator_text is None


def test_sub_agent_status_sink_preserves_identity_color() -> None:
    from klaude_code.protocol.models import SubAgentState
    from klaude_code.tui.commands import PromptStatusLine, SpinnerStatusLine
    from klaude_code.tui.components.rich.theme import ThemeKey
    from klaude_code.tui.renderer import TUICommandRenderer

    status_updates: list[tuple[tuple[PromptStatusLine, ...], str | None]] = []
    renderer = TUICommandRenderer(
        status_sink=lambda lines, separator, _reset: status_updates.append((lines, separator))
    )
    _renderer_console(renderer)
    renderer.register_session(
        "child",
        SubAgentState(
            sub_agent_type="finder",
            sub_agent_desc="inspect status",
            sub_agent_prompt="prompt",
        ),
    )
    renderer.set_progress_ui_suspended(True)
    renderer.spinner_start()
    status = Text()
    status.append("Finder", style=ThemeKey.STATUS_TEXT_BOLD)
    status.append(": ", style=ThemeKey.STATUS_TEXT)
    description_start = len(status)
    status.append("inspect status", style=ThemeKey.STATUS_TEXT)
    status.stylize("italic", description_start, len(status))
    status.append(" ")
    status.append("✓", style=ThemeKey.METADATA_GREEN)
    status.append(" · 2s", style=ThemeKey.STATUS_HINT)
    renderer.spinner_update(
        status_lines=(
            SpinnerStatusLine(
                text=status,
                session_id="child",
                sub_agent_animated=False,
                is_sub_agent=True,
            ),
            SpinnerStatusLine(
                text=Text("Found the issue…"),
                session_id="child",
                sub_agent_continuation=True,
                is_sub_agent=True,
            ),
        )
    )

    line, result_line = status_updates[-1][0]
    assert line.text == " ●  Finder: inspect status ✓ · 2s"
    assert line.fragments
    assert line.show_spinner is False
    assert line.suppress_top_spacer is False
    assert "".join(text for _, text in line.fragments) == line.text
    assert line.inline_spinner_style is None
    assert line.fragments[0][0].startswith("fg:#")
    title_style = next(style for style, text in line.fragments if "Finder" in text)
    colon_style = next(style for style, text in line.fragments if ": " in text)
    description_style = next(style for style, text in line.fragments if "inspect status" in text)
    assert "bold" in title_style
    assert "bold" not in colon_style
    assert "italic" not in colon_style
    assert "bold" not in description_style
    assert "italic" in description_style
    success_index = next(index for index, (_, text) in enumerate(line.fragments) if "✓" in text)
    success_style = line.fragments[success_index][0]
    assert success_style.startswith("fg:#")
    assert "bold" not in success_style
    assert "reverse" not in success_style
    assert line.fragments[success_index - 1] == ("class:meta", " ")
    assert result_line.text == "      ↳ Found the issue…"
    assert result_line.show_spinner is False
    assert result_line.suppress_top_spacer is False


def test_sub_agent_status_reuses_assistant_stream_boundary() -> None:
    import asyncio

    from rich.text import Text

    from klaude_code.protocol.models import SubAgentState
    from klaude_code.tui.commands import (
        AppendAssistant,
        EndAssistantStream,
        PromptStatusLine,
        SpinnerStatusLine,
        StartAssistantStream,
    )
    from klaude_code.tui.renderer import TUICommandRenderer

    status_updates: list[tuple[PromptStatusLine, ...]] = []
    renderer = TUICommandRenderer(
        status_sink=lambda lines, _separator, _reset: status_updates.append(lines)
    )
    _renderer_console(renderer)
    renderer.register_session(
        "child",
        SubAgentState(sub_agent_type="finder", sub_agent_desc="search", sub_agent_prompt="prompt"),
    )
    renderer.set_progress_ui_suspended(True)
    renderer.spinner_start()
    asyncio.run(
        renderer.execute(
            [
                StartAssistantStream(session_id="main"),
                AppendAssistant(session_id="main", content="Starting finder."),
                EndAssistantStream(session_id="main"),
            ]
        )
    )

    renderer._spinner_last_apply_at = 0.0
    renderer.spinner_update(
        status_lines=(SpinnerStatusLine(text=Text("Finder: search"), session_id="child", is_sub_agent=True),)
    )

    assert status_updates[-1][0].suppress_top_spacer is True


def test_active_sub_agent_status_uses_colored_inline_spinner() -> None:
    from klaude_code.protocol.models import SubAgentState
    from klaude_code.tui.commands import PromptStatusLine, SpinnerStatusLine
    from klaude_code.tui.components.rich.theme import ThemeKey
    from klaude_code.tui.renderer import TUICommandRenderer

    status_updates: list[tuple[tuple[PromptStatusLine, ...], str | None]] = []
    renderer = TUICommandRenderer(
        status_sink=lambda lines, separator, _reset: status_updates.append((lines, separator))
    )
    _renderer_console(renderer)
    renderer.register_session(
        "child",
        SubAgentState(sub_agent_type="finder", sub_agent_desc="inspect status", sub_agent_prompt="prompt"),
    )
    renderer.set_progress_ui_suspended(True)
    renderer.spinner_start()
    tool_status = Text()
    tool_status.append("Bash", style=ThemeKey.TOOL_NAME)
    tool_status.append(" inspect files ✓")
    transcript_tool_segment = next(
        segment for segment in renderer.console.render(tool_status) if "Bash" in segment.text
    )
    assert transcript_tool_segment.style is not None
    assert transcript_tool_segment.style.bold is True
    active_status = Text()
    active_status.append("Finder", style=ThemeKey.STATUS_TEXT_BOLD)
    active_status.append(": ", style=ThemeKey.STATUS_TEXT)
    description_start = len(active_status)
    active_status.append("inspect status", style=ThemeKey.STATUS_TEXT)
    active_status.stylize("italic", description_start, len(active_status))
    active_status.append(" · Thinking… · 2s", style=ThemeKey.STATUS_HINT)
    renderer.spinner_update(
        status_lines=(
            SpinnerStatusLine(text=active_status, session_id="child"),
            SpinnerStatusLine(text=tool_status, session_id="child", sub_agent_continuation=True),
        )
    )

    line, tool_line = status_updates[-1][0]
    assert line.text == "··· Finder: inspect status · Thinking… · 2s"
    assert line.show_spinner is False
    assert line.inline_spinner_style is not None
    assert line.inline_spinner_style.startswith("fg:#")
    assert "".join(text for _, text in line.fragments) == "Finder: inspect status · Thinking… · 2s"
    title_style = next(style for style, text in line.fragments if "Finder" in text)
    colon_style = next(style for style, text in line.fragments if ": " in text)
    description_style = next(style for style, text in line.fragments if "inspect status" in text)
    assert "bold" in title_style
    assert "bold" not in colon_style
    assert "italic" not in colon_style
    assert "bold" not in description_style
    assert "italic" in description_style
    assert tool_line.text == "      ↳ Bash inspect files ✓"
    assert tool_line.show_spinner is False
    assert tool_line.inline_spinner_style is None
    tool_name_style = next(style for style, text in tool_line.fragments if "Bash" in text)
    assert "bold" not in tool_name_style


def test_interactive_status_snapshot_does_not_use_rich_shimmer(monkeypatch) -> None:
    from klaude_code.tui.commands import SpinnerStatusLine
    from klaude_code.tui.components.rich import status as status_module
    from klaude_code.tui.renderer import TUICommandRenderer

    def _unexpected_shimmer(_text: str) -> list[tuple[str, float]]:
        raise AssertionError("interactive status should use only the prompt-toolkit spinner")

    monkeypatch.setattr(status_module, "_shimmer_profile", _unexpected_shimmer)
    renderer = TUICommandRenderer(status_sink=lambda lines, separator, reset: None)
    _renderer_console(renderer)
    renderer.set_progress_ui_suspended(True)
    renderer.spinner_start()
    renderer.spinner_update(status_lines=(SpinnerStatusLine(text=Text("Bashing…")),))


def test_display_image_prints_caption_then_image(monkeypatch, tmp_path: Path) -> None:
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

    image_path = tmp_path / "demo.png"
    image_path.write_bytes(b"image")
    renderer.display_image(str(image_path), "Demo")

    assert called == [str(image_path)]
    rendered = output.getvalue()
    assert "\n↓ Demo\n" in rendered
    assert "<image>\n" in rendered
    assert rendered.index("↓ Demo") < rendered.index("<image>\n")


def test_display_image_renders_missing_file_as_indented_tool_output(monkeypatch, tmp_path: Path) -> None:
    from klaude_code.tui.components.rich.theme import ThemeKey
    from klaude_code.tui.components.tools import TOOL_SUBJECT_INDENT, AdaptiveIndent
    from klaude_code.tui.renderer import TUICommandRenderer

    renderer = TUICommandRenderer()
    rendered: list[RenderableType] = []
    monkeypatch.setattr(renderer, "print", rendered.append)

    missing_path = tmp_path / "missing.png"
    renderer.display_image(str(missing_path))

    assert len(rendered) == 1
    padded = rendered[0]
    assert isinstance(padded, AdaptiveIndent)
    assert padded.indent == TOOL_SUBJECT_INDENT
    inner = padded.renderable
    assert isinstance(inner, Text)
    assert inner.plain == f"Image not found: {missing_path}"
    assert inner.style == ThemeKey.TOOL_RESULT

    output = io.StringIO()
    console = Console(file=output, width=12, force_terminal=False, theme=renderer.themes.app_theme)
    console.print(padded)
    assert output.getvalue().strip().startswith("Image")


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


def test_bash_live_tail_throttles_renders_and_flushes_trailing_content() -> None:
    import asyncio

    from klaude_code.tui.renderer import BASH_LIVE_TAIL_MIN_INTERVAL_S, TUICommandRenderer

    stream_updates, _full_updates, _sink = _make_stream_recorder()
    renderer = TUICommandRenderer(stream_sink=_sink)
    _renderer_console(renderer)

    async def _scenario() -> None:
        renderer.display_bash_command_start(events.BashCommandStartEvent(session_id="s", command="spam"))
        renderer.display_bash_command_delta(events.BashCommandOutputDeltaEvent(session_id="s", content="one\n"))
        renders_after_first = len(stream_updates)
        assert any("one" in line for line in stream_updates[-1])

        # A burst within the throttle window must not repaint immediately...
        renderer.display_bash_command_delta(events.BashCommandOutputDeltaEvent(session_id="s", content="two\n"))
        renderer.display_bash_command_delta(events.BashCommandOutputDeltaEvent(session_id="s", content="three\n"))
        assert len(stream_updates) == renders_after_first

        # ...but the trailing flush must render the accumulated tail.
        await asyncio.sleep(BASH_LIVE_TAIL_MIN_INTERVAL_S + 0.03)
        assert len(stream_updates) > renders_after_first
        assert any("three" in line for line in stream_updates[-1])

    asyncio.run(_scenario())


def test_spinner_update_dedupes_identical_dynamic_content() -> None:
    from klaude_code.tui.commands import SpinnerStatusLine
    from klaude_code.tui.components.rich.status import DynamicText, ResponsiveDynamicText
    from klaude_code.tui.renderer import TUICommandRenderer

    status_updates: list[tuple[tuple[object, ...], str | None]] = []
    renderer = TUICommandRenderer(
        status_sink=lambda lines, separator, _reset: status_updates.append((lines, separator))
    )
    _renderer_console(renderer)
    renderer.set_progress_ui_suspended(True)
    renderer.spinner_start()

    emits_after_start = len(status_updates)

    def _update(content: str, *, right: str) -> None:
        renderer.spinner_update(
            metadata_text=ResponsiveDynamicText(lambda: Text(right), lambda: Text(right)),
            status_lines=(SpinnerStatusLine(text=DynamicText(lambda: Text(content))),),
        )

    _update("Thinking", right="in 1k")
    assert len(status_updates) == emits_after_start + 1

    # New DynamicText / ResponsiveDynamicText instances with identical rendered
    # content must be deduped: nothing visible changed.
    _update("Thinking", right="in 1k")
    _update("Thinking", right="in 1k")
    assert len(status_updates) == emits_after_start + 1

    _update("Composing", right="in 1k")
    assert len(status_updates) == emits_after_start + 2
    _update("Composing", right="in 2k")
    assert len(status_updates) == emits_after_start + 3


def test_spinner_update_throttles_burst_and_flushes_trailing() -> None:
    import asyncio

    from klaude_code.tui.commands import PromptStatusLine, SpinnerStatusLine
    from klaude_code.tui.renderer import SPINNER_UPDATE_MIN_INTERVAL_S, TUICommandRenderer

    status_updates: list[tuple[tuple[PromptStatusLine, ...], str | None, bool]] = []
    renderer = TUICommandRenderer(
        status_sink=lambda lines, separator, reset: status_updates.append((lines, separator, reset))
    )
    _renderer_console(renderer)
    renderer.set_progress_ui_suspended(True)

    async def _scenario() -> None:
        renderer.spinner_start()
        emits_after_start = len(status_updates)

        renderer.spinner_update(status_lines=(SpinnerStatusLine(text=Text("one")),))
        assert len(status_updates) == emits_after_start + 1

        # Distinct updates inside the throttle window coalesce: no immediate emit.
        renderer.spinner_update(
            status_lines=(SpinnerStatusLine(text=Text("two")),),
            reset_bottom_height=True,
        )
        renderer.spinner_update(status_lines=(SpinnerStatusLine(text=Text("three")),))
        assert len(status_updates) == emits_after_start + 1

        # The trailing flush applies the newest state exactly once.
        await asyncio.sleep(SPINNER_UPDATE_MIN_INTERVAL_S + 0.05)
        assert len(status_updates) == emits_after_start + 2
        assert status_updates[-1][0][0].text == "three"
        assert status_updates[-1][2] is True

        # spinner_stop flushes any pending state synchronously.
        renderer.spinner_update(status_lines=(SpinnerStatusLine(text=Text("four")),))
        renderer.spinner_update(status_lines=(SpinnerStatusLine(text=Text("five")),))
        renderer.spinner_stop()
        assert any(update[0] and update[0][0].text == "five" for update in status_updates)

    asyncio.run(_scenario())


def test_manual_status_flush_cancels_scheduled_flush() -> None:
    import asyncio

    from klaude_code.tui.commands import PromptStatusLine, SpinnerStatusLine
    from klaude_code.tui.renderer import SPINNER_UPDATE_MIN_INTERVAL_S, TUICommandRenderer

    status_updates: list[tuple[tuple[PromptStatusLine, ...], str | None]] = []
    renderer = TUICommandRenderer(
        status_sink=lambda lines, separator, _reset: status_updates.append((lines, separator))
    )
    _renderer_console(renderer)
    renderer.set_progress_ui_suspended(True)

    async def _scenario() -> None:
        renderer.spinner_start()
        renderer.spinner_update(status_lines=(SpinnerStatusLine(text=Text("one")),))
        renderer.spinner_update(status_lines=(SpinnerStatusLine(text=Text("two")),))
        assert renderer._spinner_flush_handle is not None

        # A periodic refresh applies the pending update immediately and must
        # cancel the scheduled flush so the next update starts a fresh window.
        await asyncio.sleep(0.01)
        emits_before_refresh = len(status_updates)
        renderer.refresh_prompt_status()
        assert len(status_updates) == emits_before_refresh + 1
        assert renderer._spinner_flush_handle is None

        renderer.spinner_update(status_lines=(SpinnerStatusLine(text=Text("three")),))
        assert renderer._spinner_flush_handle is not None
        await asyncio.sleep(SPINNER_UPDATE_MIN_INTERVAL_S + 0.05)
        assert status_updates[-1][0][0].text == "three"

    asyncio.run(_scenario())


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
